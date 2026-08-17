# **************************************************************************************************************
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
# **************************************************************************************************************
#
# MSB_0001.py — L1 static: generate Python single-service project and check files.

import os, sys, shutil
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from testutils.scaffold_helpers import make_method, make_spec, write_scaffold


def test():
    spec = make_spec(
        service_name="Calculator",
        language="python",
        layout="single",
        methods=[
            make_method("Add",      return_type="int32", params=[("a", "int32"), ("b", "int32")]),
            make_method("Multiply", return_type="int32", params=[("a", "int32"), ("b", "int32")]),
        ],
    )

    out_dir, files = write_scaffold(spec)
    try:
        # --- 1. exact set of relative paths the generator produced -------------
        produced = set(files.keys())
        expected = {
            "main.py",
            "config.py",
            "context.py",
            "pyproject.toml",
            "domain/__init__.py",
            "domain/calculator_service.py",
            "adapters/__init__.py",
            "adapters/api/__init__.py",
            "adapters/api/grpc_adapter.py",
            "proto/__init__.py",
            "proto/calculator.proto",
            "scripts/generate_protos.py",
            "README.md",
            "calculator.nomad.hcl",
            "service_config.json",
        }
        missing = sorted(expected - produced)
        if missing:
            return f"FAIL: missing files: {missing}"

        # --- 2. content markers --------------------------------------------------
        main_py    = files["main.py"]
        proto_text = files["proto/calculator.proto"]
        nomad_text = files["calculator.nomad.hcl"]

        if "from MicroserviceBase.runtime import ServiceRunner" not in main_py:
            return "FAIL: main.py is missing the ServiceRunner import"
        if "CalculatorService" not in main_py:
            return "FAIL: main.py is missing the CalculatorService reference"

        if "service CalculatorService" not in proto_text:
            return "FAIL: proto missing `service CalculatorService` declaration"
        if "rpc Add" not in proto_text or "rpc Multiply" not in proto_text:
            return "FAIL: proto missing Add/Multiply RPCs"

        if 'driver = "raw_exec"' not in nomad_text:
            return "FAIL: nomad.hcl missing raw_exec driver line"
        if 'job "calculator"' not in nomad_text:
            return "FAIL: nomad.hcl missing `job \"calculator\"` block"
        if "CALCULATOR_GRPC_PORT" not in nomad_text or "CALCULATOR_CONSUL_ADDR" not in nomad_text:
            return "FAIL: nomad.hcl env block missing CALCULATOR_GRPC_PORT / CALCULATOR_CONSUL_ADDR"

        # --- 3. count expected files for the deterministic summary ---------------
        n = len(expected)
        return f"OK: {n} expected files present; markers verified in main.py, calculator.proto, calculator.nomad.hcl"

    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
