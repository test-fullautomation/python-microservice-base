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
Serve a service's own GUI folder over gRPC (``ServiceGui``, see
``gui_proto``).

``ServiceRunner`` binds this automatically when the service has a GUI
folder, so a service author ships files and nothing else: the Manager GUI
asks for them the first time it opens the service, and again only when the
checksum changes.
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import threading
import zipfile
from typing import Iterable, Iterator, Optional, Tuple

import grpc

from . import gui_proto

logger = logging.getLogger(__name__)

#: Files never worth shipping to a GUI.
_SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".idea", ".vscode"}
_SKIP_SUFFIXES = (".pyc", ".pyo", ".log", ".tmp", "~")


def _walk(root: str) -> Iterator[Tuple[str, str]]:
    """``(absolute path, archive path)`` of every file worth shipping."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        for name in sorted(filenames):
            if name.endswith(_SKIP_SUFFIXES):
                continue
            full = os.path.join(dirpath, name)
            yield full, os.path.relpath(full, root).replace(os.sep, "/")


class GuiPackage:
    """
The GUI folder of one service, as a checksum and a ZIP.

Both are built on first use and rebuilt only when the folder changes, so
repeated opens in the GUI cost a directory walk and nothing more.

**Arguments:**

* ``directory``

  / *Condition*: required / *Type*: str /

  Folder holding the GUI files (``component.json``, panels, assets).

* ``folder``

  / *Condition*: required / *Type*: str /

  Where the files belong on the GUI side -- the same name the service
  registers in Consul as ``Meta.gui``, e.g. ``"ClimateChamber1.0.0"``.
    """

    def __init__(self, directory: str, folder: str):
        self.directory = os.path.abspath(directory)
        self.folder = folder
        self._lock = threading.Lock()
        self._cache: Optional[Tuple[str, bytes, int]] = None   # checksum, zip, file count
        self._signature: Optional[tuple] = None

    # ---------------------------------------------------------------- state

    def exists(self) -> bool:
        """True when the folder is there and holds at least one file."""
        return os.path.isdir(self.directory) and any(True for _ in _walk(self.directory))

    def _current_signature(self) -> tuple:
        """Cheap change detector: path, size and mtime of every file."""
        return tuple((arc, os.path.getsize(full), int(os.path.getmtime(full)))
                     for full, arc in _walk(self.directory))

    def _build(self) -> Tuple[str, bytes, int]:
        digest = hashlib.sha256()
        buf = io.BytesIO()
        count = 0
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for full, arc in _walk(self.directory):
                with open(full, "rb") as fh:
                    data = fh.read()
                # Path and content both, so a rename alone changes the sum.
                digest.update(arc.encode("utf-8"))
                digest.update(b"\0")
                digest.update(data)
                zf.writestr(arc, data)
                count += 1
        return digest.hexdigest()[:32], buf.getvalue(), count

    def package(self) -> Tuple[str, bytes, int]:
        """
The current ``(checksum, zip bytes, file count)``, rebuilt when the
folder changed since the last call.
        """
        with self._lock:
            signature = self._current_signature()
            if self._cache is None or signature != self._signature:
                self._cache = self._build()
                self._signature = signature
                logger.debug("GUI package %s rebuilt: %d file(s), %d bytes",
                             self.folder, self._cache[2], len(self._cache[1]))
            return self._cache

    # ------------------------------------------------------------- handlers

    def get_gui_info(self, request, context):   # noqa: ARG002 - gRPC signature
        """``GetGuiInfo``: what is on offer, without sending it."""
        GuiInfo = gui_proto.message("GuiInfo")
        if not self.exists():
            return GuiInfo(folder=self.folder, available=False)
        checksum, blob, count = self.package()
        return GuiInfo(folder=self.folder, checksum=checksum, size_bytes=len(blob),
                       file_count=count, available=True)

    def get_gui_files(self, request, context):   # noqa: ARG002 - gRPC signature
        """``GetGuiFiles``: the folder as a chunked ZIP stream."""
        GuiChunk = gui_proto.message("GuiChunk")
        if not self.exists():
            context.abort(grpc.StatusCode.NOT_FOUND,
                          f"{self.folder}: this service ships no GUI files")
            return
        checksum, blob, _count = self.package()
        if getattr(request, "known_checksum", "") == checksum:
            # The caller is already current: say so and send no bytes.
            yield GuiChunk(checksum=checksum, unchanged=True)
            return
        for start in range(0, len(blob), gui_proto.CHUNK_BYTES):
            yield GuiChunk(data=blob[start:start + gui_proto.CHUNK_BYTES], checksum=checksum)


def gui_generic_handler(package: GuiPackage):
    """
A generic gRPC handler serving ``ServiceGui`` from *package*.

Built with ``grpc.method_handlers_generic_handler`` so a service needs no
generated stubs -- the same trick the bridge uses on the client side.
    """
    info_req, info_resp, _ = gui_proto.method_types("GetGuiInfo")
    files_req, files_resp, _ = gui_proto.method_types("GetGuiFiles")
    return grpc.method_handlers_generic_handler(gui_proto.FULL_SERVICE_NAME, {
        "GetGuiInfo": grpc.unary_unary_rpc_method_handler(
            package.get_gui_info,
            request_deserializer=info_req.FromString,
            response_serializer=info_resp.SerializeToString),
        "GetGuiFiles": grpc.unary_stream_rpc_method_handler(
            package.get_gui_files,
            request_deserializer=files_req.FromString,
            response_serializer=files_resp.SerializeToString),
    })


def add_service_gui(server, directory: str, folder: str) -> Optional[GuiPackage]:
    """
Serve *directory* as the service's GUI folder, if it has one.

**Arguments:**

* ``server``

  / *Condition*: required / *Type*: grpc.Server or grpc.aio.Server /

  The running server.

* ``directory``

  / *Condition*: required / *Type*: str /

  Folder holding the GUI files.

* ``folder``

  / *Condition*: required / *Type*: str /

  The name the files belong under on the GUI side (Consul ``Meta.gui``).

**Returns:**

* ``package``

  / *Type*: Optional[GuiPackage] /

  The package that was bound, or ``None`` when the folder holds nothing.

``ServiceGui`` must not be added to the server's reflection list: its
types live in a private descriptor pool, so reflection could list it but
not describe it, and clients walking the list would fail on it.
    """
    package = GuiPackage(directory, folder)
    if not package.exists():
        logger.debug("No GUI files in %s; ServiceGui not served", directory)
        return None
    server.add_generic_rpc_handlers((gui_generic_handler(package),))
    logger.info("Serving GUI folder %s from %s", folder, package.directory)
    return package
