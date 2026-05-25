"""Generate Robot Framework resource files from .proto files.

For each ``service`` declared in any ``.proto`` under a user-supplied
folder, emit a self-contained ``.resource`` file with typed keywords
(one per RPC method) that wrap QConnectBase's ``GrpcClient`` connection.

Test authors then write:

    *** Settings ***
    Resource    com_setup_device_service.resource

    *** Test Cases ***
    Smoke
        Com Setup Device Service Connect    conn=power
        ...    service_name=multi_proto    consul_addr=http://127.0.0.1:8500
        ...    proto_dir=${CURDIR}/../proto
        ${res}=    Com Setup Device Service Set Interface Type    conn=power    type=0
        Should Be Equal As Integers    ${res}[result]    0
        [Teardown]    Com Setup Device Service Disconnect    power

…rather than hand-rolling JSON ``send_cmd`` strings.

Entry points:

* :func:`generate_robot_resources` — programmatic API; returns
  ``{relative_path: file_content}``.
* ``MicroserviceBase.tools.robot_gen`` — CLI wrapper.
* ``POST /api/scaffold/robot`` — FastAPI endpoint used by the GUI.
"""

from __future__ import annotations

import datetime as _dt
import glob
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List

from ._template_loader import load_template


# ---------------------------------------------------------------------------
# Parsed-proto data classes (intentionally lightweight — not the same as
# ScaffoldSpec's; we don't need build / nomad / GUI fields for the Robot path).
# ---------------------------------------------------------------------------

@dataclass
class _RpcParam:
    name: str
    type: str  # proto3 scalar (string / int32 / bool / …)


@dataclass
class _Rpc:
    name: str
    params: List[_RpcParam] = field(default_factory=list)
    return_type: str = "string"
    server_streaming: bool = False


@dataclass
class _Service:
    name: str
    package: str               # e.g. "Com_Setup_Device"
    proto_file: str            # absolute path to the source .proto
    methods: List[_Rpc] = field(default_factory=list)

    @property
    def full_name(self) -> str:
        return f"{self.package}.{self.name}" if self.package else self.name


# ---------------------------------------------------------------------------
# Proto-folder parsing — driven by grpc_tools.protoc via FileDescriptorSet.
# Mirrors the bridge's /api/scaffold/parse-proto logic but works on a whole
# folder at once and returns plain dataclasses instead of dicts.
# ---------------------------------------------------------------------------

# proto3 wire-type → display name (matches what the wizard emits).
_SCALAR = {
    1: "double",   2: "float",     3: "int64",   4: "uint64",
    5: "int32",    6: "fixed64",   7: "fixed32", 8: "bool",
    9: "string",  12: "bytes",    13: "uint32",
    15: "sfixed32", 16: "sfixed64", 17: "sint32", 18: "sint64",
}
_TYPE_MESSAGE = 11
_TYPE_ENUM = 14


class RobotGenError(RuntimeError):
    """Raised when proto parsing or emit fails."""


def parse_proto_folder(proto_dir: str) -> List[_Service]:
    """Walk ``proto_dir`` for ``.proto`` files and return discovered services.

    Each ``.proto`` is compiled via ``grpc_tools.protoc`` into a
    FileDescriptorSet; descriptors carry the service / method / message
    information we need to emit typed keywords.

    Only the top-level proto folder is scanned non-recursively.  Imports
    that reference other ``.proto`` files in the same folder are
    resolved (the folder is passed as a single ``-I`` include path).
    """
    if not os.path.isdir(proto_dir):
        raise RobotGenError(f"proto_dir does not exist or is not a directory: {proto_dir}")

    proto_files = sorted(glob.glob(os.path.join(proto_dir, "*.proto")))
    if not proto_files:
        raise RobotGenError(f"No .proto files found in {proto_dir}")

    try:
        from grpc_tools import protoc as grpc_protoc
        from google.protobuf import descriptor_pb2
    except ImportError as exc:
        raise RobotGenError(
            "grpc_tools / protobuf are required to parse .proto files; "
            "install grpcio-tools."
        ) from exc

    services: List[_Service] = []
    import tempfile

    for proto_path in proto_files:
        with tempfile.TemporaryDirectory() as tmpdir:
            desc_path = os.path.join(tmpdir, "out.pb")
            rc = grpc_protoc.main([
                "grpc_tools.protoc",
                f"--proto_path={proto_dir}",
                f"--descriptor_set_out={desc_path}",
                proto_path,
            ])
            if rc != 0:
                raise RobotGenError(
                    f"protoc rejected {os.path.basename(proto_path)} (exit {rc})"
                )
            with open(desc_path, "rb") as fh:
                fds = descriptor_pb2.FileDescriptorSet()
                fds.ParseFromString(fh.read())

        for file_desc in fds.file:
            # Skip files we didn't ask for (transitive imports get pulled in
            # by --descriptor_set_out unless --include_imports is omitted —
            # but we want only the file we just compiled).
            if not file_desc.name.endswith(os.path.basename(proto_path)):
                continue

            msgs = {m.name: m for m in file_desc.message_type}

            def _extract_fields(msg_short_name: str) -> List[_RpcParam]:
                msg = msgs.get(msg_short_name)
                if msg is None:
                    return []
                out = []
                for fld in msg.field:
                    if fld.type in (_TYPE_MESSAGE, _TYPE_ENUM):
                        # Nested / enum types: fall back to "string" for the
                        # Robot keyword signature.  Caller passes the field
                        # value as JSON; QConnectBase serialises it as-is.
                        t = "string"
                    else:
                        t = _SCALAR.get(fld.type, "string")
                    out.append(_RpcParam(name=fld.name, type=t))
                return out

            def _first_field_type(msg_short_name: str) -> str:
                msg = msgs.get(msg_short_name)
                if not msg or not msg.field:
                    return "string"
                f0 = msg.field[0]
                if f0.type in (_TYPE_MESSAGE, _TYPE_ENUM):
                    return "message" if f0.type == _TYPE_MESSAGE else "enum"
                return _SCALAR.get(f0.type, "string")

            def _strip_pkg(qualified: str) -> str:
                return qualified.rsplit(".", 1)[-1]

            for svc_desc in file_desc.service:
                rpcs: List[_Rpc] = []
                for m in svc_desc.method:
                    input_short = _strip_pkg(m.input_type)
                    output_short = _strip_pkg(m.output_type)
                    rpcs.append(_Rpc(
                        name=m.name,
                        params=_extract_fields(input_short),
                        return_type=_first_field_type(output_short),
                        server_streaming=bool(m.server_streaming),
                    ))
                services.append(_Service(
                    name=svc_desc.name,
                    package=file_desc.package,
                    proto_file=proto_path,
                    methods=rpcs,
                ))

    return services


# ---------------------------------------------------------------------------
# Naming helpers
# ---------------------------------------------------------------------------

_CAMEL_BOUNDARY_1 = re.compile(r"(.)([A-Z][a-z]+)")
_CAMEL_BOUNDARY_2 = re.compile(r"([a-z0-9])([A-Z])")
_MULTI_UNDERSCORE = re.compile(r"_+")


def _snake(name: str) -> str:
    """``SetInterfaceType`` → ``set_interface_type``.

    Handles existing underscores in the source name (e.g.
    ``GetSubDeviceType_ID`` → ``get_sub_device_type_id``) — without the
    collapse step the camel-boundary regex doubles them up
    (``_L`` between ``Type_ListCount`` becomes ``__L`` after substitution),
    which downstream surfaces as a double space in :func:`_spaced` and
    breaks Robot Framework's 2+-spaces-is-delimiter convention.
    """
    s = _CAMEL_BOUNDARY_1.sub(r"\1_\2", name)
    s = _CAMEL_BOUNDARY_2.sub(r"\1_\2", s)
    s = _MULTI_UNDERSCORE.sub("_", s)  # collapse __, ___, … → _
    return s.lower().strip("_")


def _spaced(name: str) -> str:
    """``SetInterfaceType`` → ``Set Interface Type`` (Robot-keyword style).

    Inserts a space at every camel-case boundary, then title-cases.  Acronym
    runs like ``XMLParser`` become ``XML Parser`` (snake → ``xml_parser``
    → spaced/titled).  Single-space-separated — never double — so Robot
    Framework's keyword-name parser doesn't truncate at a double space.
    """
    return _snake(name).replace("_", " ").title()


def _const(name: str) -> str:
    """``ComSetupDeviceService`` → ``COM_SETUP_DEVICE_SERVICE``."""
    return _snake(name).upper()


# ---------------------------------------------------------------------------
# Keyword emit — one block per RPC, joined into the service resource.
# ---------------------------------------------------------------------------

def _emit_method_keyword(svc: _Service, rpc: _Rpc) -> str:
    method_display = _spaced(rpc.name)

    # Doc string describing the request shape.
    if rpc.params:
        request_doc = "Request fields: " + ", ".join(
            f"{p.name}:{p.type}" for p in rpc.params
        )
    else:
        request_doc = "Request fields: (none)"

    if not rpc.params:
        # Cleanest emitter: no args, no Create Dictionary, no Evaluate.
        return load_template(
            "robot/method_no_args.keyword.tmpl",
            service_name=_spaced(svc.name),
            method_display=method_display,
            full_service_name=svc.full_name,
            method_name=rpc.name,
            return_type=rpc.return_type,
        )

    # Build the [Arguments] tail — one named arg per proto field.
    arg_signature = "".join(f"    ${{{p.name}}}" for p in rpc.params)

    # Build the Create Dictionary lines that assemble the args dict.
    # Robot's `Create Dictionary  k=v  k=v` returns a dict with string values;
    # numeric/bool conversion happens when we serialize via json.dumps.
    dict_pairs = "    ".join(f"{p.name}=${{{p.name}}}" for p in rpc.params)
    arg_dict_build = (
        f"    &{{args}}=    Create Dictionary    {dict_pairs}\n"
    )

    tmpl = (
        "robot/method_streaming.keyword.tmpl"
        if rpc.server_streaming
        else "robot/method_unary.keyword.tmpl"
    )
    return load_template(
        tmpl,
        service_name=_spaced(svc.name),
        method_display=method_display,
        full_service_name=svc.full_name,
        method_name=rpc.name,
        return_type=rpc.return_type,
        request_doc=request_doc,
        arg_signature=arg_signature,
        arg_dict_build=arg_dict_build,
        args_var="${args}",
    )


def _emit_service_resource(svc: _Service) -> str:
    method_keywords = "\n".join(_emit_method_keyword(svc, m) for m in svc.methods)
    return load_template(
        "robot/service.resource.tmpl",
        service_name=_spaced(svc.name),
        service_const=_const(svc.name),
        full_service_name=svc.full_name,
        proto_file=os.path.basename(svc.proto_file),
        generated_at=_dt.date.today().strftime("%Y-%m-%d"),
        method_keywords=method_keywords,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_robot_resources(
    proto_dir: str,
    *,
    service_filter: List[str] = None,
) -> Dict[str, str]:
    """Generate one ``.resource`` per service under ``proto_dir``.

    Returns ``{relative_path: file_content}`` — the caller writes them.

    *service_filter* (optional): only emit resources for services whose
    name is in the list.  Empty / None = all.
    """
    services = parse_proto_folder(proto_dir)
    if service_filter:
        wanted = set(service_filter)
        services = [s for s in services if s.name in wanted]
        if not services:
            raise RobotGenError(
                f"No services in {proto_dir} matched filter {service_filter}"
            )

    files: Dict[str, str] = {}
    for svc in services:
        path = f"{_snake(svc.name)}.resource"
        files[path] = _emit_service_resource(svc)
    return files
