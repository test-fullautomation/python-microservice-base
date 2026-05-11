# **************************************************************************************************************
#  Copyright 2020-2026 Robert Bosch GmbH
#  See MSB_0001.py for license header.
# **************************************************************************************************************
#
# MSB_0011.py — L4 runtime: spawn one service from a Python monorepo against
# a real consul -dev agent and confirm it registers + reflects.

import os, subprocess, sys, shutil, time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from testutils.scaffold_helpers import make_method, make_service, make_spec, write_scaffold
from testutils.build_helpers    import run_generate_protos_script
from testutils.infra_helpers    import (
    skip_if_no_consul, spawn_consul_dev, stop_agent,
    free_port, wait_for_port, consul_health_passing,
)
from testutils.grpc_helpers     import grpc_libs_available, list_services_via_reflection


def test():
    skip = skip_if_no_consul()
    if skip:
        return skip
    if not grpc_libs_available():
        return "SKIPPED: grpcio + grpcio-reflection not installed"

    services = [
        make_service("Calculator", [make_method("Add", "int32", [("a", "int32"), ("b", "int32")])]),
        make_service("Echo",       [make_method("Say", "string", [("text", "string")])]),
    ]
    spec = make_spec("Toolbox", language="python", layout="monorepo", services=services)

    out_dir, _files = write_scaffold(spec)
    consul = None
    svc_proc = None
    svc_log = None
    try:
        consul = spawn_consul_dev()

        # Build the shared proto stubs once (sit at proto/toolbox_pb2*.py)
        code, _ = run_generate_protos_script(out_dir)
        if code != 0:
            return f"FAIL: generate_protos.py exit {code} during L4 setup"

        # Spawn the Calculator service from src/toolbox/calculator/main.py
        grpc_port = free_port()
        env = os.environ.copy()
        env["CALCULATOR_SERVICE_NAME"]      = "calculator_service"
        env["CALCULATOR_GRPC_PORT"]         = str(grpc_port)
        env["CALCULATOR_ADVERTISE_ADDR"]    = "127.0.0.1"
        env["CALCULATOR_CONSUL_ADDR"]       = consul["url"]
        env["CALCULATOR_LOG_LEVEL"]         = "WARNING"
        # The monorepo main.py imports via `from toolbox.calculator.context import...`
        # so the project root must be on PYTHONPATH (it adds itself to sys.path
        # but PYTHONPATH is the cleaner contract).
        env["PYTHONPATH"] = os.path.join(out_dir, "src") + os.pathsep + env.get("PYTHONPATH", "")

        svc_main = os.path.join(out_dir, "src", "toolbox", "calculator", "main.py")
        svc_log_path = os.path.join(out_dir, ".service.log")
        svc_log = open(svc_log_path, "w", encoding="utf-8")
        svc_proc = subprocess.Popen(
            [sys.executable, svc_main],
            cwd=out_dir,
            env=env,
            stdout=svc_log,
            stderr=subprocess.STDOUT,
        )

        wait_for_port("127.0.0.1", grpc_port, timeout=20.0)
        deadline = time.monotonic() + 15.0
        registered = []
        while time.monotonic() < deadline:
            registered = consul_health_passing(consul["url"], "calculator_service")
            if registered:
                break
            time.sleep(0.5)
        if not registered:
            with open(svc_log_path, encoding="utf-8", errors="replace") as fh:
                tail = fh.read()[-400:]
            return f"FAIL: monorepo calculator_service not in Consul after 15s; service log tail: {tail!r}"

        services_advertised = list_services_via_reflection(f"127.0.0.1:{grpc_port}")
        # Monorepo packages services under the *project* name (toolbox.v1)
        # not the service name, and uses the bare service name (Calculator)
        # without the "Service" suffix that single-service mode adds.
        target_fqn = "toolbox.v1.Calculator"
        if target_fqn not in services_advertised:
            return f"FAIL: reflection did not list {target_fqn}; got {services_advertised}"

        return "OK: monorepo Calculator service registered + reflection advertises toolbox.v1.Calculator"

    finally:
        if svc_proc is not None and svc_proc.poll() is None:
            try:
                svc_proc.terminate()
                svc_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                svc_proc.kill()
                svc_proc.wait(timeout=2)
        if svc_log is not None:
            try:
                svc_log.close()
            except Exception:
                pass
        stop_agent(consul)
        shutil.rmtree(out_dir, ignore_errors=True)
