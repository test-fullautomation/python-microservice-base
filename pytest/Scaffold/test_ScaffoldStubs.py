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
"""A Python service scaffolded with pre-generated stubs starts: the stubs
land in generated/, the package its code imports them from."""

import os
import subprocess
import sys

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)

from MicroserviceBase.adapters.scaffold.generator import (  # noqa: E402
    MethodParam, MethodSpec, ScaffoldSpec, generate_scaffold,
)

pytest.importorskip("grpc_tools")


def _spec():
    return ScaffoldSpec(
        service_name="HelloSvc", version="1.0.0", language="python",
        short_desc="Stub layout check", gen_stubs=True,
        methods=[MethodSpec(name="Greet", params=[MethodParam("name", "string")])],
    )


def _write(root, files):
    for rel, content in files.items():
        path = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)


class Test_PreGeneratedStubs:

    def test_stubs_are_written_to_generated(self):
        files = generate_scaffold(_spec())
        assert "generated/hello_svc_pb2.py" in files
        assert "generated/hello_svc_pb2_grpc.py" in files
        assert not any(p.startswith("proto/") and p.endswith(("_pb2.py", "_pb2_grpc.py")) for p in files)
        # The grpc stub imports its message module relative to its package.
        assert "from . import hello_svc_pb2" in files["generated/hello_svc_pb2_grpc.py"]

    def test_the_scaffolded_service_imports_its_stubs(self, tmp_path):
        _write(tmp_path, generate_scaffold(_spec()))
        # The same imports main.py and the gRPC adapter make, in a fresh
        # interpreter rooted at the service -- as `python main.py` would run.
        code = "from generated import hello_svc_pb2, hello_svc_pb2_grpc; print('ok')"
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(tmp_path), REPO]))
        proc = subprocess.run([sys.executable, "-c", code], cwd=str(tmp_path), env=env,
                              capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0 and "ok" in proc.stdout, proc.stderr
