"""Dynamic gRPC client using the server reflection protocol.

Services that enable the standard reflection service (which
:class:`MicroserviceBase.runtime.ServiceRunner` does automatically) can be
called without their proto files being available locally — the reflection
service returns their ``FileDescriptorProto`` bytes and we feed them into a
:class:`google.protobuf.descriptor_pool.DescriptorPool` to build dynamic
message classes.

This keeps the GUI bridge completely decoupled from individual services:
add a new service, and it just appears in the GUI with its methods
browsable.

When the server **doesn't** ship reflection (e.g. built against vcpkg's
grpc port which doesn't include ``grpc++_reflection``), the bridge can
fall back to :class:`LocalProtoClient` which compiles ``.proto`` files
from disk via ``grpc_tools.protoc``.  Same public API, no server help
required.

Only **unary-unary** RPCs are supported at this stage.  Streaming methods
are detected and reported but cannot yet be invoked.
"""

from __future__ import annotations

import glob
import json
import logging
import os
import tempfile
from typing import Any, Dict, Iterable, List, Optional

import grpc
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
from google.protobuf.json_format import MessageToDict, Parse, ParseError
from grpc_reflection.v1alpha import reflection_pb2, reflection_pb2_grpc

logger = logging.getLogger(__name__)


class GrpcReflectError(Exception):
    """Any failure from the reflection client — network, parse, or invoke.

    Attributes:
        is_unimplemented: True when the failure came from a reflection RPC
            that the server returned ``UNIMPLEMENTED`` for — the canonical
            signal that the server wasn't built with reflection support.
            Bridge code uses this to decide whether to fall back to
            :class:`LocalProtoClient`.
    """

    def __init__(self, message: str, *, is_unimplemented: bool = False) -> None:
        super().__init__(message)
        self.is_unimplemented = is_unimplemented


class GrpcReflectClient:
    """Talk to a gRPC server using only its address + the reflection API.

    Usage:
        client = GrpcReflectClient("127.0.0.1:50051")
        services = client.list_services()
        methods = client.list_methods("hello.v1.HelloService")
        result = client.call_unary(
            "hello.v1.HelloService", "Greet", '{"name": "World"}'
        )

    The instance is **not** thread-safe.  Create one per request on the
    bridge side.
    """

    # Built-in gRPC services to hide from callers — they're implementation
    # details of the runtime, not the service's business API.
    _HIDDEN_SERVICES = {
        "grpc.reflection.v1alpha.ServerReflection",
        "grpc.reflection.v1.ServerReflection",
        "grpc.health.v1.Health",
    }

    def __init__(self, target: str, timeout: float = 5.0) -> None:
        self._target = target
        self._timeout = timeout
        self._channel = grpc.insecure_channel(target)
        self._refl = reflection_pb2_grpc.ServerReflectionStub(self._channel)
        self._pool = descriptor_pool.DescriptorPool()
        self._loaded_files: set[str] = set()
        self._loaded_symbols: set[str] = set()

    def close(self) -> None:
        try:
            self._channel.close()
        except Exception:
            pass

    def __enter__(self) -> "GrpcReflectClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Reflection requests
    # ------------------------------------------------------------------

    def _reflect(
        self, request: reflection_pb2.ServerReflectionRequest
    ) -> reflection_pb2.ServerReflectionResponse:
        try:
            responses = self._refl.ServerReflectionInfo(
                iter([request]), timeout=self._timeout
            )
            for resp in responses:
                return resp
        except grpc.RpcError as exc:
            unimpl = (
                hasattr(exc, "code")
                and exc.code() == grpc.StatusCode.UNIMPLEMENTED
            )
            raise GrpcReflectError(
                f"Reflection RPC to {self._target} failed: {exc}",
                is_unimplemented=unimpl,
            ) from exc
        raise GrpcReflectError("Empty reflection response")

    def list_services(self) -> List[str]:
        """Return all fully-qualified service names exposed by the target,
        excluding the built-in reflection / health services."""
        req = reflection_pb2.ServerReflectionRequest(list_services="")
        resp = self._reflect(req)
        names = [s.name for s in resp.list_services_response.service]
        return [n for n in names if n not in self._HIDDEN_SERVICES]

    def _load_file(self, filename: str) -> None:
        if filename in self._loaded_files:
            return
        req = reflection_pb2.ServerReflectionRequest(file_by_filename=filename)
        resp = self._reflect(req)
        fd_bytes_list = resp.file_descriptor_response.file_descriptor_proto
        self._ingest_files(fd_bytes_list)

    def _load_symbol(self, symbol: str) -> None:
        if symbol in self._loaded_symbols:
            return
        req = reflection_pb2.ServerReflectionRequest(file_containing_symbol=symbol)
        resp = self._reflect(req)
        fd_bytes_list = resp.file_descriptor_response.file_descriptor_proto
        self._ingest_files(fd_bytes_list)
        self._loaded_symbols.add(symbol)

    def _ingest_files(self, fd_bytes_list) -> None:
        """Add FileDescriptorProto bytes to the pool in dependency order."""
        # Parse + stage.  We may receive files in any order, so add them
        # repeatedly until all deps are satisfied.
        pending = []
        for raw in fd_bytes_list:
            fd = descriptor_pb2.FileDescriptorProto.FromString(raw)
            if fd.name not in self._loaded_files:
                pending.append(fd)

        progress = True
        while pending and progress:
            progress = False
            remaining = []
            for fd in pending:
                deps_ok = all(d in self._loaded_files for d in fd.dependency)
                if not deps_ok:
                    # Try to fetch the missing dep
                    for dep in fd.dependency:
                        if dep not in self._loaded_files:
                            try:
                                self._load_file(dep)
                            except GrpcReflectError:
                                # Well-known types etc. may be missing from
                                # reflection — the pool can still resolve
                                # them from the built-in descriptors.
                                pass
                    deps_ok = all(
                        d in self._loaded_files or self._is_wellknown(d)
                        for d in fd.dependency
                    )
                if deps_ok:
                    try:
                        self._pool.Add(fd)
                        self._loaded_files.add(fd.name)
                        progress = True
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("Pool.Add(%s) failed: %s", fd.name, exc)
                        self._loaded_files.add(fd.name)
                        progress = True
                else:
                    remaining.append(fd)
            pending = remaining

    @staticmethod
    def _is_wellknown(name: str) -> bool:
        return name.startswith("google/protobuf/")

    # ------------------------------------------------------------------
    # Descriptor lookup
    # ------------------------------------------------------------------

    def _service_descriptor(self, full_name: str):
        self._load_symbol(full_name)
        return self._pool.FindServiceByName(full_name)

    def list_methods(self, full_service_name: str) -> List[Dict[str, Any]]:
        """Return a list of method descriptors for *full_service_name*.

        Each entry:
            {
              "name": "Greet",
              "input_type": "hello.v1.GreetRequest",
              "output_type": "hello.v1.GreetResponse",
              "client_streaming": False,
              "server_streaming": False,
              "input_fields": [ {name, type, label, message_type?}, ... ]
            }
        """
        svc = self._service_descriptor(full_service_name)
        out: List[Dict[str, Any]] = []
        for m in svc.methods:
            out.append(
                {
                    "name": m.name,
                    "input_type": m.input_type.full_name,
                    "output_type": m.output_type.full_name,
                    "client_streaming": m.client_streaming,
                    "server_streaming": m.server_streaming,
                    "input_fields": self._describe_fields(m.input_type),
                    "input_skeleton": self._skeleton_for(m.input_type),
                }
            )
        return out

    @staticmethod
    def _describe_fields(msg_desc) -> List[Dict[str, Any]]:
        """Shallow field list for the top-level fields of a message."""
        out = []
        for f in msg_desc.fields:
            entry: Dict[str, Any] = {
                "name": f.name,
                "number": f.number,
                "type": _FIELD_TYPE_NAMES.get(f.type, str(f.type)),
                "label": _FIELD_LABEL_NAMES.get(f.label, str(f.label)),
            }
            if f.message_type is not None:
                entry["message_type"] = f.message_type.full_name
            out.append(entry)
        return out

    @classmethod
    def _skeleton_for(cls, msg_desc, _depth: int = 0) -> Any:
        """Return a JSON skeleton with default values for all fields.

        Stops recursing at depth 3 to avoid blowing up on cyclic schemas.
        """
        if _depth > 3:
            return {}
        out: Dict[str, Any] = {}
        for f in msg_desc.fields:
            key = f.name
            if f.label == 3:  # LABEL_REPEATED
                out[key] = []
                continue
            if f.type == 11:  # TYPE_MESSAGE
                out[key] = cls._skeleton_for(f.message_type, _depth + 1)
            elif f.type in (1, 2):  # double, float
                out[key] = 0
            elif f.type in (3, 4, 5, 6, 7, 13, 15, 16, 17, 18):  # int/long
                out[key] = 0
            elif f.type == 8:  # bool
                out[key] = False
            elif f.type == 9:  # string
                out[key] = ""
            elif f.type == 12:  # bytes
                out[key] = ""
            elif f.type == 14:  # enum
                out[key] = 0
            else:
                out[key] = None
        return out

    # ------------------------------------------------------------------
    # Dynamic invocation
    # ------------------------------------------------------------------

    def call_method(
        self,
        full_service_name: str,
        method_name: str,
        args_json: str,
        max_events: int = 100,
        max_seconds: float = 15.0,
    ) -> Dict[str, Any]:
        """Invoke a unary-unary or server-streaming method.

        * **Unary-unary** → returns ``{"streaming": False, "result": <dict>}``.
        * **Server-streaming** → reads up to *max_events* events from the
          stream (or until *max_seconds* elapses), then cancels the RPC and
          returns
          ``{"streaming": True, "events": [<dict>, ...], "truncated": bool}``.
        * **Client- or bidi-streaming** → raises :class:`GrpcReflectError`.

        Client-streaming and bidirectional streaming need a different UI
        pattern (incremental request sends + cancel button) and are
        intentionally rejected here.
        """
        import time

        svc = self._service_descriptor(full_service_name)
        method = svc.FindMethodByName(method_name)
        if method is None:
            raise GrpcReflectError(
                f"Method '{method_name}' not found in {full_service_name}"
            )
        if method.client_streaming:
            raise GrpcReflectError(
                f"Client-streaming RPCs are not supported "
                f"({full_service_name}/{method_name})"
            )

        req_cls = message_factory.GetMessageClass(method.input_type)
        resp_cls = message_factory.GetMessageClass(method.output_type)

        req_msg = req_cls()
        if args_json and args_json.strip():
            try:
                Parse(args_json, req_msg)
            except ParseError as exc:
                raise GrpcReflectError(
                    f"Invalid JSON for {method.input_type.full_name}: {exc}"
                ) from exc

        full_path = f"/{full_service_name}/{method_name}"

        # ---- Unary-unary ------------------------------------------------
        if not method.server_streaming:
            call = self._channel.unary_unary(
                full_path,
                request_serializer=req_cls.SerializeToString,
                response_deserializer=resp_cls.FromString,
            )
            try:
                resp = call(req_msg, timeout=self._timeout)
            except grpc.RpcError as exc:
                raise GrpcReflectError(self._fmt_rpc_err(exc)) from exc
            return {
                "streaming": False,
                "result": MessageToDict(resp, preserving_proto_field_name=True),
            }

        # ---- Server-streaming -------------------------------------------
        call = self._channel.unary_stream(
            full_path,
            request_serializer=req_cls.SerializeToString,
            response_deserializer=resp_cls.FromString,
        )
        stream = call(req_msg, timeout=max_seconds + 2)

        events: List[Dict[str, Any]] = []
        truncated = False
        start = time.monotonic()
        try:
            for item in stream:
                events.append(
                    MessageToDict(item, preserving_proto_field_name=True)
                )
                if len(events) >= max_events:
                    truncated = True
                    break
                if time.monotonic() - start >= max_seconds:
                    truncated = True
                    break
        except grpc.RpcError as exc:
            # If we already collected some events, return them with the
            # error note rather than discarding everything.
            if events:
                return {
                    "streaming": True,
                    "events": events,
                    "truncated": True,
                    "error": self._fmt_rpc_err(exc),
                }
            raise GrpcReflectError(self._fmt_rpc_err(exc)) from exc
        finally:
            try:
                stream.cancel()
            except Exception:
                pass

        return {
            "streaming": True,
            "events": events,
            "truncated": truncated,
        }

    # Backwards-compat alias — unwraps unary results to match the old shape.
    def call_unary(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        data = self.call_method(*args, **kwargs)
        if not data.get("streaming"):
            return data.get("result") or {}
        return data

    @staticmethod
    def _fmt_rpc_err(exc: grpc.RpcError) -> str:
        code = exc.code() if hasattr(exc, "code") else grpc.StatusCode.UNKNOWN
        detail = exc.details() if hasattr(exc, "details") else str(exc)
        return f"{code.name}: {detail}"


class LocalProtoClient:
    """Drop-in replacement for :class:`GrpcReflectClient` when the server
    has no reflection support.

    Builds the descriptor pool by compiling local ``.proto`` files via
    ``grpc_tools.protoc`` instead of asking the server.  Has the same
    public methods (:meth:`list_services`, :meth:`list_methods`,
    :meth:`call_method`, :meth:`call_unary`) so callers can swap one for
    the other.

    The client owns a gRPC channel to *target* for the actual invocations
    — only schema discovery is local.

    Usage:
        client = LocalProtoClient(
            "127.0.0.1:50051",
            proto_files=["proto/hello.proto"],     # explicit
        )
        # or
        client = LocalProtoClient.from_search_paths(
            "127.0.0.1:50051",
            search_paths=["./proto", "C:/projects"],
        )
    """

    _HIDDEN_SERVICES = GrpcReflectClient._HIDDEN_SERVICES

    def __init__(
        self,
        target: str,
        proto_files: Iterable[str],
        *,
        include_paths: Optional[Iterable[str]] = None,
        timeout: float = 5.0,
    ) -> None:
        self._target = target
        self._timeout = timeout
        self._channel = grpc.insecure_channel(target)
        self._pool = descriptor_pool.DescriptorPool()
        self._loaded_files: set[str] = set()
        self._proto_sources: List[str] = list(proto_files)
        self._include_paths: List[str] = list(include_paths or [])

        if not self._proto_sources:
            raise GrpcReflectError(
                "LocalProtoClient needs at least one .proto file"
            )
        self._compile_and_load()

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_search_paths(
        cls,
        target: str,
        search_paths: Iterable[str],
        *,
        timeout: float = 5.0,
    ) -> "LocalProtoClient":
        """Build a client by globbing ``**/*.proto`` under each search path.

        Empty/missing dirs are silently skipped.  Each search path is also
        added as a protoc ``-I`` include path so cross-file imports
        resolve.
        """
        files: List[str] = []
        includes: List[str] = []
        for root in search_paths:
            root = (root or "").strip()
            if not root or not os.path.isdir(root):
                continue
            includes.append(os.path.abspath(root))
            for path in glob.glob(
                os.path.join(root, "**", "*.proto"), recursive=True
            ):
                files.append(os.path.abspath(path))
        if not files:
            raise GrpcReflectError(
                "No .proto files found under search paths: "
                + ", ".join(search_paths)
            )
        # De-dup while preserving order.
        seen: set[str] = set()
        unique = [f for f in files if not (f in seen or seen.add(f))]
        return cls(target, unique, include_paths=includes, timeout=timeout)

    # ------------------------------------------------------------------
    # Compile + ingest
    # ------------------------------------------------------------------

    def _compile_and_load(self) -> None:
        """Run protoc on the proto sources, harvest a FileDescriptorSet,
        and register every FileDescriptorProto in the pool."""
        try:
            from grpc_tools import protoc as _grpc_protoc
            from grpc_tools import _protoc_compiler  # noqa: F401  (sanity)
        except ImportError as exc:  # pragma: no cover
            raise GrpcReflectError(
                "grpc_tools is required for LocalProtoClient "
                "(`pip install grpcio-tools`)."
            ) from exc

        # Always add grpc_tools' bundled .proto root so well-known types
        # (google/protobuf/*.proto) resolve.
        from importlib import resources
        try:
            wkt_root = str(resources.files("grpc_tools").joinpath("_proto"))
        except Exception:
            wkt_root = ""

        with tempfile.NamedTemporaryFile(
            suffix=".pb", delete=False
        ) as descriptor_file:
            descriptor_path = descriptor_file.name

        try:
            argv = [
                "protoc",
                f"--descriptor_set_out={descriptor_path}",
                "--include_imports",
                "--include_source_info",
            ]
            for inc in self._include_paths:
                argv.append(f"-I{inc}")
            if wkt_root:
                argv.append(f"-I{wkt_root}")
            argv.extend(self._proto_sources)

            rc = _grpc_protoc.main(argv)
            if rc != 0:
                raise GrpcReflectError(
                    f"protoc returned exit code {rc} for sources "
                    f"{self._proto_sources}"
                )

            with open(descriptor_path, "rb") as fh:
                fds = descriptor_pb2.FileDescriptorSet.FromString(fh.read())
        finally:
            try:
                os.unlink(descriptor_path)
            except OSError:
                pass

        # Add files in dependency order.  protoc's --include_imports
        # already emits in topological order, but be defensive.
        pending = list(fds.file)
        progress = True
        while pending and progress:
            progress = False
            remaining = []
            for fd in pending:
                deps_ok = all(
                    d in self._loaded_files or self._is_wellknown(d)
                    for d in fd.dependency
                )
                if not deps_ok:
                    remaining.append(fd)
                    continue
                try:
                    self._pool.Add(fd)
                except Exception as exc:  # noqa: BLE001
                    # Already present (e.g. WKT) — fine.
                    logger.debug("Pool.Add(%s) skipped: %s", fd.name, exc)
                self._loaded_files.add(fd.name)
                progress = True
            pending = remaining

    @staticmethod
    def _is_wellknown(name: str) -> bool:
        return name.startswith("google/protobuf/")

    # ------------------------------------------------------------------
    # Public API — mirrors GrpcReflectClient
    # ------------------------------------------------------------------

    def close(self) -> None:
        try:
            self._channel.close()
        except Exception:
            pass

    def __enter__(self) -> "LocalProtoClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def list_services(self) -> List[str]:
        """Return all fully-qualified service names found in the loaded
        proto files, excluding built-in reflection / health services."""
        out: List[str] = []
        for fname in sorted(self._loaded_files):
            try:
                fd = self._pool.FindFileByName(fname)
            except KeyError:
                continue
            for svc in fd.services_by_name.values():
                if svc.full_name not in self._HIDDEN_SERVICES:
                    out.append(svc.full_name)
        return out

    def list_methods(self, full_service_name: str) -> List[Dict[str, Any]]:
        """Same shape as :meth:`GrpcReflectClient.list_methods`."""
        try:
            svc = self._pool.FindServiceByName(full_service_name)
        except KeyError as exc:
            raise GrpcReflectError(
                f"Service '{full_service_name}' not found in loaded protos "
                f"({len(self._loaded_files)} files compiled)."
            ) from exc
        out: List[Dict[str, Any]] = []
        for m in svc.methods:
            out.append(
                {
                    "name": m.name,
                    "input_type": m.input_type.full_name,
                    "output_type": m.output_type.full_name,
                    "client_streaming": m.client_streaming,
                    "server_streaming": m.server_streaming,
                    "input_fields": GrpcReflectClient._describe_fields(
                        m.input_type
                    ),
                    "input_skeleton": GrpcReflectClient._skeleton_for(
                        m.input_type
                    ),
                }
            )
        return out

    def call_method(
        self,
        full_service_name: str,
        method_name: str,
        args_json: str,
        max_events: int = 100,
        max_seconds: float = 15.0,
    ) -> Dict[str, Any]:
        """Same semantics as :meth:`GrpcReflectClient.call_method`."""
        # Reuse GrpcReflectClient's invocation core by binding it to our
        # own channel + descriptor pool.  Simpler than copy-pasting the
        # streaming branch.
        return _invoke_method(
            channel=self._channel,
            pool=self._pool,
            target=self._target,
            timeout=self._timeout,
            full_service_name=full_service_name,
            method_name=method_name,
            args_json=args_json,
            max_events=max_events,
            max_seconds=max_seconds,
        )

    def call_unary(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        data = self.call_method(*args, **kwargs)
        if not data.get("streaming"):
            return data.get("result") or {}
        return data


# ---------------------------------------------------------------------------
# Shared invocation core (used by LocalProtoClient; GrpcReflectClient still
# inlines its own copy for backwards compatibility).
# ---------------------------------------------------------------------------

def _invoke_method(
    *,
    channel: grpc.Channel,
    pool: descriptor_pool.DescriptorPool,
    target: str,
    timeout: float,
    full_service_name: str,
    method_name: str,
    args_json: str,
    max_events: int,
    max_seconds: float,
) -> Dict[str, Any]:
    import time

    try:
        svc = pool.FindServiceByName(full_service_name)
    except KeyError as exc:
        raise GrpcReflectError(
            f"Service '{full_service_name}' not in descriptor pool"
        ) from exc

    method = svc.FindMethodByName(method_name)
    if method is None:
        raise GrpcReflectError(
            f"Method '{method_name}' not found in {full_service_name}"
        )
    if method.client_streaming:
        raise GrpcReflectError(
            f"Client-streaming RPCs are not supported "
            f"({full_service_name}/{method_name})"
        )

    req_cls = message_factory.GetMessageClass(method.input_type)
    resp_cls = message_factory.GetMessageClass(method.output_type)

    req_msg = req_cls()
    if args_json and args_json.strip():
        try:
            Parse(args_json, req_msg)
        except ParseError as exc:
            raise GrpcReflectError(
                f"Invalid JSON for {method.input_type.full_name}: {exc}"
            ) from exc

    full_path = f"/{full_service_name}/{method_name}"

    if not method.server_streaming:
        call = channel.unary_unary(
            full_path,
            request_serializer=req_cls.SerializeToString,
            response_deserializer=resp_cls.FromString,
        )
        try:
            resp = call(req_msg, timeout=timeout)
        except grpc.RpcError as exc:
            raise GrpcReflectError(
                GrpcReflectClient._fmt_rpc_err(exc)
            ) from exc
        return {
            "streaming": False,
            "result": MessageToDict(resp, preserving_proto_field_name=True),
        }

    call = channel.unary_stream(
        full_path,
        request_serializer=req_cls.SerializeToString,
        response_deserializer=resp_cls.FromString,
    )
    stream = call(req_msg, timeout=max_seconds + 2)

    events: List[Dict[str, Any]] = []
    truncated = False
    start = time.monotonic()
    try:
        for item in stream:
            events.append(
                MessageToDict(item, preserving_proto_field_name=True)
            )
            if len(events) >= max_events:
                truncated = True
                break
            if time.monotonic() - start >= max_seconds:
                truncated = True
                break
    except grpc.RpcError as exc:
        if events:
            return {
                "streaming": True,
                "events": events,
                "truncated": True,
                "error": GrpcReflectClient._fmt_rpc_err(exc),
            }
        raise GrpcReflectError(
            GrpcReflectClient._fmt_rpc_err(exc)
        ) from exc
    finally:
        try:
            stream.cancel()
        except Exception:
            pass

    return {
        "streaming": True,
        "events": events,
        "truncated": truncated,
    }


# --- protobuf descriptor enum → human-readable string mappings ----------

_FIELD_TYPE_NAMES = {
    1: "double", 2: "float", 3: "int64", 4: "uint64", 5: "int32",
    6: "fixed64", 7: "fixed32", 8: "bool", 9: "string", 10: "group",
    11: "message", 12: "bytes", 13: "uint32", 14: "enum",
    15: "sfixed32", 16: "sfixed64", 17: "sint32", 18: "sint64",
}

_FIELD_LABEL_NAMES = {
    1: "optional",
    2: "required",
    3: "repeated",
}
