# **************************************************************************************************************
#
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
#
# **************************************************************************************************************
#
# scaffold_helpers.py
#
# Programmatic invocation of the MicroserviceBase scaffold generator for
# component tests.  Constructs a ScaffoldSpec from a small dict, runs the
# in-process generator, and writes the result to a temp dir we can later
# build / run.
#
# 10.05.2026
#
# --------------------------------------------------------------------------------------------------------------

import os
import sys
import tempfile
from typing import Dict, List, Optional

# Make the framework importable when running tests directly from test/
_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from MicroserviceBase.adapters.scaffold.generator import (
    MethodParam,
    MethodSpec,
    ServiceBlock,
    ScaffoldSpec,
    generate_scaffold,
)


# --------------------------------------------------------------------------------------------------------------

def make_method(name, return_type="string", params=None, description=""):
    """Convenience: build a MethodSpec from positional args.

    ``params`` is a list of ``(name, type, required)`` tuples or
    ``(name, type)`` (required defaults to True).
    """
    method_params = []
    for p in (params or []):
        if len(p) == 2:
            method_params.append(MethodParam(name=p[0], type=p[1], required=True))
        elif len(p) == 3:
            method_params.append(MethodParam(name=p[0], type=p[1], required=bool(p[2])))
        else:
            raise ValueError(f"param tuple must be (name, type) or (name, type, required); got {p!r}")
    return MethodSpec(
        name=name,
        return_type=return_type,
        params=method_params,
        description=description,
    )


def make_service(name, methods, proto_file=""):
    """Convenience wrapper for ServiceBlock."""
    return ServiceBlock(name=name, methods=methods, proto_file=proto_file)


def make_spec(
    service_name,
    *,
    language="python",
    layout="single",
    methods=None,
    services=None,
    gen_nomad=True,
    gen_stubs=False,
    version="1.0.0",
    description="",
    short_desc="",
    group="examples",
    server_grpc_kind="msys2",
    client_grpc_kind="google",
    gui_type="none",
    nomad_consul_addr="http://127.0.0.1:8500",
):
    """Build a ScaffoldSpec from keyword args.  Sensible defaults for tests:
    no GUI, no pre-built stubs (we run protoc explicitly in L3), monorepo
    only when caller passes services.
    """
    return ScaffoldSpec(
        service_name=service_name,
        version=version,
        description=description,
        short_desc=short_desc,
        group=group,
        language=language,
        layout=layout,
        gui_type=gui_type,
        client_grpc_kind=client_grpc_kind,
        server_grpc_kind=server_grpc_kind,
        gen_nomad=gen_nomad,
        gen_build_scripts=True,
        gen_readme=True,
        gen_stubs=gen_stubs,
        nomad_consul_addr=nomad_consul_addr,
        methods=methods or [],
        services=services or [],
    )


# --------------------------------------------------------------------------------------------------------------

def write_scaffold(spec, out_dir=None):
    """Run the scaffold generator and write every file to ``out_dir``.

    Returns ``(out_dir, files_dict)`` where ``files_dict`` is the same
    dict returned by ``generate_scaffold`` (relpath -> content).  When
    ``out_dir`` is ``None`` a fresh ``tempfile.mkdtemp(prefix="msb_test_")``
    directory is created and returned.

    The directory is **not** auto-deleted; callers can clean it up with
    ``shutil.rmtree(out_dir)`` once their assertions are done.
    """
    if out_dir is None:
        out_dir = tempfile.mkdtemp(prefix="msb_test_")

    files = generate_scaffold(spec)

    for relpath, content in files.items():
        full = os.path.join(out_dir, relpath)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        # protobuf-generated stubs are bytes-y in places; keep utf-8 with
        # ``replace`` to avoid choking the test on a stray byte.
        with open(full, "w", encoding="utf-8", errors="replace", newline="\n") as fh:
            fh.write(content)

    return out_dir, files


def list_relative(out_dir):
    """Return every file under ``out_dir`` as a sorted list of POSIX-style
    relative paths.  Useful when an assertion needs to compare against an
    expected file list verbatim.
    """
    rels = []
    for dirpath, _, filenames in os.walk(out_dir):
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, out_dir).replace(os.sep, "/")
            rels.append(rel)
    return sorted(rels)


# --------------------------------------------------------------------------------------------------------------
