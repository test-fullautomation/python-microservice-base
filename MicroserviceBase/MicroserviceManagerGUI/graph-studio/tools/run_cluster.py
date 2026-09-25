"""Persistent in-process signal cluster for Graph Studio's Run/Monitor features.

Keeps ``signal-discovery`` + one or more ``signal_graph`` services running on
FIXED ports until stopped (Ctrl-C / SIGTERM / stdin closed), so Graph Studio
can monitor them over gRPC. Everything is mocked (device + measurement store):
no Consul, no DB. Graph ports come from each graph.json ``service.grpc_port``.

    python run_cluster.py --signals-root <repo>/services/signals --all
    python run_cluster.py --signals-root <repo>/services/signals --config path/to/graph.json

``--signals-root`` is the directory that contains the ``signal_graph``,
``signal_discovery`` and ``common`` packages (the signals repository's
``services/signals``, or the tool's ``reference/signals`` snapshot).

Runner-side hooks — the two extension points the UDS block stories need but
signal_graph does not have yet (see the extraction explainer §4). They are
applied HERE, for local mocked runs only, so a graph with extra block
packages can be started before the hook PR is merged:

* ``"block_modules": ["uds_blocks.blocks"]`` in graph.json → imported before
  the graph is built (registers the block types and the adapter kinds).
* ``"device_kinds": {"uds_tester": "uds_blocks.tester"}`` in graph.json → that
  logical device gets the kind's MOCK adapter (``<pkg>.adapters.registry.
  MOCK_ADAPTER``) instead of the built-in mock device adapter.
* ``"mock_scripts": {"uds_tester": [["periodic:52", {"BatteryVoltage": 12500}, 0]]}``
  (optional, local runs only) → handed to that mock adapter as ``script=``
  so the graph shows moving values instead of None.

``device_kinds`` is inferred when absent: a device referenced by a block
from an imported package gets that package's kind. ``device_kinds`` and
``mock_scripts`` may also live in a ``<graph>.mock.json`` sidecar next to
the graph so the deployable graph.json stays clean.

All three keys are ignored by signal_graph's own loader (pydantic drops
unknown keys) and preserved by Graph Studio's lossless round-trip.

Bench mode — a second sidecar, ``<graph>.bench.json`` with ``"enabled": true``,
turns the mocked local run into a member of the running bench:

* ``"registry": {"backend": "consul", "host": "127.0.0.1", "port": 8500}`` →
  the cluster registers in that Consul instead of an in-memory registry, so
  the bench's own ``signal-discovery`` lists the graph and real adapters can
  resolve real services by name. The Consul client here uses the standard
  library only, so the Run interpreter needs nothing installed for it.
* If a ``signal-discovery`` is already registered there, it is used and no
  local one is started; otherwise a local one starts and registers itself.
* ``"real_kinds": ["uds_tester"]`` → those logical devices get the kind's
  REAL adapter (``<pkg>.adapters.registry.KINDS[kind]``) instead of the mock;
  devices not listed keep the mock and its script.

This file belongs to Graph Studio, not to the signals code.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import os
import signal
import sys
import urllib.error
import urllib.parse
import urllib.request

SHIPPED = ["signal-in", "signal-out", "signal-proc-foo-bar"]


class StdlibConsulRegistry:
    """The signal layer's ServiceRegistryPort over Consul's HTTP API, with urllib
    on a worker thread. Same payload shape as the layer's own Consul adapter,
    so a graph registered here looks identical to one deployed by Nomad, minus
    a health check: Consul reports a check-less service as passing."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8500) -> None:
        self._base = f"http://{host}:{port}"

    async def _call(self, method: str, path: str, body=None, params=None):
        url = self._base + path + (("?" + urllib.parse.urlencode(params)) if params else "")
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={"Content-Type": "application/json"} if data else {})

        def do():
            with urllib.request.urlopen(req, timeout=5) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else None

        return await asyncio.get_running_loop().run_in_executor(None, do)

    async def register(self, name, host, port, service_type, meta=None) -> str:
        service_id = f"{name}-{host}-{port}"
        await self._call("PUT", "/v1/agent/service/register", body={
            "ID": service_id, "Name": name, "Address": host, "Port": port,
            "Tags": [f"service-type={service_type}"],
            "Meta": {"service-type": service_type, **(meta or {})},
        })
        return service_id

    async def deregister(self, service_id: str) -> None:
        await self._call("PUT", f"/v1/agent/service/deregister/{service_id}")

    async def resolve(self, name: str):
        found = await self._health(name)
        return found[0] if found else None

    async def list_by_type(self, service_type: str):
        catalog = await self._call("GET", "/v1/catalog/services") or {}
        tag = f"service-type={service_type}"
        result = []
        for svc_name, tags in catalog.items():
            if tag in (tags or []):
                result.extend(await self._health(svc_name, service_type))
        return result

    async def _health(self, name: str, service_type: str = ""):
        from common.ports import RegisteredService

        entries = await self._call("GET", f"/v1/health/service/{name}", params={"passing": "true"}) or []
        out = []
        for entry in entries:
            svc = entry["Service"]
            meta = svc.get("Meta") or {}
            out.append(RegisteredService(name=svc["Service"], host=svc.get("Address") or entry["Node"]["Address"],
                                         port=svc["Port"], service_type=service_type or meta.get("service-type", ""),
                                         meta=meta))
        return out

    async def close(self) -> None:
        pass


def _bench_path(path: str) -> str:
    """``graph.json`` → ``graph.bench.json`` (same directory)."""
    stem, _ext = os.path.splitext(path)
    return stem + ".bench.json"


def _bench_extras(path: str) -> dict | None:
    """The bench sidecar when present and enabled, else None."""
    side = _bench_path(path)
    if not os.path.exists(side):
        return None
    with open(side, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not data.get("enabled", False):
        print(f"  bench sidecar present but enabled=false, mocked run: {side}", flush=True)
        return None
    print(f"  bench sidecar: {side}", flush=True)
    return data


def _prepare_sys_path(root: str) -> None:
    root = os.path.abspath(root)
    for needed in ("signal_graph", "signal_discovery", "common"):
        if not os.path.isdir(os.path.join(root, needed)):
            sys.exit(f"--signals-root {root!r} has no {needed}/ package — point it at "
                     f"<repo>/services/signals (or the reference/signals snapshot)")
    if root not in sys.path:
        sys.path.insert(0, root)


def _graph_settings(graph_settings_cls, discovery_port: int):
    s = graph_settings_cls()
    s.storage_backend = "mock"
    s.device_backend = "mock"
    s.discovery_host = "127.0.0.1"
    s.discovery_port = discovery_port
    return s


def _sidecar_path(path: str) -> str:
    """``graph.json`` → ``graph.mock.json`` (same directory)."""
    stem, _ext = os.path.splitext(path)
    return stem + ".mock.json"


def _raw_extras(path: str) -> tuple[list[str], dict[str, str], dict[str, list], dict]:
    """The hook keys straight from the JSON (signal_graph's model drops them).

    ``device_kinds`` / ``mock_scripts`` may also live in a ``<graph>.mock.json``
    sidecar next to the graph, so the deployable graph.json stays free of
    local-run data. Sidecar entries win over in-file ones.
    """
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    side = _sidecar_path(path)
    if os.path.exists(side):
        with open(side, "r", encoding="utf-8") as fh:
            extra = json.load(fh)
        for key in ("device_kinds", "mock_scripts"):
            merged = dict(raw.get(key) or {})
            merged.update(extra.get(key) or {})
            raw[key] = merged
        print(f"  mock sidecar: {side}", flush=True)
    modules = [m for m in raw.get("block_modules", []) if isinstance(m, str)]
    kinds = {k: v for k, v in (raw.get("device_kinds") or {}).items() if isinstance(v, str)}
    scripts = {k: v for k, v in (raw.get("mock_scripts") or {}).items() if isinstance(v, list)}
    return modules, kinds, scripts, raw


def _infer_device_kinds(raw: dict, modules: list[str], explicit: dict[str, str]) -> dict[str, str]:
    """Devices used only by blocks from an imported block package get that package's kind.

    A block from ``uds_blocks.blocks`` whose param value names a
    ``device_services`` key means that device speaks the package's port, so
    the built-in MockDeviceAdapter (no ``subscribe``) would crash it. The kind
    is ``<pkg>.<param name>`` when the package registers it, else the
    package's first kind. Explicit ``device_kinds`` entries always win.
    """
    from signal_graph.core.domain.blocks import _REGISTRY

    packages = {m.split(".", 1)[0] for m in modules}
    devices = set((raw.get("device_services") or {}).keys())
    inferred: dict[str, str] = {}
    for block in raw.get("blocks", []):
        factory = _REGISTRY.get(block.get("type"))
        cls = getattr(factory, "__self__", None)
        pkg = (getattr(cls, "__module__", "") or "").split(".", 1)[0]
        if pkg not in packages:
            continue
        try:
            known = list(getattr(importlib.import_module(f"{pkg}.adapters.registry"), "KINDS", {}))
        except ImportError:
            continue
        if not known:
            continue
        for pname, pval in (block.get("params") or {}).items():
            if isinstance(pval, str) and pval in devices and pval not in explicit:
                kind = f"{pkg}.{pname}"
                inferred.setdefault(pval, kind if kind in known else known[0])
    return inferred


def _mock_adapter_for(kind: str, service_name: str, script: list | None):
    """``<pkg>.adapters.registry.MOCK_ADAPTER(service_name)`` for a kind ``<pkg>.<param>``."""
    pkg = kind.split(".", 1)[0]
    registry = importlib.import_module(f"{pkg}.adapters.registry")
    known = getattr(registry, "KINDS", {})
    if kind not in known:
        sys.exit(f"device kind {kind!r} is not in {pkg}.adapters.registry.KINDS ({sorted(known)})")
    mock_cls = getattr(registry, "MOCK_ADAPTER", None)
    if mock_cls is None:
        sys.exit(f"{pkg}.adapters.registry has no MOCK_ADAPTER — add `MOCK_ADAPTER = Mock...Adapter`")
    if script:
        # graph.json rows are lists; the scaffolded mock expects (key, values, status) tuples
        return mock_cls(service_name, script=[tuple(row) for row in script])
    return mock_cls(service_name)


def _real_adapter_for(kind: str, registry, service_name: str):
    """``<pkg>.adapters.registry.KINDS[kind](registry, service_name, None)``: the package's real adapter."""
    pkg = kind.split(".", 1)[0]
    kinds = getattr(importlib.import_module(f"{pkg}.adapters.registry"), "KINDS", {})
    if kind not in kinds:
        sys.exit(f"device kind {kind!r} is not in {pkg}.adapters.registry.KINDS ({sorted(kinds)})")
    return kinds[kind](registry, service_name, None)


def _make_app_class(graph_app_cls, device_kinds: dict[str, str], mock_scripts: dict[str, list],
                    real_kinds: set[str] | None = None):
    """GraphApp subclass that swaps in kind-specific adapters (hook #2, runner-side):
    the package's mock, or in bench mode its real adapter for the devices listed."""
    real_kinds = real_kinds or set()

    class StudioGraphApp(graph_app_cls):
        def _build_device_adapters(self):
            adapters = super()._build_device_adapters()
            for logical, kind in device_kinds.items():
                service_name = self._config.device_services.get(logical, logical)
                if logical in real_kinds:
                    adapters[logical] = _real_adapter_for(kind, self._registry, service_name)
                    print(f"  device {logical!r} -> REAL adapter for kind {kind!r} "
                          f"(service {service_name!r} via the registry)", flush=True)
                    continue
                script = mock_scripts.get(logical)
                adapters[logical] = _mock_adapter_for(kind, service_name, script)
                print(f"  device {logical!r} -> mock adapter for kind {kind!r}"
                      f"{f' (script: {len(script)} rows)' if script else ''}", flush=True)
            return adapters

    return StudioGraphApp


async def main(config_paths: list[str], discovery_port: int,
               exit_on_stdin_close: bool = False) -> None:
    from common.registry import InMemoryServiceRegistry
    from signal_discovery.app import DiscoveryApp
    from signal_discovery.config import Settings as DiscoverySettings
    from signal_graph.app import GraphApp
    from signal_graph.config import Settings as GraphSettings
    from signal_graph.core.domain.graph_config import GraphConfig

    # Bench mode is a property of the cluster: the first enabled sidecar wins.
    bench = next((b for b in (_bench_extras(p) for p in config_paths) if b), None)
    real_kinds: set[str] = set(bench.get("real_kinds") or []) if bench else set()

    if bench and (bench.get("registry") or {}).get("backend", "consul") == "consul":
        reg = bench.get("registry") or {}
        registry = StdlibConsulRegistry(reg.get("host", "127.0.0.1"), int(reg.get("port", 8500)))
        print(f"bench mode: registry consul {reg.get('host', '127.0.0.1')}:{reg.get('port', 8500)}"
              f"{', real adapters for ' + ', '.join(sorted(real_kinds)) if real_kinds else ''}", flush=True)
    else:
        registry = InMemoryServiceRegistry()

    discovery = None
    existing = await registry.resolve("signal-discovery") if bench else None
    if existing is not None:
        disc_host, disc_port = existing.host, existing.port
        print(f"signal-discovery already on the bench at {disc_host}:{disc_port}; using it "
              f"(it lists this graph on its next refresh)", flush=True)
    else:
        disc_settings = DiscoverySettings()
        disc_settings.grpc_port = discovery_port
        disc_settings.routing_refresh_interval = 2.0
        discovery = DiscoveryApp(disc_settings, registry)
        await discovery.start()
        disc_host, disc_port = "127.0.0.1", discovery.port
        print(f"signal-discovery listening on {disc_host}:{disc_port}", flush=True)

    apps = []
    for path in config_paths:
        modules, kinds, scripts, raw = _raw_extras(path)
        for mod in modules:                      # hook #1 (runner-side)
            importlib.import_module(mod)
            print(f"  imported block module {mod}", flush=True)
        for logical, kind in _infer_device_kinds(raw, modules, kinds).items():
            kinds[logical] = kind
            print(f"  device {logical!r}: kind {kind!r} inferred from its blocks "
                  f"(add \"device_kinds\" to override)", flush=True)
        unknown = real_kinds - set(kinds)
        if unknown:
            sys.exit(f"real_kinds names devices without a kind: {sorted(unknown)} "
                     f"(known: {sorted(kinds)})")
        config = GraphConfig.load(path)
        app_cls = _make_app_class(GraphApp, kinds, scripts, real_kinds) if kinds else GraphApp
        settings = _graph_settings(GraphSettings, disc_port)
        settings.discovery_host = disc_host
        app = app_cls(config, settings, registry)
        await app.start()
        apps.append(app)
        names = ", ".join(o.name for o in config.observe)
        print(f"{config.service.name} listening on 127.0.0.1:{app.port}  "
              f"[{names}]", flush=True)

    await asyncio.sleep(1.0)
    if discovery is not None:
        await discovery.catalog.refresh()
    print("READY", flush=True)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig_name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, sig_name, None)
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            signal.signal(sig, lambda *_: stop.set())

    # Opt-in: stop when the parent closes our stdin (Electron child lifecycle).
    if exit_on_stdin_close:
        async def watch_stdin() -> None:
            try:
                await loop.run_in_executor(None, sys.stdin.read)
            except Exception:  # noqa: BLE001
                pass
            stop.set()
        asyncio.create_task(watch_stdin())

    try:
        await stop.wait()
    finally:
        for app in reversed(apps):
            await app.stop()
        if discovery is not None:
            await discovery.stop()
        close = getattr(registry, "close", None)
        if close is not None:
            await close()
        print("cluster stopped", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--signals-root", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "reference", "signals"),
                        help="directory containing signal_graph/, signal_discovery/, common/")
    parser.add_argument("--all", action="store_true", help="run the three shipped configs under <root>/signal_graph/configs")
    parser.add_argument("--config", action="append", default=[], help="graph.json path (repeatable)")
    parser.add_argument("--discovery-port", type=int, default=50210)
    parser.add_argument("--exit-on-stdin-close", action="store_true",
                        help="stop when stdin reaches EOF (used by Graph Studio)")
    args = parser.parse_args()
    root = os.path.abspath(args.signals_root)
    _prepare_sys_path(root)
    configs_dir = os.path.join(root, "signal_graph", "configs")
    paths = [os.path.join(configs_dir, n, "graph.json") for n in SHIPPED] if args.all else []
    paths += [os.path.abspath(p) for p in args.config]
    if not paths:
        parser.error("give --all and/or --config <graph.json>")
    print(f"signals root: {root}", flush=True)
    try:
        asyncio.run(main(paths, args.discovery_port, args.exit_on_stdin_close))
    except KeyboardInterrupt:
        pass
