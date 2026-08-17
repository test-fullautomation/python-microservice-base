#!/usr/bin/env python3
"""Generate microservice scaffolds via the bridge's HTTP API.

Does the same job as the Service Creator wizard in the Manager GUI, but from
a terminal — so you can script it, commit reproducible specs, or run from CI.

Two ways to supply input:

1. **Config file** (YAML or JSON) with any subset of the
   ``/api/scaffold/generate-v2`` fields::

       python -m MicroserviceBase.tools.scaffold_cli --config my_service.yaml

2. **Inline flags** for the common cases::

       python -m MicroserviceBase.tools.scaffold_cli \\
           --name Hello --language python --output ./out

Config + flags compose: flags override fields loaded from the config.

Importing an existing .proto is supported via ``--proto path/to/file.proto``.
Pass ``--monorepo`` to emit one project folder with N executables (one per
service declared in the .proto).

Requires the bridge to be running (default ``http://127.0.0.1:1112``; set via
``--bridge-url`` or the ``MB_BRIDGE_URL`` env var).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_BRIDGE = "http://127.0.0.1:1112"


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _post_json(url: str, payload: Dict[str, Any], timeout: int = 60) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"Failed to reach bridge at {url}: {exc}\n"
            f"Is the bridge running?  Start the Manager GUI or launch the bridge "
            f"directly (python -m MicroserviceBase.adapters.ui_bridge.fastapi_bridge).")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Bridge returned non-JSON response: {exc}")


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def _load_config(path: str) -> Dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise SystemExit(f"Config not found: {p}")
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError:
            raise SystemExit(
                "YAML configs require PyYAML.  `pip install pyyaml` or use a .json file.")
        return yaml.safe_load(text) or {}
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in {p}: {exc}")


# ---------------------------------------------------------------------------
# Payload assembly
# ---------------------------------------------------------------------------

def _defaults() -> Dict[str, Any]:
    return {
        "service_name": "",
        "version": "1.0.0",
        "description": "",
        "short_desc": "",
        "group": "",
        "tag": "",
        "language": "python",
        "gui_type": "none",
        "client_grpc_kind": "google",
        "server_grpc_kind": "msys2",
        "gen_nomad": True,
        "gen_build_scripts": True,
        "gen_readme": True,
        "gen_stubs": True,
        "vcpkg_root": "",
        "protoc_path": "",
        "grpc_plugin_path": "",
        "nomad_dc": "dc1",
        "nomad_driver": "raw_exec",
        "nomad_command": "",
        "nomad_cpu": 100,
        "nomad_mem": 128,
        "nomad_consul_addr": "http://127.0.0.1:8500",
        "methods": [],
        "output_path": "",
        "proto_content_override": "",
        "monorepo": False,
        "services": [],
        "proto_package": "",
    }


def _mapped_method(m: Dict[str, Any]) -> Dict[str, Any]:
    """Normalise a method dict from either a config file or parse-proto output."""
    return {
        "name": m.get("name", ""),
        "params": [
            {"name": p.get("name", ""),
             "type": p.get("type", "string"),
             "required": p.get("required", True),
             "description": p.get("description", "")}
            for p in m.get("params", [])
        ],
        "return_type": m.get("return_type", "string"),
        "description": m.get("description", ""),
        "server_streaming": bool(m.get("server_streaming", False)),
        "input_type": m.get("input_type", ""),
        "output_type": m.get("output_type", ""),
    }


def _parse_proto(bridge_url: str, content: str) -> Dict[str, Any]:
    r = _post_json(f"{bridge_url}/api/scaffold/parse-proto",
                   {"proto_content": content})
    if r.get("status") != "ok":
        raise SystemExit(f"parse-proto failed: {r.get('error', 'unknown error')}")
    return r


def _build_payload(args: argparse.Namespace,
                   cfg: Dict[str, Any]) -> Dict[str, Any]:
    payload = _defaults()
    payload.update(cfg)  # config-file values win over defaults

    # Inline flag overrides
    overrides = {
        "service_name":     args.name,
        "language":         args.language,
        "gui_type":         args.gui,
        "client_grpc_kind": args.client_grpc,
        "server_grpc_kind": args.server_grpc,
        "output_path":      args.output,
        "version":          args.version,
        "description":      args.description,
    }
    for k, v in overrides.items():
        if v is not None:
            payload[k] = v
    if args.monorepo:
        payload["monorepo"] = True
    if args.no_nomad:
        payload["gen_nomad"] = False
    if args.no_build_scripts:
        payload["gen_build_scripts"] = False
    if args.no_stubs:
        payload["gen_stubs"] = False

    # Normalise method lists (config file may have passed raw ones)
    payload["methods"] = [_mapped_method(m) for m in payload.get("methods", [])]
    payload["services"] = [
        {"name": s.get("name", ""),
         "methods": [_mapped_method(m) for m in s.get("methods", [])]}
        for s in payload.get("services", [])
    ]

    # Optional .proto import — overrides methods/services with parsed content.
    if args.proto:
        proto_text = Path(args.proto).read_text(encoding="utf-8")
        parsed = _parse_proto(args.bridge_url, proto_text)
        payload["proto_content_override"] = proto_text
        payload["proto_package"] = parsed.get("proto_package", payload.get("proto_package", ""))

        svcs: List[Dict[str, Any]] = parsed.get("services", []) or []
        if not svcs:
            raise SystemExit("The .proto contains no service declarations.")

        if payload["monorepo"]:
            payload["services"] = [
                {"name": s["name"],
                 "methods": [_mapped_method(m) for m in s.get("methods", [])]}
                for s in svcs
            ]
            # Bridge validates top-level methods even for monorepos.
            payload["methods"] = payload["services"][0]["methods"] if payload["services"] else []
        else:
            pick = None
            if args.proto_service:
                pick = next((s for s in svcs if s["name"] == args.proto_service), None)
                if pick is None:
                    names = ", ".join(s["name"] for s in svcs) or "(none)"
                    raise SystemExit(
                        f"Service '{args.proto_service}' not found in proto. "
                        f"Available: {names}")
            else:
                pick = svcs[0]
            payload["service_name"] = payload["service_name"] or pick["name"]
            payload["methods"] = [_mapped_method(m) for m in pick.get("methods", [])]

    # Final validation
    if not payload["service_name"]:
        raise SystemExit("service_name is required (use --name or set it in the config).")
    if not payload["output_path"]:
        raise SystemExit("output_path is required (use --output or set it in the config).")

    return payload


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="mb-scaffold",
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  mb-scaffold -c spec.yaml\n"
            "  mb-scaffold --name Hello --language python --output ./out\n"
            "  mb-scaffold --name Device --proto device.proto --monorepo --output ./out\n"))
    ap.add_argument("-c", "--config",
                    help="YAML or JSON spec file")
    ap.add_argument("-n", "--name",
                    help="service_name (required unless set in config)")
    ap.add_argument("-l", "--language", choices=("python", "cpp"),
                    help="Target language")
    ap.add_argument("--gui", choices=("none", "html", "qml", "wasm", "widget"),
                    help="GUI variant")
    ap.add_argument("--client-grpc", dest="client_grpc",
                    choices=("google", "qt", "google_vcpkg"),
                    help="Which gRPC stack the GUI client uses:\n"
                         "  google         - Google grpc++ via MSYS2 prebuilt (default)\n"
                         "  qt             - Qt6::Grpc + Qt6::Protobuf, qt_client/ project\n"
                         "  google_vcpkg   - Google grpc++ via vcpkg + Qt MinGW, "
                         "qt_client_grpcpp/ project")
    ap.add_argument("--server-grpc", dest="server_grpc",
                    choices=("msys2", "vcpkg"),
                    help="Toolchain the server is built with:\n"
                         "  msys2  - Google grpc++ from MSYS2 prebuilt (default)\n"
                         "  vcpkg  - Google grpc++ via vcpkg + Qt MinGW; emits "
                         "build_qt_vcpkg.bat + shared triplets/ + ports/ overlay. "
                         "Independent of --client-grpc; pick 'vcpkg' for both sides "
                         "to share the vcpkg cache.")
    ap.add_argument("-o", "--output",
                    help="Output folder (the service dir is created inside this)")
    ap.add_argument("--version", help="Service version string (default 1.0.0)")
    ap.add_argument("--description")
    ap.add_argument("--proto", help="Path to an existing .proto to import")
    ap.add_argument("--proto-service",
                    help="Pick one service from the .proto (default: first)")
    ap.add_argument("--monorepo", action="store_true",
                    help="Emit one project with N executables (requires --proto)")
    ap.add_argument("--no-nomad",         action="store_true", help="Skip Nomad HCL")
    ap.add_argument("--no-build-scripts", action="store_true", help="Skip build_deploy*.bat/sh")
    ap.add_argument("--no-stubs",         action="store_true", help="Skip pre-generating proto stubs")
    ap.add_argument("--bridge-url",
                    default=os.environ.get("MB_BRIDGE_URL", DEFAULT_BRIDGE),
                    help=f"Bridge base URL (default: $MB_BRIDGE_URL or {DEFAULT_BRIDGE})")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the JSON payload and exit without calling the bridge")
    ap.add_argument("-q", "--quiet", action="store_true",
                    help="Print only the target path on success")
    args = ap.parse_args(argv)

    cfg = _load_config(args.config) if args.config else {}
    payload = _build_payload(args, cfg)

    if args.dry_run:
        print(json.dumps(payload, indent=2))
        return 0

    r = _post_json(f"{args.bridge_url}/api/scaffold/generate-v2", payload)
    if r.get("status") != "ok":
        print(f"ERROR: {r.get('error', 'unknown error')}", file=sys.stderr)
        return 1

    if args.quiet:
        print(r.get("path", ""))
    else:
        print(f"OK — {r.get('file_count', '?')} files written to {r.get('path')}")
        if r.get("files"):
            # Show just the tree top-level for brevity
            tops = sorted({Path(f).parts[0] for f in r["files"] if f})
            print("    contents:", " ".join(tops))
    return 0


if __name__ == "__main__":
    sys.exit(main())
