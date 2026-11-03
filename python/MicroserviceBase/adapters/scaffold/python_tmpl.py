"""Python service scaffold templates.

Generates the full project structure for a Python gRPC microservice
using the MicroserviceBase async runtime (ServiceRunner + Consul).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict

from ._template_loader import load_template
from .shared import python_file_header

if TYPE_CHECKING:
    from .generator import ScaffoldSpec


def generate(spec: "ScaffoldSpec") -> Dict[str, str]:
    """
Render every file for a Python single-service gRPC scaffold.

Produces ``main.py``, ``config.py`` (Pydantic ``BaseServiceSettings``
subclass), ``context.py`` (composition root), ``pyproject.toml``,
domain stubs, gRPC adapter, proto-stub generator script, and
optionally HTML/JS GUI files when ``spec.gui_type == "html"``.

For multi-service / monorepo layouts use :func:`generate_monorepo`.

**Arguments:**

* ``spec``

  / *Condition*: required / *Type*: ScaffoldSpec /

  Scaffold specification.

**Returns:**

* ``files``

  / *Type*: Dict[str, str] /

  Map of relative-path → file-contents for every file the scaffold
  should write.
    """
    files: Dict[str, str] = {}

    sn = spec.snake_name
    prefix = spec.env_prefix
    svc = spec.service_name

    # ---- composition root -------------------------------------------
    files["main.py"] = _main_py(spec)
    files["config.py"] = _config_py(spec)
    files["context.py"] = _context_py(spec)
    files["pyproject.toml"] = _pyproject(spec)
    files["BUILD.bazel"] = _build_bazel(spec)

    # ---- core/ — pure: domain + the ports it declares ----------------
    files["core/__init__.py"] = ""
    files["core/domain/__init__.py"] = ""
    files[f"core/domain/{sn}_service.py"] = _domain_service(spec)
    files["core/ports/__init__.py"] = ""
    files["core/ports/inbound/__init__.py"] = ""
    files[f"core/ports/inbound/{sn}_port.py"] = _port_inbound(spec)
    files["core/ports/outbound/__init__.py"] = ""
    files[f"core/ports/outbound/{sn}_backend_port.py"] = _port_outbound(spec)

    # ---- adapters/ — infrastructure, split by direction --------------
    files["adapters/__init__.py"] = ""
    files["adapters/inbound/__init__.py"] = ""
    files["adapters/inbound/api/__init__.py"] = ""
    files["adapters/inbound/api/grpc_adapter.py"] = _grpc_adapter(spec)
    files["adapters/outbound/__init__.py"] = ""

    # ---- generated/ — checked-in proto stubs -------------------------
    files["generated/__init__.py"] = ""
    files["proto/__init__.py"] = ""
    files["scripts/generate_protos.py"] = _gen_protos_script(spec)

    # ---- tests/ — unit + executable architecture rules ---------------
    files["tests/__init__.py"] = ""
    files["tests/pytest.ini"] = _tests_pytest_ini(spec)
    files["tests/pytest_wrapper.py"] = _tests_pytest_wrapper(spec)
    files["tests/BUILD.bazel"] = _tests_build_bazel(spec)
    files["tests/unit/__init__.py"] = ""
    files[f"tests/unit/test_{sn}_service.py"] = _tests_unit_service(spec)
    files["tests/architecture/__init__.py"] = ""
    files["tests/architecture/test_core_purity.py"] = _tests_core_purity(spec)

    if spec.gui_type == "html":
        files[f"GUIs/{svc}.html"] = _gui_html(spec)
        files[f"GUIs/{svc}.js"] = _gui_js(spec)

    return files


# -----------------------------------------------------------------------
# main.py
# -----------------------------------------------------------------------

def _main_py(spec: "ScaffoldSpec") -> str:
    sn = spec.snake_name
    svc = spec.service_name
    header = python_file_header(
        "main.py",
        f"Entry point for the {svc} service.\n"
        f"Composes the dependency-injection context and hands it off to\n"
        f"ServiceRunner, which manages the gRPC server lifecycle and\n"
        f"Consul registration.",
    )
    return load_template(
        "python/service/main.py.tmpl",
        header=header, sn=sn, svc=svc,
    )


# -----------------------------------------------------------------------
# config.py
# -----------------------------------------------------------------------

def _config_py(spec: "ScaffoldSpec") -> str:
    sn = spec.snake_name
    prefix = spec.env_prefix
    header = python_file_header(
        "config.py",
        f"Pydantic settings for the {spec.service_name} service.\n"
        f"All fields are loaded from environment variables prefixed with\n"
        f"`{prefix}` (e.g. {prefix}GRPC_PORT, {prefix}CONSUL_ADDR).",
    )
    return load_template(
        "python/service/config.py.tmpl",
        header=header, sn=sn, prefix=prefix, service_name=spec.service_name,
    )


# -----------------------------------------------------------------------
# context.py
# -----------------------------------------------------------------------

def _context_py(spec: "ScaffoldSpec") -> str:
    sn = spec.snake_name
    svc = spec.service_name
    cls = f"{svc}Service"
    header = python_file_header(
        "context.py",
        f"Dependency-injection composition root for the {svc} service.\n"
        f"Wires Settings, the domain class, and the gRPC adapter together.\n"
        f"main.py calls create_context() once at startup.",
    )
    return load_template(
        "python/service/context.py.tmpl",
        header=header, sn=sn, svc=svc, cls=cls,
    )


# -----------------------------------------------------------------------
# domain/<snake>_service.py
# -----------------------------------------------------------------------

def _domain_service(spec: "ScaffoldSpec") -> str:
    svc = spec.service_name
    cls = f"{svc}Service"

    def _arg_block(p) -> str:
        return (
            f"\n* ``{p.name}``\n"
            f"\n  / *Condition*: required / *Type*: str /\n"
            f"\n  TODO: describe ``{p.name}``.\n"
        )

    methods = ""
    for m in spec.methods:
        params = ", ".join(f"{p.name}: str" for p in m.params)
        if params:
            params = ", " + params

        arg_section = ""
        if m.params:
            arg_section = "\n**Arguments:**\n" + "".join(_arg_block(p) for p in m.params)

        tmpl = ("python/service/domain_method_streaming.py.tmpl"
                if m.server_streaming
                else "python/service/domain_method_unary.py.tmpl")
        methods += load_template(
            tmpl,
            snake_method=_snake(m.name),
            method=m.name,
            params=params,
            arg_section=arg_section,
        )

    header = python_file_header(
        f"{_snake(svc)}_service.py",
        f"Pure business logic for the {svc} service.\n"
        f"This module owns the domain model and contains zero I/O — no\n"
        f"gRPC, no Consul, no Nomad, no HTTP.  All inbound traffic enters\n"
        f"through the gRPC adapter (adapters/api/grpc_adapter.py) and is\n"
        f"translated into method calls on this class.",
    )

    return load_template(
        "python/service/domain_service.py.tmpl",
        header=header, svc=svc, cls=cls,
        methods=methods if methods else "    pass",
    )


# -----------------------------------------------------------------------
# adapters/api/grpc_adapter.py
# -----------------------------------------------------------------------

def _grpc_adapter(spec: "ScaffoldSpec") -> str:
    sn = spec.snake_name
    svc = spec.service_name
    cls = f"{svc}Service"

    # Stubs live in generated/ and the domain under core/ -- see the
    # nested-hexagonal layout emitted by generate().
    imports = (
        f"from generated import {sn}_pb2, {sn}_pb2_grpc  "
        f"# type: ignore[import-not-found]\n"
        f"from core.domain.{sn}_service import {cls}\n"
    )

    methods = ""
    for m in spec.methods:
        param_reads = "\n".join(
            f"        _{p.name} = request.{p.name}"
            for p in m.params
        )
        args = ", ".join(f"_{p.name}" for p in m.params)

        request_doc = f"Proto message ``{m.name}Request``."
        if m.params:
            request_doc += "  Fields: " + ", ".join(f"``{p.name}``" for p in m.params) + "."

        tmpl = ("python/service/adapter_method_streaming.py.tmpl"
                if m.server_streaming
                else "python/service/adapter_method_unary.py.tmpl")
        methods += load_template(
            tmpl,
            method=m.name,
            snake_method=_snake(m.name),
            request_doc=request_doc,
            param_reads=param_reads or "        pass",
            args=args,
            sn=sn,
        )

    header = python_file_header(
        "grpc_adapter.py",
        f"gRPC inbound adapter for {cls}.\n"
        f"Translates protobuf request/response messages into method calls\n"
        f"on the domain service.  One method per RPC.  Do not change the\n"
        f"signatures (they are required by the proto-generated servicer\n"
        f"base class); edit only the body to plug in real logic.",
    )

    return load_template(
        "python/service/grpc_adapter.py.tmpl",
        header=header, sn=sn, svc=svc, cls=cls,
        imports=imports, methods=methods,
    )


# -----------------------------------------------------------------------
# scripts/generate_protos.py
# -----------------------------------------------------------------------

def _gen_protos_script(spec: "ScaffoldSpec", stub_dir: str = "generated") -> str:
    """Render scripts/generate_protos.py.

    ``stub_dir`` is where protoc's output lands, relative to the service
    root.  The two layouts differ:

    * single service (nested hexagonal) -> ``generated/``, keeping
      authored ``.proto`` sources separate from emitted stubs, which is
      what the Bazel ``generated_lib`` target globs.
    * monorepo -> ``proto/``, alongside the sources.  That layout has not
      been migrated to the nested shape, and moving its stubs alone would
      leave it half-converted.
    """
    sn = spec.snake_name
    header = python_file_header(
        "generate_protos.py",
        f"Helper script that runs `protoc` on {sn}.proto and patches the\n"
        f"generated `_pb2_grpc.py` to use a package-relative import.\n"
        f"Run from the service root:  python scripts/generate_protos.py",
    )
    return load_template(
        "python/service/generate_protos.py.tmpl",
        header=header, sn=sn, sn_dunder=sn.replace("_", "__"),
        stub_dir=stub_dir,
    )


# -----------------------------------------------------------------------
# pyproject.toml
# -----------------------------------------------------------------------

def _pyproject(spec: "ScaffoldSpec") -> str:
    sn = spec.snake_name
    description = spec.description or (spec.service_name + ' microservice')
    return load_template(
        "python/service/pyproject.toml.tmpl",
        sn=sn, version=spec.version, description=description,
    )


# -----------------------------------------------------------------------
# HTML/JS GUI
# -----------------------------------------------------------------------

def _gui_html(spec: "ScaffoldSpec") -> str:
    return load_template("python/service/gui.html.tmpl", svc=spec.service_name)


def _gui_js(spec: "ScaffoldSpec") -> str:
    return load_template("python/service/gui.js.tmpl", svc=spec.service_name)


# =======================================================================
# Monorepo: one project, N services sharing one .proto
# =======================================================================

# -----------------------------------------------------------------------
# BUILD.bazel
# -----------------------------------------------------------------------

def _build_bazel(spec: "ScaffoldSpec") -> str:
    return load_template(
        "python/service/BUILD.bazel.tmpl",
        svc=spec.service_name, sn=spec.snake_name,
    )


# -----------------------------------------------------------------------
# core/ports/inbound/<snake>_port.py
# -----------------------------------------------------------------------

def _port_inbound(spec: "ScaffoldSpec") -> str:
    svc = spec.service_name
    sn = spec.snake_name
    cls = f"{svc}Service"

    # One Protocol method per RPC, mirroring the domain signatures so the
    # domain satisfies the Protocol without an explicit `implements`.
    body = ""
    for m in spec.methods:
        params = ", ".join(f"{p.name}: str" for p in m.params)
        if params:
            params = ", " + params
        ret = "AsyncIterator[str]" if m.server_streaming else "str"
        body += (
            f"    def {_snake(m.name)}(self{params}) -> {ret}:\n"
            f'        """TODO: describe {m.name}."""\n'
            f"        ...\n\n"
        )
    if not body:
        body = "    ...\n"

    header = python_file_header(
        f"{sn}_port.py",
        f"Inbound port for the {svc} service.\n"
        f"Declares the operations the domain offers to driving adapters,\n"
        f"so the gRPC servicer depends on this Protocol rather than on the\n"
        f"concrete domain class.",
    )
    return load_template(
        "python/service/port_inbound.py.tmpl",
        header=header, svc=svc, sn=sn, cls=cls,
        port_methods=body.rstrip("\n"),
    )


# -----------------------------------------------------------------------
# core/ports/outbound/<snake>_backend_port.py
# -----------------------------------------------------------------------

def _port_outbound(spec: "ScaffoldSpec") -> str:
    svc = spec.service_name
    header = python_file_header(
        f"{spec.snake_name}_backend_port.py",
        f"Outbound port for the {svc} service.\n"
        f"Declares what the domain needs from its environment.  A driven\n"
        f"adapter under adapters/outbound/ implements it, so swapping real\n"
        f"hardware for a mock is a composition-root change only.",
    )
    return load_template(
        "python/service/port_outbound.py.tmpl",
        header=header, svc=svc, cls=f"{svc}Service",
    )


# -----------------------------------------------------------------------
# tests/
# -----------------------------------------------------------------------

def _tests_pytest_ini(spec: "ScaffoldSpec") -> str:
    return load_template(
        "python/service/tests_pytest.ini.tmpl",
        svc=spec.service_name,
    )


def _tests_pytest_wrapper(spec: "ScaffoldSpec") -> str:
    header = python_file_header(
        "pytest_wrapper.py",
        "Bazel entry point for pytest.\n"
        "py_test runs a script rather than a pytest session, so every\n"
        "test target points its `main` here.",
    )
    return load_template(
        "python/service/tests_pytest_wrapper.py.tmpl",
        header=header,
    )


def _tests_build_bazel(spec: "ScaffoldSpec") -> str:
    # Bazel label of the service package. Scaffolds are generated into an
    # arbitrary folder, so we emit a relative-looking placeholder the user
    # retargets when the service is dropped into the monorepo.
    return load_template(
        "python/service/tests_BUILD.bazel.tmpl",
        svc=spec.service_name, sn=spec.snake_name,
        bazel_pkg=f"services/{spec.snake_name}",
    )


def _tests_unit_service(spec: "ScaffoldSpec") -> str:
    svc = spec.service_name
    sn = spec.snake_name
    cls = f"{svc}Service"

    tests = ""
    for m in spec.methods:
        call_args = ", ".join(f'"{p.name}"' for p in m.params)
        sm = _snake(m.name)
        if m.server_streaming:
            tests += (
                f"@pytest.mark.asyncio\n"
                f"async def test_{sm}_yields_results(service: {cls}) -> None:\n"
                f'    """TODO: assert what {m.name} streams."""\n'
                f"    results = [item async for item in service.{sm}({call_args})]\n"
                f"    assert results is not None\n\n\n"
            )
        else:
            tests += (
                f"def test_{sm}_returns_a_result(service: {cls}) -> None:\n"
                f'    """TODO: assert what {m.name} returns."""\n'
                f"    result = service.{sm}({call_args})\n"
                f"    assert result is not None\n\n\n"
            )
    if not tests:
        tests = (
            "# TODO: add a test per domain method once the domain does\n"
            "# something worth asserting.\n"
        )

    header = python_file_header(
        f"test_{sn}_service.py",
        f"Unit tests for the {svc} domain.\n"
        f"Exercises the pure domain directly — no gRPC server, no Consul,\n"
        f"no hardware.",
    )
    return load_template(
        "python/service/tests_unit_service.py.tmpl",
        header=header, svc=svc, sn=sn, cls=cls,
        test_methods=tests.rstrip("\n"),
    )


def _tests_core_purity(spec: "ScaffoldSpec") -> str:
    header = python_file_header(
        "test_core_purity.py",
        "Architecture test: core/ must not import infrastructure.\n"
        "AST-scans every module under core/ and fails on transport or\n"
        "vendor imports, so the hexagonal rule is enforced rather than\n"
        "merely documented.",
    )
    return load_template(
        "python/service/tests_arch_core_purity.py.tmpl",
        header=header,
    )


def generate_monorepo(spec: "ScaffoldSpec", services) -> Dict[str, str]:
    """
Render a Python monorepo scaffold: one project, N services, N
``run_<svc>`` console-script entry points.

Used when the user picks the ``monorepo`` layout in the Service
Creator wizard or sets ``monorepo: true`` in the CLI config.  Each
service gets its own ``main.py``, ``config.py``, ``context.py``,
domain + adapter stubs, and Nomad job spec; ``pyproject.toml`` lists
all entry points so ``pip install .`` produces N CLI commands.

**Arguments:**

* ``spec``

  / *Condition*: required / *Type*: ScaffoldSpec /

  Outer (project-level) scaffold specification.

* ``services``

  / *Condition*: required / *Type*: list /

  List of per-service ``ScaffoldSpec``-like objects.  Each entry's
  ``service_name``, ``methods``, and ``proto_package`` drive its own
  generated files.

**Returns:**

* ``files``

  / *Type*: Dict[str, str] /

  Map of relative-path → file-contents for the entire monorepo tree.
    """
    """Emit a Python monorepo scaffold with one entry-point per service.

    Layout:
        ProjectName/
          pyproject.toml          ← single project, lists each service
          README.md                  as a `[project.scripts]` entry point
          proto/
            <project>.proto        ← shared
            <project>_pb2.py       ← shared generated stubs
            <project>_pb2_grpc.py
          scripts/
            generate_protos.py
          deploy/
            <svc1>.nomad.hcl       ← one job per service
            <svc1>_service_config.json
            <svc2>.nomad.hcl
            ...
          src/
            <project_snake>/       ← Python package
              __init__.py
              <svc1>/              ← per-service module
                __init__.py
                main.py            ← entry point — `python -m <project>.<svc>`
                config.py          ← per-service env vars
                context.py         ← per-service DI
                domain/<svc>.py
                adapters/api/grpc_adapter.py
              <svc2>/
                ...

    All services share one .proto + one set of generated stubs.  Each
    service has its own env-var prefix (``<SVC1>_``), its own Nomad job,
    and its own asyncio entry point.  Mirrors the C++ monorepo layout
    (cpp_tmpl.generate_monorepo) but in Python.
    """
    files: Dict[str, str] = {}
    proj_snake = spec.snake_name        # e.g. "power_device_service"

    # ---- Shared proto (single file with N service blocks) ------------
    if spec.proto_content_override:
        files[f"proto/{proj_snake}.proto"] = spec.proto_content_override
    else:
        files[f"proto/{proj_snake}.proto"] = _mono_gen_proto(spec, services)
    files["proto/__init__.py"] = ""

    # ---- Top-level package files -------------------------------------
    files["pyproject.toml"] = _mono_pyproject(spec, services)
    # Monorepo keeps stubs beside their sources in proto/; only the
    # single-service layout moved them to generated/.
    files["scripts/generate_protos.py"] = _gen_protos_script(spec, stub_dir="proto")
    files[f"src/{proj_snake}/__init__.py"] = ""

    # ---- Per-service module tree -------------------------------------
    for svc in services:
        svc_snake = _snake(svc.name)
        base = f"src/{proj_snake}/{svc_snake}"
        files[f"{base}/__init__.py"] = ""
        files[f"{base}/main.py"]    = _mono_main_py(spec, svc)
        files[f"{base}/config.py"]  = _mono_config_py(spec, svc)
        files[f"{base}/context.py"] = _mono_context_py(spec, svc)
        files[f"{base}/domain/__init__.py"] = ""
        files[f"{base}/domain/{svc_snake}.py"] = _mono_domain_py(spec, svc)
        files[f"{base}/adapters/__init__.py"] = ""
        files[f"{base}/adapters/api/__init__.py"] = ""
        files[f"{base}/adapters/api/grpc_adapter.py"] = _mono_grpc_adapter(spec, svc)

    # ---- Nomad jobs (one per service) --------------------------------
    if spec.gen_nomad:
        for svc in services:
            svc_snake = _snake(svc.name)
            files[f"deploy/{svc_snake}.nomad.hcl"] = _mono_nomad(spec, svc)
            files[f"deploy/{svc_snake}_service_config.json"] = _mono_service_config(spec, svc)

    # ---- README ------------------------------------------------------
    if spec.gen_readme:
        files["README.md"] = _mono_readme(spec, services)

    return files


def _mono_gen_proto(spec, services) -> str:
    """Fallback proto generator for the monorepo (when no override)."""
    pkg = spec.proto_package
    out = ['syntax = "proto3";', '', f'package {pkg};', '']
    for svc in services:
        out.append(f'service {svc.name} {{')
        for m in svc.methods:
            req = f"{m.name}Request"
            resp = f"{m.name}Response"
            stream = "stream " if m.server_streaming else ""
            out.append(f"  rpc {m.name}({req}) returns ({stream}{resp});")
        out.append('}')
        out.append('')
        for m in svc.methods:
            out.append(f'message {m.name}Request {{')
            for i, p in enumerate(m.params, 1):
                ptype = _proto_type(p.type)
                out.append(f'  {ptype} {p.name} = {i};')
            out.append('}')
            out.append(f'message {m.name}Response {{')
            out.append(f'  string result = 1;')
            out.append('}')
            out.append('')
    return '\n'.join(out)


def _proto_type(t: str) -> str:
    """Map our wizard types to proto3 scalar types."""
    return {
        'string': 'string',
        'int32': 'int32', 'int64': 'int64',
        'uint32': 'uint32', 'uint64': 'uint64',
        'bool': 'bool',
        'float': 'float', 'double': 'double',
        'bytes': 'bytes',
    }.get(t, 'string')


def _mono_pyproject(spec, services) -> str:
    """One pyproject.toml that registers each service as an entry point."""
    proj_snake = spec.snake_name
    proj_name_dash = proj_snake.replace('_', '-')
    scripts = []
    for svc in services:
        svc_snake = _snake(svc.name)
        scripts.append(f'{svc_snake.replace("_", "-")} = "{proj_snake}.{svc_snake}.main:run"')
    scripts_block = '\n'.join(scripts)
    description = spec.description or (spec.service_name + ' (monorepo with multiple services)')

    return load_template(
        "python/monorepo/pyproject.toml.tmpl",
        proj_name_dash=proj_name_dash, version=spec.version,
        description=description, scripts_block=scripts_block,
        proj_snake=proj_snake,
    )


def _mono_main_py(spec, svc) -> str:
    """Entry point for one service inside the monorepo."""
    proj_snake = spec.snake_name
    svc_snake = _snake(svc.name)
    header = python_file_header(
        "main.py",
        f"Entry point for {svc.name} (one service in the {spec.service_name}\n"
        f"monorepo).  Reusable shape: each service has its own main.py /\n"
        f"context.py / config.py and runs as `python -m {proj_snake}.{svc_snake}.main`.",
    )
    return load_template(
        "python/monorepo/main.py.tmpl",
        header=header, proj_snake=proj_snake, svc_snake=svc_snake,
        svc_name=svc.name, service_name=spec.service_name,
    )


def _mono_config_py(spec, svc) -> str:
    svc_snake = _snake(svc.name)
    prefix = svc_snake.upper() + "_"
    header = python_file_header(
        "config.py",
        f"Pydantic settings for the {svc.name} sub-service.\n"
        f"Reads env vars prefixed with `{prefix}`.",
    )
    return load_template(
        "python/monorepo/config.py.tmpl",
        header=header, svc_name=svc.name, svc_snake=svc_snake, prefix=prefix,
    )


def _mono_context_py(spec, svc) -> str:
    proj_snake = spec.snake_name
    svc_snake = _snake(svc.name)
    cls = svc.name
    header = python_file_header(
        "context.py",
        f"Dependency-injection composition root for the {svc.name}\n"
        f"sub-service.",
    )
    return load_template(
        "python/monorepo/context.py.tmpl",
        header=header, svc_name=svc.name, svc_snake=svc_snake,
        proj_snake=proj_snake, cls=cls,
    )


def _mono_domain_py(spec, svc) -> str:
    cls = svc.name
    svc_snake = _snake(svc.name)

    methods = ""
    for m in svc.methods:
        params = ", ".join(f"{p.name}: str" for p in m.params)
        if params:
            params = ", " + params

        arg_section = ""
        if m.params:
            arg_section = "\n**Arguments:**\n" + "".join(
                f"\n* ``{p.name}``\n"
                f"\n  / *Condition*: required / *Type*: str /\n"
                f"\n  TODO: describe ``{p.name}``.\n"
                for p in m.params
            )

        tmpl = ("python/monorepo/domain_method_streaming.py.tmpl"
                if m.server_streaming
                else "python/monorepo/domain_method_unary.py.tmpl")
        methods += load_template(
            tmpl,
            snake_method=_snake(m.name),
            method=m.name,
            params=params,
            arg_section=arg_section,
        )

    header = python_file_header(
        f"{svc_snake}.py",
        f"Pure business logic for the {svc.name} sub-service.\n"
        f"Zero I/O — no gRPC, no Consul, no HTTP.  Inbound traffic enters\n"
        f"through the gRPC adapter at adapters/api/grpc_adapter.py.",
    )
    return load_template(
        "python/monorepo/domain.py.tmpl",
        header=header, svc_name=svc.name, cls=cls,
        methods=methods if methods else "    pass",
    )


def _mono_grpc_adapter(spec, svc) -> str:
    proj_snake = spec.snake_name
    svc_snake = _snake(svc.name)
    cls = svc.name

    methods = ""
    for m in svc.methods:
        tmpl = ("python/monorepo/adapter_method_streaming.py.tmpl"
                if m.server_streaming
                else "python/monorepo/adapter_method_unary.py.tmpl")
        methods += load_template(
            tmpl,
            method=m.name,
            snake_method=_snake(m.name),
            proj_snake=proj_snake,
        )

    header = python_file_header(
        "grpc_adapter.py",
        f"gRPC inbound adapter for {svc.name} (one service in the\n"
        f"{spec.service_name} monorepo).",
    )
    return load_template(
        "python/monorepo/grpc_adapter.py.tmpl",
        header=header, svc_name=svc.name, proj_snake=proj_snake,
        svc_snake=svc_snake, cls=cls,
        methods=methods if methods else "    pass",
    )


def _mono_nomad(spec, svc) -> str:
    """Nomad HCL for one service inside the monorepo."""
    svc_snake = _snake(svc.name)
    prefix = svc_snake.upper() + "_"
    return load_template(
        "python/monorepo/nomad.hcl.tmpl",
        svc_name=svc.name, svc_snake=svc_snake, prefix=prefix,
        proj_snake=spec.snake_name, service_name=spec.service_name,
        nomad_dc=spec.nomad_dc, nomad_driver=spec.nomad_driver,
        nomad_consul_addr=spec.nomad_consul_addr,
        nomad_cpu=spec.nomad_cpu, nomad_mem=spec.nomad_mem,
    )


def _mono_service_config(spec, svc) -> str:
    """Per-service service_config.json for the monorepo."""
    import json as _json
    svc_snake = _snake(svc.name)
    return _json.dumps({
        "service_name": svc_snake,
        "version": spec.version,
        "description": svc.name,
        "language": "python",
        "monorepo_project": spec.snake_name,
    }, indent=2) + '\n'


def _mono_readme(spec, services) -> str:
    proj = spec.service_name
    proj_snake = spec.snake_name
    svc_lines = "\n".join(
        f"- **{s.name}** — {len(s.methods)} method(s), env prefix `{_snake(s.name).upper()}_`"
        for s in services
    )
    first_svc_lower = services[0].name.lower() if services else 'service'
    first_svc_snake = _snake(services[0].name) if services else 'svc'
    nomad_run_line = (
        f'nomad job run deploy/{_snake(services[0].name)}.nomad.hcl'
        if services
        else '# nomad job run deploy/<service>.nomad.hcl'
    )
    return load_template(
        "python/monorepo/README.md.tmpl",
        proj=proj, proj_snake=proj_snake,
        n_services=len(services), svc_lines=svc_lines,
        first_svc_lower=first_svc_lower, first_svc_snake=first_svc_snake,
        nomad_run_line=nomad_run_line,
    )


# =======================================================================
# Helpers
# =======================================================================

def _snake(name: str) -> str:
    """CamelCase → snake_case, keeping runs of capitals together.

    ``DoSomething`` → ``do_something``, ``PPSService`` → ``pps_service``,
    ``XMLParser`` → ``xml_parser``.
    """
    import re
    s = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    return s.lower()
