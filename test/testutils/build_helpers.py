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
# build_helpers.py
#
# Compile / install steps used by the L2 (syntactic) and L3 (build) test
# tiers.  Pure-Python where possible; for C++ we shell out to cmake.
#
# 10.05.2026
#
# --------------------------------------------------------------------------------------------------------------

import os
import py_compile
import shutil
import subprocess
import sys
import tempfile
from typing import List, Optional, Tuple


# --------------------------------------------------------------------------------------------------------------

def py_compile_tree(root):
    """Run :func:`py_compile.compile` on every .py file under ``root``.

    Returns ``(ok_count, errors)`` where ``errors`` is a list of
    ``(relpath, exception)`` tuples.  Skips ``__pycache__`` and
    pre-generated ``*_pb2*.py`` files (those exercise their own codegen
    in L3 and we don't want a missing-import to mask a real syntax bug).
    """
    ok = 0
    errors = []
    for dirpath, _, filenames in os.walk(root):
        if "__pycache__" in dirpath:
            continue
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            if fn.endswith("_pb2.py") or fn.endswith("_pb2_grpc.py"):
                # generated files — checked by run_protoc_python instead
                continue
            full = os.path.join(dirpath, fn)
            rel  = os.path.relpath(full, root).replace(os.sep, "/")
            try:
                py_compile.compile(full, doraise=True)
                ok += 1
            except py_compile.PyCompileError as ex:
                errors.append((rel, ex))
    return ok, errors


# --------------------------------------------------------------------------------------------------------------

def run_protoc_python(proto_dir, out_dir, proto_files=None):
    """Compile every .proto under ``proto_dir`` into ``out_dir`` using
    grpc_tools.protoc (in-process; no external binary needed because
    grpcio-tools is a base dep of MicroserviceBase).

    Returns ``(generated_files, exit_code)``.  When exit_code != 0,
    generated_files is empty.
    """
    try:
        from grpc_tools import protoc as grpc_protoc
    except ImportError:
        return [], 127  # tool not installed

    os.makedirs(out_dir, exist_ok=True)

    if proto_files is None:
        proto_files = []
        for fn in os.listdir(proto_dir):
            if fn.endswith(".proto"):
                proto_files.append(os.path.join(proto_dir, fn))

    if not proto_files:
        return [], 2  # nothing to compile

    args = [
        "grpc_tools.protoc",
        f"--proto_path={proto_dir}",
        f"--python_out={out_dir}",
        f"--grpc_python_out={out_dir}",
    ] + proto_files

    code = grpc_protoc.main(args)

    generated = []
    if code == 0:
        for fn in os.listdir(out_dir):
            if fn.endswith("_pb2.py") or fn.endswith("_pb2_grpc.py"):
                generated.append(fn)
    return sorted(generated), code


# --------------------------------------------------------------------------------------------------------------

def pip_install_editable(project_dir, python=None, extra_args=None, timeout=600):
    """Run ``pip install -e .`` against the generated project.

    Captures stdout+stderr to ``project_dir/.pip_install.log`` for
    debugging.  Returns ``(returncode, log_path)``.
    """
    py = python or sys.executable
    log_path = os.path.join(project_dir, ".pip_install.log")
    cmd = [py, "-m", "pip", "install", "-e", ".", "--no-build-isolation"]
    if extra_args:
        cmd += list(extra_args)
    with open(log_path, "w", encoding="utf-8") as logfh:
        result = subprocess.run(
            cmd,
            cwd=project_dir,
            stdout=logfh,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
    return result.returncode, log_path


def pip_install_deps(project_dir, requirements=None, python=None, timeout=300):
    """Install just the listed packages (or, if ``requirements`` is None,
    parse ``pyproject.toml``'s ``[project] dependencies`` and install
    those).  Useful when we want the deps installed but not the project
    itself.
    """
    py = python or sys.executable
    log_path = os.path.join(project_dir, ".pip_install_deps.log")
    if requirements is None:
        # very small toml parser — pyproject.toml dependencies are a list of strings
        try:
            import tomllib  # py 3.11+
        except ImportError:
            import tomli as tomllib  # py 3.10 fallback
        with open(os.path.join(project_dir, "pyproject.toml"), "rb") as fh:
            data = tomllib.load(fh)
        requirements = data.get("project", {}).get("dependencies", []) or []
    if not requirements:
        return 0, log_path
    cmd = [py, "-m", "pip", "install"] + list(requirements)
    with open(log_path, "w", encoding="utf-8") as logfh:
        result = subprocess.run(cmd, stdout=logfh, stderr=subprocess.STDOUT, timeout=timeout)
    return result.returncode, log_path


# --------------------------------------------------------------------------------------------------------------

def run_protoc_parse(proto_dir, proto_files=None):
    """Parse-only protoc invocation: writes a FileDescriptorSet, no
    language codegen.  Validates .proto syntax without needing a
    language plugin (protobuf, grpc_cpp_plugin, etc.).  Returns
    ``exit_code``.
    """
    try:
        from grpc_tools import protoc as grpc_protoc
    except ImportError:
        return 127

    import tempfile
    if proto_files is None:
        proto_files = []
        for fn in os.listdir(proto_dir):
            if fn.endswith(".proto"):
                proto_files.append(os.path.join(proto_dir, fn))
    if not proto_files:
        return 2

    desc_out = os.path.join(tempfile.gettempdir(), f"msb_desc_{os.getpid()}.pb")
    args = [
        "grpc_tools.protoc",
        f"--proto_path={proto_dir}",
        f"--descriptor_set_out={desc_out}",
    ] + proto_files
    try:
        return grpc_protoc.main(args)
    finally:
        try:
            os.unlink(desc_out)
        except OSError:
            pass


def run_generate_protos_script(project_dir, python=None, timeout=120):
    """Run the project's own ``scripts/generate_protos.py`` (the same
    script the developer runs after a fresh clone).  Returns
    ``(returncode, log_path)``.
    """
    py = python or sys.executable
    script = os.path.join(project_dir, "scripts", "generate_protos.py")
    if not os.path.isfile(script):
        return 2, ""  # script missing
    log_path = os.path.join(project_dir, ".generate_protos.log")
    with open(log_path, "w", encoding="utf-8") as logfh:
        result = subprocess.run(
            [py, script],
            cwd=project_dir,
            stdout=logfh,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
    return result.returncode, log_path


# --------------------------------------------------------------------------------------------------------------

def cmake_configure(project_dir, build_dir=None, timeout=300, extra_args=None):
    """Run ``cmake -S <project_dir> -B <build_dir>``.  Skips when cmake
    isn't on PATH (returns ``(127, "")``).  This is enough to catch
    CMakeLists syntax errors and missing vcpkg manifest entries without
    actually compiling — full build is a separate step the user can
    enable later.
    """
    if shutil.which("cmake") is None:
        return 127, ""
    if build_dir is None:
        build_dir = os.path.join(project_dir, "build_test")
    os.makedirs(build_dir, exist_ok=True)
    log_path = os.path.join(project_dir, ".cmake_configure.log")
    cmd = ["cmake", "-S", project_dir, "-B", build_dir]
    if extra_args:
        cmd += list(extra_args)
    with open(log_path, "w", encoding="utf-8") as logfh:
        result = subprocess.run(cmd, stdout=logfh, stderr=subprocess.STDOUT, timeout=timeout)
    return result.returncode, log_path


# --------------------------------------------------------------------------------------------------------------
