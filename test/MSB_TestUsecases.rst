.. Copyright 2020-2026 Robert Bosch GmbH

.. Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

.. http://www.apache.org/licenses/LICENSE-2.0

.. Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.

Test Use Cases
==============

* **Test MSB_0001**

  [ScaffoldGenerator_Python / GOODCASE]

   **Generate a Python single-service project and assert file layout**

   Expected: All expected files written; key markers present in main.py / .proto / nomad.hcl

   *Comment: L1 static check*

----

* **Test MSB_0002**

  [ScaffoldGenerator_Python / GOODCASE]

   **Generated Python project compiles (py_compile + protoc)**

   Expected: Every .py compiles; protoc generates calculator_pb2.py + calculator_pb2_grpc.py

   *Comment: L2 syntactic check*

----

* **Test MSB_0003**

  [ScaffoldGenerator_Python / GOODCASE]

   **Generated Python project's scripts/generate_protos.py runs cleanly**

   Expected: scripts/generate_protos.py exits 0 and writes proto/*_pb2*.py

   *Comment: L3 build check*

----

* **Test MSB_0004**

  [ScaffoldGenerator_Python / GOODCASE]

   **Generated Python service registers in Consul and answers a gRPC call**

   Expected: calculator_service appears in Consul catalog (passing); reflection lists Calculator.Add

   *Comment: L4 runtime check (uses real Consul agent in -dev mode)*

   *Hint: Requires consul on PATH; SKIPPED otherwise*

----

* **Test MSB_0005**

  [ScaffoldGenerator_Cpp / GOODCASE]

   **Generate a C++ multi_proto project (Toolbox=Calculator+Echo) and assert layout**

   Expected: Per-service .proto + domain + adapter present; CMakeLists / main.cpp / nomad.hcl emitted

   *Comment: L1 static check, multi_proto layout*

----

* **Test MSB_0006**

  [ScaffoldGenerator_Python / GOODCASE]

   **Generate a Python monorepo project (Toolbox = Calculator + Echo) and assert layout**

   Expected: Per-service src tree + shared toolbox.proto + per-service deploy artefacts emitted

   *Comment: L1 static check, monorepo layout*

----

* **Test MSB_0007**

  [ScaffoldGenerator_Python / GOODCASE]

   **Python monorepo compiles + shared .proto compiles**

   Expected: py_compile clean; protoc emits toolbox_pb2.py + toolbox_pb2_grpc.py

   *Comment: L2 syntactic check, monorepo layout*

----

* **Test MSB_0008**

  [ScaffoldGenerator_Cpp / GOODCASE]

   **Generate a C++ single-service project (Echo) and assert layout**

   Expected: CMakeLists, main.cpp, EchoService domain + adapter, echo.proto + .nomad.hcl emitted

   *Comment: L1 static check, single-service C++*

----

* **Test MSB_0009**

  [ScaffoldGenerator_Cpp / BADCASE]

   **Python + multi_proto layout must raise NotImplementedError**

   Expected: generate_scaffold raises NotImplementedError mentioning python multi_proto

   *Comment: Documents that multi_proto is C++-only in this release*

----

* **Test MSB_0010**

  [ScaffoldGenerator_Python / GOODCASE]

   **Python monorepo's scripts/generate_protos.py runs cleanly**

   Expected: exit 0; toolbox_pb2.py + toolbox_pb2_grpc.py written under proto/

   *Comment: L3 build check, monorepo layout*

----

* **Test MSB_0011**

  [ScaffoldGenerator_Python / GOODCASE]

   **Python monorepo Calculator service registers in Consul + reflection works**

   Expected: Service appears in Consul (passing); reflection lists calculator.v1.CalculatorService

   *Comment: L4 runtime check, monorepo layout*

   *Hint: Requires consul on PATH; SKIPPED otherwise*

----

* **Test MSB_0012**

  [ScaffoldGenerator_Cpp / GOODCASE]

   **C++ single-service .proto parses cleanly through protoc**

   Expected: echo.proto compiles to a FileDescriptorSet without errors

   *Comment: L2 syntactic check, single-service C++*

----

* **Test MSB_0013**

  [ScaffoldGenerator_Cpp / GOODCASE]

   **C++ multi_proto: every per-service .proto parses cleanly**

   Expected: calculator.proto and echo.proto each compile independently

   *Comment: L2 syntactic check, multi_proto layout*

----

* **Test MSB_0014**

  [ScaffoldGenerator_Cpp / GOODCASE]

   **Generate a C++ monorepo project (Toolbox = Calculator + Echo) and assert layout**

   Expected: Per-service src tree + shared toolbox.proto + per-service deploy artefacts emitted

   *Comment: L1 static check, C++ monorepo*

----

* **Test MSB_0015**

  [ScaffoldGenerator_Cpp / GOODCASE]

   **C++ monorepo shared toolbox.proto parses cleanly**

   Expected: Single shared .proto declaring multiple services compiles

   *Comment: L2 syntactic check, C++ monorepo*

----

* **Test MSB_0016**

  [ScaffoldGenerator_Cpp / GOODCASE]

   **C++ single-service CMake configure step succeeds**

   Expected: cmake -S . -B build_test exits 0 (or skips when cmake/gRPC absent)

   *Comment: L3 build check, C++ single-service*

   *Hint: Skips when cmake or system gRPC is unavailable*

----

* **Test MSB_0017**

  [ScaffoldGenerator_E2E / GOODCASE]

   **Submit generated calculator.nomad.hcl to Nomad; service registers + answers reflection**

   Expected: Nomad allocation runs; service registers via Consul; reflection lists CalculatorService

   *Comment: L5 end-to-end check*

   *Hint: Requires both consul AND nomad on PATH; SKIPPED otherwise*

----

* **Test MSB_0018**

  [ScaffoldGenerator_Python / BADCASE]

   **Empty service_name produces malformed file paths (no input validation)**

   Expected: Generator currently accepts empty input and emits leading-dot paths

   *Comment: Generator-side bug — open follow-up to add input validation*

   *Hint: Documents missing input validation; remove if generator gains a ValueError*

----

Generated: 10.05.2026 - 15:35:51

