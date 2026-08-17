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
# TestConfig.py
#
# Nguyen Huynh Tri Cuong (MS/EMC51)
# Adapted from python-process-hub component test for MicroserviceBase.
#
# 10.05.2026
#
# --------------------------------------------------------------------------------------------------------------

listofdictUsecases = []

# Optional keys (all others are mandatory):
#   dictUsecase['HINT']       = None
#   dictUsecase['COMMENT']    = None
#   dictUsecase['USERAWPATH'] = False    # if True, 'TESTFILE' will not be normalized

# A test that returns "SKIPPED: <reason>" (string prefix) is counted SKIPPED
# rather than FAILED — used by L4/L5 cases that need consul/nomad on PATH.

# --------------------------------------------------------------------------------------------------------------
#TM***
# ==============================================================================
# ScaffoldGenerator — Python single-service
# ==============================================================================
# --------------------------------------------------------------------------------------------------------------
dictUsecase = {}
dictUsecase['TESTID']            = "MSB_0001"
dictUsecase['DESCRIPTION']       = "Generate a Python single-service project and assert file layout"
dictUsecase['EXPECTATION']       = "All expected files written; key markers present in main.py / .proto / nomad.hcl"
dictUsecase['SECTION']           = "ScaffoldGenerator_Python"
dictUsecase['SUBSECTION']        = "GOODCASE"
dictUsecase['HINT']              = None
dictUsecase['COMMENT']           = "L1 static check"
dictUsecase['TESTFILE']          = r"MSB_0001.py"
dictUsecase['EXPECTEDEXCEPTION'] = None
dictUsecase['EXPECTEDRETURN']    = "OK: 15 expected files present; markers verified in main.py, calculator.proto, calculator.nomad.hcl"
listofdictUsecases.append(dictUsecase)
del dictUsecase
# --------------------------------------------------------------------------------------------------------------
dictUsecase = {}
dictUsecase['TESTID']            = "MSB_0002"
dictUsecase['DESCRIPTION']       = "Generated Python project compiles (py_compile + protoc)"
dictUsecase['EXPECTATION']       = "Every .py compiles; protoc generates calculator_pb2.py + calculator_pb2_grpc.py"
dictUsecase['SECTION']           = "ScaffoldGenerator_Python"
dictUsecase['SUBSECTION']        = "GOODCASE"
dictUsecase['HINT']              = None
dictUsecase['COMMENT']           = "L2 syntactic check"
dictUsecase['TESTFILE']          = r"MSB_0002.py"
dictUsecase['EXPECTEDEXCEPTION'] = None
dictUsecase['EXPECTEDRETURN']    = "OK: py_compile clean; protoc emitted calculator_pb2.py and calculator_pb2_grpc.py"
listofdictUsecases.append(dictUsecase)
del dictUsecase
# --------------------------------------------------------------------------------------------------------------
dictUsecase = {}
dictUsecase['TESTID']            = "MSB_0003"
dictUsecase['DESCRIPTION']       = "Generated Python project's scripts/generate_protos.py runs cleanly"
dictUsecase['EXPECTATION']       = "scripts/generate_protos.py exits 0 and writes proto/*_pb2*.py"
dictUsecase['SECTION']           = "ScaffoldGenerator_Python"
dictUsecase['SUBSECTION']        = "GOODCASE"
dictUsecase['HINT']              = None
dictUsecase['COMMENT']           = "L3 build check"
dictUsecase['TESTFILE']          = r"MSB_0003.py"
dictUsecase['EXPECTEDEXCEPTION'] = None
dictUsecase['EXPECTEDRETURN']    = "OK: generate_protos.py exit 0; calculator_pb2.py + calculator_pb2_grpc.py present in proto/"
listofdictUsecases.append(dictUsecase)
del dictUsecase
# --------------------------------------------------------------------------------------------------------------
dictUsecase = {}
dictUsecase['TESTID']            = "MSB_0004"
dictUsecase['DESCRIPTION']       = "Generated Python service registers in Consul and answers a gRPC call"
dictUsecase['EXPECTATION']       = "calculator_service appears in Consul catalog (passing); reflection lists Calculator.Add"
dictUsecase['SECTION']           = "ScaffoldGenerator_Python"
dictUsecase['SUBSECTION']        = "GOODCASE"
dictUsecase['HINT']              = "Requires consul on PATH; SKIPPED otherwise"
dictUsecase['COMMENT']           = "L4 runtime check (uses real Consul agent in -dev mode)"
dictUsecase['TESTFILE']          = r"MSB_0004.py"
dictUsecase['EXPECTEDEXCEPTION'] = None
dictUsecase['EXPECTEDRETURN']    = "OK: service registered in Consul; reflection advertises calculator.v1.CalculatorService"
listofdictUsecases.append(dictUsecase)
del dictUsecase
# --------------------------------------------------------------------------------------------------------------
# ==============================================================================
# ScaffoldGenerator — C++ multi_proto
# ==============================================================================
# --------------------------------------------------------------------------------------------------------------
dictUsecase = {}
dictUsecase['TESTID']            = "MSB_0005"
dictUsecase['DESCRIPTION']       = "Generate a C++ multi_proto project (Toolbox=Calculator+Echo) and assert layout"
dictUsecase['EXPECTATION']       = "Per-service .proto + domain + adapter present; CMakeLists / main.cpp / nomad.hcl emitted"
dictUsecase['SECTION']           = "ScaffoldGenerator_Cpp"
dictUsecase['SUBSECTION']        = "GOODCASE"
dictUsecase['HINT']              = None
dictUsecase['COMMENT']           = "L1 static check, multi_proto layout"
dictUsecase['TESTFILE']          = r"MSB_0005.py"
dictUsecase['EXPECTEDEXCEPTION'] = None
dictUsecase['EXPECTEDRETURN']    = "OK: per-service files present for Calculator + Echo; multi_proto markers verified"
listofdictUsecases.append(dictUsecase)
del dictUsecase
# --------------------------------------------------------------------------------------------------------------
dictUsecase = {}
dictUsecase['TESTID']            = "MSB_0006"
dictUsecase['DESCRIPTION']       = "Generate a Python monorepo project (Toolbox = Calculator + Echo) and assert layout"
dictUsecase['EXPECTATION']       = "Per-service src tree + shared toolbox.proto + per-service deploy artefacts emitted"
dictUsecase['SECTION']           = "ScaffoldGenerator_Python"
dictUsecase['SUBSECTION']        = "GOODCASE"
dictUsecase['HINT']              = None
dictUsecase['COMMENT']           = "L1 static check, monorepo layout"
dictUsecase['TESTFILE']          = r"MSB_0006.py"
dictUsecase['EXPECTEDEXCEPTION'] = None
dictUsecase['EXPECTEDRETURN']    = "OK: monorepo emitted per-service src trees, shared proto, per-service deploy"
listofdictUsecases.append(dictUsecase)
del dictUsecase
# --------------------------------------------------------------------------------------------------------------
dictUsecase = {}
dictUsecase['TESTID']            = "MSB_0007"
dictUsecase['DESCRIPTION']       = "Python monorepo compiles + shared .proto compiles"
dictUsecase['EXPECTATION']       = "py_compile clean; protoc emits toolbox_pb2.py + toolbox_pb2_grpc.py"
dictUsecase['SECTION']           = "ScaffoldGenerator_Python"
dictUsecase['SUBSECTION']        = "GOODCASE"
dictUsecase['HINT']              = None
dictUsecase['COMMENT']           = "L2 syntactic check, monorepo layout"
dictUsecase['TESTFILE']          = r"MSB_0007.py"
dictUsecase['EXPECTEDEXCEPTION'] = None
dictUsecase['EXPECTEDRETURN']    = "OK: monorepo .py compiled clean; protoc emitted toolbox_pb2.py + toolbox_pb2_grpc.py"
listofdictUsecases.append(dictUsecase)
del dictUsecase
# --------------------------------------------------------------------------------------------------------------
dictUsecase = {}
dictUsecase['TESTID']            = "MSB_0008"
dictUsecase['DESCRIPTION']       = "Generate a C++ single-service project (Echo) and assert layout"
dictUsecase['EXPECTATION']       = "CMakeLists, main.cpp, EchoService domain + adapter, echo.proto + .nomad.hcl emitted"
dictUsecase['SECTION']           = "ScaffoldGenerator_Cpp"
dictUsecase['SUBSECTION']        = "GOODCASE"
dictUsecase['HINT']              = None
dictUsecase['COMMENT']           = "L1 static check, single-service C++"
dictUsecase['TESTFILE']          = r"MSB_0008.py"
dictUsecase['EXPECTEDEXCEPTION'] = None
dictUsecase['EXPECTEDRETURN']    = "OK: C++ single-service emitted CMake + main.cpp + Echo domain/adapter; markers verified"
listofdictUsecases.append(dictUsecase)
del dictUsecase
# --------------------------------------------------------------------------------------------------------------
# ==============================================================================
# ScaffoldGenerator — BADCASE (unsupported combinations / invalid input)
# ==============================================================================
# --------------------------------------------------------------------------------------------------------------
dictUsecase = {}
dictUsecase['TESTID']            = "MSB_0009"
dictUsecase['DESCRIPTION']       = "Python + multi_proto layout must raise NotImplementedError"
dictUsecase['EXPECTATION']       = "generate_scaffold raises NotImplementedError mentioning python multi_proto"
dictUsecase['SECTION']           = "ScaffoldGenerator_Cpp"   # grouped with cpp because of layout origin
dictUsecase['SUBSECTION']        = "BADCASE"
dictUsecase['HINT']              = None
dictUsecase['COMMENT']           = "Documents that multi_proto is C++-only in this release"
dictUsecase['TESTFILE']          = r"MSB_0009.py"
dictUsecase['EXPECTEDEXCEPTION'] = "multi_proto layout not yet supported for language='python'"
dictUsecase['EXPECTEDRETURN']    = None
listofdictUsecases.append(dictUsecase)
del dictUsecase
# --------------------------------------------------------------------------------------------------------------
dictUsecase = {}
dictUsecase['TESTID']            = "MSB_0010"
dictUsecase['DESCRIPTION']       = "Python monorepo's scripts/generate_protos.py runs cleanly"
dictUsecase['EXPECTATION']       = "exit 0; toolbox_pb2.py + toolbox_pb2_grpc.py written under proto/"
dictUsecase['SECTION']           = "ScaffoldGenerator_Python"
dictUsecase['SUBSECTION']        = "GOODCASE"
dictUsecase['HINT']              = None
dictUsecase['COMMENT']           = "L3 build check, monorepo layout"
dictUsecase['TESTFILE']          = r"MSB_0010.py"
dictUsecase['EXPECTEDEXCEPTION'] = None
dictUsecase['EXPECTEDRETURN']    = "OK: monorepo generate_protos.py exit 0; toolbox_pb2.py + toolbox_pb2_grpc.py present"
listofdictUsecases.append(dictUsecase)
del dictUsecase
# --------------------------------------------------------------------------------------------------------------
dictUsecase = {}
dictUsecase['TESTID']            = "MSB_0011"
dictUsecase['DESCRIPTION']       = "Python monorepo Calculator service registers in Consul + reflection works"
dictUsecase['EXPECTATION']       = "Service appears in Consul (passing); reflection lists calculator.v1.CalculatorService"
dictUsecase['SECTION']           = "ScaffoldGenerator_Python"
dictUsecase['SUBSECTION']        = "GOODCASE"
dictUsecase['HINT']              = "Requires consul on PATH; SKIPPED otherwise"
dictUsecase['COMMENT']           = "L4 runtime check, monorepo layout"
dictUsecase['TESTFILE']          = r"MSB_0011.py"
dictUsecase['EXPECTEDEXCEPTION'] = None
dictUsecase['EXPECTEDRETURN']    = "OK: monorepo Calculator service registered + reflection advertises toolbox.v1.Calculator"
listofdictUsecases.append(dictUsecase)
del dictUsecase
# --------------------------------------------------------------------------------------------------------------
dictUsecase = {}
dictUsecase['TESTID']            = "MSB_0012"
dictUsecase['DESCRIPTION']       = "C++ single-service .proto parses cleanly through protoc"
dictUsecase['EXPECTATION']       = "echo.proto compiles to a FileDescriptorSet without errors"
dictUsecase['SECTION']           = "ScaffoldGenerator_Cpp"
dictUsecase['SUBSECTION']        = "GOODCASE"
dictUsecase['HINT']              = None
dictUsecase['COMMENT']           = "L2 syntactic check, single-service C++"
dictUsecase['TESTFILE']          = r"MSB_0012.py"
dictUsecase['EXPECTEDEXCEPTION'] = None
dictUsecase['EXPECTEDRETURN']    = "OK: C++ single-service echo.proto parses cleanly"
listofdictUsecases.append(dictUsecase)
del dictUsecase
# --------------------------------------------------------------------------------------------------------------
dictUsecase = {}
dictUsecase['TESTID']            = "MSB_0013"
dictUsecase['DESCRIPTION']       = "C++ multi_proto: every per-service .proto parses cleanly"
dictUsecase['EXPECTATION']       = "calculator.proto and echo.proto each compile independently"
dictUsecase['SECTION']           = "ScaffoldGenerator_Cpp"
dictUsecase['SUBSECTION']        = "GOODCASE"
dictUsecase['HINT']              = None
dictUsecase['COMMENT']           = "L2 syntactic check, multi_proto layout"
dictUsecase['TESTFILE']          = r"MSB_0013.py"
dictUsecase['EXPECTEDEXCEPTION'] = None
dictUsecase['EXPECTEDRETURN']    = "OK: multi_proto calculator.proto and echo.proto both parse cleanly"
listofdictUsecases.append(dictUsecase)
del dictUsecase
# --------------------------------------------------------------------------------------------------------------
dictUsecase = {}
dictUsecase['TESTID']            = "MSB_0014"
dictUsecase['DESCRIPTION']       = "Generate a C++ monorepo project (Toolbox = Calculator + Echo) and assert layout"
dictUsecase['EXPECTATION']       = "Per-service src tree + shared toolbox.proto + per-service deploy artefacts emitted"
dictUsecase['SECTION']           = "ScaffoldGenerator_Cpp"
dictUsecase['SUBSECTION']        = "GOODCASE"
dictUsecase['HINT']              = None
dictUsecase['COMMENT']           = "L1 static check, C++ monorepo"
dictUsecase['TESTFILE']          = r"MSB_0014.py"
dictUsecase['EXPECTEDEXCEPTION'] = None
dictUsecase['EXPECTEDRETURN']    = "OK: C++ monorepo emitted per-service src trees, shared proto, per-service deploy"
listofdictUsecases.append(dictUsecase)
del dictUsecase
# --------------------------------------------------------------------------------------------------------------
dictUsecase = {}
dictUsecase['TESTID']            = "MSB_0015"
dictUsecase['DESCRIPTION']       = "C++ monorepo shared toolbox.proto parses cleanly"
dictUsecase['EXPECTATION']       = "Single shared .proto declaring multiple services compiles"
dictUsecase['SECTION']           = "ScaffoldGenerator_Cpp"
dictUsecase['SUBSECTION']        = "GOODCASE"
dictUsecase['HINT']              = None
dictUsecase['COMMENT']           = "L2 syntactic check, C++ monorepo"
dictUsecase['TESTFILE']          = r"MSB_0015.py"
dictUsecase['EXPECTEDEXCEPTION'] = None
dictUsecase['EXPECTEDRETURN']    = "OK: C++ monorepo toolbox.proto parses cleanly (both services in one file)"
listofdictUsecases.append(dictUsecase)
del dictUsecase
# --------------------------------------------------------------------------------------------------------------
dictUsecase = {}
dictUsecase['TESTID']            = "MSB_0016"
dictUsecase['DESCRIPTION']       = "C++ single-service CMake configure step succeeds"
dictUsecase['EXPECTATION']       = "cmake -S . -B build_test exits 0 (or skips when cmake/gRPC absent)"
dictUsecase['SECTION']           = "ScaffoldGenerator_Cpp"
dictUsecase['SUBSECTION']        = "GOODCASE"
dictUsecase['HINT']              = "Skips when cmake or system gRPC is unavailable"
dictUsecase['COMMENT']           = "L3 build check, C++ single-service"
dictUsecase['TESTFILE']          = r"MSB_0016.py"
dictUsecase['EXPECTEDEXCEPTION'] = None
dictUsecase['EXPECTEDRETURN']    = "OK: cmake configure exit 0 for C++ single-service"
listofdictUsecases.append(dictUsecase)
del dictUsecase
# --------------------------------------------------------------------------------------------------------------
# ==============================================================================
# ScaffoldGenerator — full E2E (Nomad + Consul + service)
# ==============================================================================
# --------------------------------------------------------------------------------------------------------------
dictUsecase = {}
dictUsecase['TESTID']            = "MSB_0017"
dictUsecase['DESCRIPTION']       = "Submit generated calculator.nomad.hcl to Nomad; service registers + answers reflection"
dictUsecase['EXPECTATION']       = "Nomad allocation runs; service registers via Consul; reflection lists CalculatorService"
dictUsecase['SECTION']           = "ScaffoldGenerator_E2E"
dictUsecase['SUBSECTION']        = "GOODCASE"
dictUsecase['HINT']              = "Requires both consul AND nomad on PATH; SKIPPED otherwise"
dictUsecase['COMMENT']           = "L5 end-to-end check"
dictUsecase['TESTFILE']          = r"MSB_0017.py"
dictUsecase['EXPECTEDEXCEPTION'] = None
dictUsecase['EXPECTEDRETURN']    = "OK: Nomad job ran calculator; service registered via Consul; reflection advertises calculator.v1.CalculatorService"
listofdictUsecases.append(dictUsecase)
del dictUsecase
# --------------------------------------------------------------------------------------------------------------
dictUsecase = {}
dictUsecase['TESTID']            = "MSB_0018"
dictUsecase['DESCRIPTION']       = "Empty service_name produces malformed file paths (no input validation)"
dictUsecase['EXPECTATION']       = "Generator currently accepts empty input and emits leading-dot paths"
dictUsecase['SECTION']           = "ScaffoldGenerator_Python"
dictUsecase['SUBSECTION']        = "BADCASE"
dictUsecase['HINT']              = "Documents missing input validation; remove if generator gains a ValueError"
dictUsecase['COMMENT']           = "Generator-side bug — open follow-up to add input validation"
dictUsecase['TESTFILE']          = r"MSB_0018.py"
dictUsecase['EXPECTEDEXCEPTION'] = None
dictUsecase['EXPECTEDRETURN']    = "OK: empty service_name produces malformed paths and an empty proto package — generator-side bug documented"
listofdictUsecases.append(dictUsecase)
del dictUsecase
# --------------------------------------------------------------------------------------------------------------
dictUsecase = {}
dictUsecase['TESTID']            = "MSB_0019"
dictUsecase['DESCRIPTION']       = "C++ multi_proto + Qt6::Grpc client emits qt_client/ with multi-proto-aware CMakeLists + MainWindow.cpp + WASM scripts"
dictUsecase['EXPECTATION']       = "qt_client/ folder is generated with PROTO_FILES listing all .proto files, MainWindow.cpp with N include pairs + per-service namespace dispatch, and build_wasm + serve_wasm helpers"
dictUsecase['SECTION']           = "ScaffoldGenerator_Cpp"
dictUsecase['SUBSECTION']        = "GOODCASE"
dictUsecase['HINT']              = "L1 static check — no compiler needed"
dictUsecase['COMMENT']           = "Regression guard for multi_proto + client_grpc_kind=qt wiring (previously the qt branch was missing from generate_multi_proto)"
dictUsecase['TESTFILE']          = r"MSB_0019.py"
dictUsecase['EXPECTEDEXCEPTION'] = None
dictUsecase['EXPECTEDRETURN']    = "OK: qt_client/ emitted 19 files; multi-proto CMakeLists + N include pairs + per-service namespaces + WASM scripts verified"
listofdictUsecases.append(dictUsecase)
del dictUsecase
# --------------------------------------------------------------------------------------------------------------
dictUsecase = {}
dictUsecase['TESTID']            = "MSB_0020"
dictUsecase['DESCRIPTION']       = "LocalProtoClient._is_excluded prunes build / vcpkg_installed / vendor dirs"
dictUsecase['EXPECTATION']       = "Recursive .proto glob keeps real service protos, excludes vcpkg_installed/google/protobuf duplicates + build-*/build_/_legacy/node_modules/.git/__pycache__ artefacts"
dictUsecase['SECTION']           = "ScaffoldGenerator_Cpp"
dictUsecase['SUBSECTION']        = "GOODCASE"
dictUsecase['HINT']              = "L1 unit check — no compiler / network needed"
dictUsecase['COMMENT']           = "Regression guard for GUI 'no reflection + provide a .proto folder' flow (previously protoc exited 1 because duplicated google.protobuf.* schemas from multiple build dirs were globbed in)"
dictUsecase['TESTFILE']          = r"MSB_0020.py"
dictUsecase['EXPECTEDEXCEPTION'] = None
dictUsecase['EXPECTEDRETURN']    = "OK: _is_excluded correctly kept 4 real-proto paths and excluded 11 build/vendor paths"
listofdictUsecases.append(dictUsecase)
del dictUsecase
# --------------------------------------------------------------------------------------------------------------
dictUsecase = {}
dictUsecase['TESTID']            = "MSB_0021"
dictUsecase['DESCRIPTION']       = "robot_tmpl emits one .resource per service with prefixed keywords + conn_name-first args + no collisions on Connect/underscore RPC names"
dictUsecase['EXPECTATION']       = "Per-service .resource with QConnectBase Library import, Open/Close Connection helpers (renamed to avoid colliding with proto-defined Connect()/Disconnect() RPCs), prefixed keyword names ('<Service> <Method>'), ${conn_name} as first positional arg, no-arg RPCs skip the args-dict scaffolding, and single-space-only keyword headers (regression: underscore + camelCase used to produce double-space names that Robot's parser truncates)"
dictUsecase['SECTION']           = "ScaffoldGenerator_Cpp"
dictUsecase['SUBSECTION']        = "GOODCASE"
dictUsecase['HINT']              = "L1 unit check — uses grpc_tools to compile a synthetic .proto with `Connect` and `Get_SubItem_ID` methods that trigger both regressions, then asserts the emitted Robot resource shape"
dictUsecase['COMMENT']           = "Locks in the Robot resource generator (see MicroserviceBase/adapters/scaffold/robot_tmpl.py + MicroserviceBase/tools/robot_gen.py). Two regressions guarded: (1) Connect/Disconnect helpers colliding with same-named RPCs; (2) GetThing_NestedName producing 'Get Thing  Nested Name' (double space) which Robot truncates"
dictUsecase['TESTFILE']          = r"MSB_0021.py"
dictUsecase['EXPECTEDEXCEPTION'] = None
dictUsecase['EXPECTEDRETURN']    = "OK: 2 resources emitted; Calculator has 6 keywords, Echo has 3 keywords; prefixed names + conn_name-first + Open/Close Connection helpers + no Connect/underscore collisions verified"
listofdictUsecases.append(dictUsecase)
del dictUsecase
# --------------------------------------------------------------------------------------------------------------
