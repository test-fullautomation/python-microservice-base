#  Copyright 2020-2026 Robert Bosch GmbH
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
"""
Fetch a service's GUI folder over gRPC and put it where the GUI looks.

The service side is ``runtime/gui_server.py`` (contract in
``runtime/gui_proto.py``). This is the client half, used by the bridge's
``/api/service-gui/*`` endpoints: ask what the service has, download it
when the checksum moved, and extract it into ``web/services/<folder>/``.

Extraction here serves the browser-hosted GUI, which is served by the
bridge itself. The desktop app asks for the ZIP instead and extracts it
through its preload, because only it knows whether it is running from the
source tree or from ``%APPDATA%``.
"""

from __future__ import annotations

import logging
import os
import zipfile
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

#: Overrides where extracted GUI folders land.
SERVICES_DIR_ENV = "MB_GUI_SERVICES_DIR"

#: Refuse a package bigger than this; a GUI folder is assets, not a dataset.
MAX_PACKAGE_BYTES = 64 * 1024 * 1024


class ServiceGuiError(Exception):
    """
A GUI package could not be fetched or unpacked.

``unavailable`` is True when the service simply does not serve the
contract -- an ordinary answer, not a fault -- and False when something
went wrong on the way.
    """

    def __init__(self, message: str, unavailable: bool = False):
        super().__init__(message)
        self.unavailable = unavailable


def services_dir() -> str:
    """
Where extracted GUI folders go.

``MB_GUI_SERVICES_DIR`` wins; otherwise the Manager GUI's
``web/services`` next to this package.
    """
    override = os.environ.get(SERVICES_DIR_ENV, "").strip()
    if override:
        return os.path.abspath(override)
    return os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "..", "MicroserviceManagerGUI", "web", "services"))


def _channel(host: str, port: int):
    import grpc
    return grpc.insecure_channel(f"{host}:{int(port)}")


def gui_info(host: str, port: int, timeout: float = 10.0) -> dict:
    """
What a service offers: ``{available, folder, checksum, size_bytes, file_count}``.

Raises :class:`ServiceGuiError` when the service does not serve
``ServiceGui`` at all -- an older service, or one that ships no files.
    """
    import grpc

    from ...runtime import gui_proto

    req_cls, resp_cls, _ = gui_proto.method_types("GetGuiInfo")
    with _channel(host, port) as channel:
        call = channel.unary_unary(
            gui_proto.method_path("GetGuiInfo"),
            request_serializer=lambda m: m.SerializeToString(),
            response_deserializer=resp_cls.FromString)
        try:
            info = call(req_cls(), timeout=timeout)
        except grpc.RpcError as exc:
            code = exc.code() if hasattr(exc, "code") else None
            if code in (grpc.StatusCode.UNIMPLEMENTED, grpc.StatusCode.NOT_FOUND):
                raise ServiceGuiError(
                    "this service does not offer its GUI over gRPC", unavailable=True) from exc
            raise ServiceGuiError(f"{host}:{port}: {exc.details() if hasattr(exc, 'details') else exc}") from exc
    return {"available": bool(info.available), "folder": info.folder,
            "checksum": info.checksum, "size_bytes": int(info.size_bytes),
            "file_count": int(info.file_count)}


def fetch_gui_zip(host: str, port: int, known_checksum: str = "",
                  timeout: float = 120.0) -> Tuple[Optional[bytes], str]:
    """
Download the GUI package.

**Arguments:**

* ``host`` / ``port``

  / *Condition*: required /

  Where the service listens.

* ``known_checksum``

  / *Condition*: optional / *Type*: str / *Default*: "" /

  What the caller already has. When it still matches, the service sends
  no bytes and this returns ``(None, checksum)``.

* ``timeout``

  / *Condition*: optional / *Type*: float / *Default*: 120.0 /

  Deadline for the whole stream.

**Returns:**

* ``(zip_bytes, checksum)``

  / *Type*: Tuple[Optional[bytes], str] /

  ``zip_bytes`` is ``None`` when the caller was already current.
    """
    import grpc

    from ...runtime import gui_proto

    req_cls, resp_cls, _ = gui_proto.method_types("GetGuiFiles")
    chunks = []
    total = 0
    checksum = ""
    with _channel(host, port) as channel:
        call = channel.unary_stream(
            gui_proto.method_path("GetGuiFiles"),
            request_serializer=lambda m: m.SerializeToString(),
            response_deserializer=resp_cls.FromString)
        try:
            for chunk in call(req_cls(known_checksum=known_checksum or ""), timeout=timeout):
                checksum = chunk.checksum or checksum
                if chunk.unchanged:
                    return None, checksum
                if not chunk.data:
                    continue
                total += len(chunk.data)
                if total > MAX_PACKAGE_BYTES:
                    raise ServiceGuiError(
                        f"GUI package exceeds {MAX_PACKAGE_BYTES // (1024 * 1024)} MB")
                chunks.append(chunk.data)
        except grpc.RpcError as exc:
            code = exc.code() if hasattr(exc, "code") else None
            if code in (grpc.StatusCode.UNIMPLEMENTED, grpc.StatusCode.NOT_FOUND):
                raise ServiceGuiError(
                    "this service does not offer its GUI over gRPC", unavailable=True) from exc
            raise ServiceGuiError(
                f"{host}:{port}: {exc.details() if hasattr(exc, 'details') else exc}") from exc
    return b"".join(chunks), checksum


def extract_package(zip_bytes: bytes, folder: str, target_root: str = "") -> int:
    """
Unpack a fetched package into ``<target_root>/<folder>/``.

Members that would escape the folder are refused (zip slip), and the
folder is left untouched when that happens.

**Returns:**

* ``count``

  / *Type*: int /

  Number of files written.
    """
    import io

    # A folder name is a plain name -- no separators, no drive, no
    # traversal. Anything else is refused rather than normalised, so a
    # service cannot talk the bridge into writing somewhere else.
    safe = folder.strip()
    if (not safe or safe in (".", "..") or "/" in safe or "\\" in safe
            or ":" in safe or os.path.basename(safe) != safe):
        raise ServiceGuiError(f"unsafe GUI folder name: {folder!r}")

    root = os.path.abspath(target_root or services_dir())
    target = os.path.join(root, safe)
    real_target = os.path.realpath(target)

    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise ServiceGuiError("the service sent something that is not a ZIP") from exc

    with zf:
        members = [m for m in zf.infolist() if not m.is_dir()]
        for member in members:
            destination = os.path.realpath(os.path.join(target, member.filename))
            if destination != real_target and not destination.startswith(real_target + os.sep):
                raise ServiceGuiError(f"refused path outside the folder: {member.filename!r}")
        os.makedirs(target, exist_ok=True)
        for member in members:
            destination = os.path.join(target, member.filename)
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            with zf.open(member) as src, open(destination, "wb") as dst:
                dst.write(src.read())
    logger.info("Extracted %d GUI file(s) into %s", len(members), target)
    return len(members)
