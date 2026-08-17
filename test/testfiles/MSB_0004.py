# **************************************************************************************************************
#  Copyright 2020-2026 Robert Bosch GmbH
#  See MSB_0001.py for license header.
# **************************************************************************************************************
#
# MSB_0004.py — L4 runtime: spawn the generated service against a real
# `consul agent -dev`, wait for registration, verify reflection.
#
# Skips cleanly when consul isn't on PATH so the rest of the suite still
# passes on developer machines without HashiCorp tools installed.

import os, subprocess, sys, shutil, time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from testutils.scaffold_helpers import make_method, make_spec, write_scaffold
from testutils.build_helpers    import run_generate_protos_script
from testutils.infra_helpers    import (
    skip_if_no_consul,
    spawn_consul_dev,
    stop_agent,
    free_port,
    wait_for_port,
    consul_health_passing,
)
from testutils.grpc_helpers     import grpc_libs_available, list_services_via_reflection


def test():
    skip = skip_if_no_consul()
    if skip:
        return skip
    if not grpc_libs_available():
        return "SKIPPED: grpcio + grpcio-reflection not installed"

    spec = make_spec(
        service_name="Calculator",
        language="python",
        layout="single",
        methods=[
            make_method("Add",      return_type="int32", params=[("a", "int32"), ("b", "int32")]),
            make_method("Multiply", return_type="int32", params=[("a", "int32"), ("b", "int32")]),
        ],
    )

    out_dir, _files = write_scaffold(spec)
    consul = None
    svc_proc = None
    svc_log = None
    try:
        # 1. consul agent -dev on a free port
        consul = spawn_consul_dev()

        # 2. compile the generated stubs in-place
        code, _ = run_generate_protos_script(out_dir)
        if code != 0:
            return f"FAIL: generate_protos.py exit {code} during L4 setup"

        # 3. spawn the service, pointing it at our consul agent
        grpc_port = free_port()
        env = os.environ.copy()
        env["CALCULATOR_SERVICE_NAME"]      = "calculator_service"
        env["CALCULATOR_GRPC_PORT"]         = str(grpc_port)
        env["CALCULATOR_ADVERTISE_ADDR"]    = "127.0.0.1"
        env["CALCULATOR_CONSUL_ADDR"]       = consul["url"]
        env["CALCULATOR_LOG_LEVEL"]         = "WARNING"

        svc_log_path = os.path.join(out_dir, ".service.log")
        svc_log = open(svc_log_path, "w", encoding="utf-8")
        svc_proc = subprocess.Popen(
            [sys.executable, "main.py"],
            cwd=out_dir,
            env=env,
            stdout=svc_log,
            stderr=subprocess.STDOUT,
        )

        # 4. wait for the service's gRPC port + Consul registration
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
            return f"FAIL: calculator_service not in Consul (passing) after 15s; service log tail: {tail!r}"

        # 5. reflection: confirm the service FQN is advertised
        services = list_services_via_reflection(f"127.0.0.1:{grpc_port}")
        target_fqn = "calculator.v1.CalculatorService"
        if target_fqn not in services:
            return f"FAIL: reflection did not list {target_fqn}; got {services}"

        return "OK: service registered in Consul; reflection advertises calculator.v1.CalculatorService"

    finally:
        # tear down service, then consul, then temp dir
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
