"""Persistent in-process signal cluster for Graph Studio's Run/Monitor features.

Keeps ``signal-discovery`` + one or more ``signal_graph`` services running on
FIXED ports until stopped (Ctrl-C / SIGTERM / stdin closed), so Graph Studio
can monitor them over gRPC. Everything is mocked (device + measurement store):
no Consul, no DB. Graph ports come from each graph.json ``service.grpc_port``.

    python run_cluster.py --signals-root <repo>/services/signals --all
    python run_cluster.py --signals-root <repo>/services/signals --config path/to/graph.json

``--signals-root`` is the directory that contains the ``signal_graph``,
``signal_discovery`` and ``common`` packages (the repo's ``services/signals``
since PR #253 landed, or the tool's ``reference/signals`` snapshot).

Runner-side hooks — the two extension points the UDS block stories need but
signal_graph does not have yet (see the extraction explainer §4). They are
applied HERE, for local mocked runs only, so a graph with extra block
packages can be started before the hook PR is merged:

* ``"block_modules": ["uds_blocks.blocks"]`` in graph.json → imported before
  the graph is built (registers the block types and the adapter kinds).
* ``"device_kinds": {"uds_gw": "uds_blocks.gateway"}`` in graph.json → that
  logical device gets the kind's MOCK adapter (``<pkg>.adapters.registry.
  MOCK_ADAPTER``) instead of the built-in mock device adapter.
* ``"mock_scripts": {"uds_gw": [["periodic:52", {"BatteryVoltage": 12500}, 0]]}``
  (optional, local runs only) → handed to that mock adapter as ``script=``
  so the graph shows moving values instead of None.

``device_kinds`` is inferred when absent: a device referenced by a block
from an imported package gets that package's kind. ``device_kinds`` and
``mock_scripts`` may also live in a ``<graph>.mock.json`` sidecar next to
the graph so the deployable graph.json stays clean.

All three keys are ignored by signal_graph's own loader (pydantic drops
unknown keys) and preserved by Graph Studio's lossless round-trip.
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

SHIPPED = ["signal-in", "signal-out", "signal-proc-foo-bar"]


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


def _make_app_class(graph_app_cls, device_kinds: dict[str, str], mock_scripts: dict[str, list]):
    """GraphApp subclass that swaps in kind-specific mock adapters (hook #2, runner-side)."""

    class StudioGraphApp(graph_app_cls):
        def _build_device_adapters(self):
            adapters = super()._build_device_adapters()
            for logical, kind in device_kinds.items():
                service_name = self._config.device_services.get(logical, logical)
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

    registry = InMemoryServiceRegistry()

    disc_settings = DiscoverySettings()
    disc_settings.grpc_port = discovery_port
    disc_settings.routing_refresh_interval = 2.0
    discovery = DiscoveryApp(disc_settings, registry)
    await discovery.start()
    print(f"signal-discovery listening on 127.0.0.1:{discovery.port}", flush=True)

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
        config = GraphConfig.load(path)
        app_cls = _make_app_class(GraphApp, kinds, scripts) if kinds else GraphApp
        app = app_cls(config, _graph_settings(GraphSettings, discovery.port), registry)
        await app.start()
        apps.append(app)
        names = ", ".join(o.name for o in config.observe)
        print(f"{config.service.name} listening on 127.0.0.1:{app.port}  "
              f"[{names}]", flush=True)

    await asyncio.sleep(1.0)
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
        await discovery.stop()
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
