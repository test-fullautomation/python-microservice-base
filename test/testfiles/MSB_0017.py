# **************************************************************************************************************
#  Copyright 2020-2026 Robert Bosch GmbH
#  See MSB_0001.py for license header.
# **************************************************************************************************************
#
# MSB_0017.py — L5 e2e: submit the generated calculator.nomad.hcl to a real
# nomad -dev agent, wait for the allocation to register the service in
# Consul, and confirm the service is reachable via reflection.
#
# Skips when consul OR nomad is unavailable.

import json, os, re, shutil, subprocess, sys, time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from testutils.scaffold_helpers import make_method, make_spec, write_scaffold
from testutils.build_helpers    import run_generate_protos_script
from testutils.infra_helpers    import (
    skip_if_no_consul, skip_if_no_nomad,
    spawn_consul_dev, spawn_nomad_dev, stop_agent,
    free_port, find_binary, consul_health_passing,
)
from testutils.grpc_helpers     import grpc_libs_available, list_services_via_reflection


def _patch_nomad_hcl(path, project_root, python_exe, consul_url):
    """Edit the generated .nomad.hcl in-place so its ``command`` /
    ``args`` / ``env`` point at this project on this machine instead
    of the placeholder paths the scaffold writes.
    """
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    # The generator writes:
    #   command = "python"
    #   args    = ["/path/to/calculator/main.py"]
    #   PYTHONPATH = "/path/to/calculator"
    #   CALCULATOR_CONSUL_ADDR = "http://127.0.0.1:8500"
    text = re.sub(
        r'command\s*=\s*"python"',
        f'command = "{python_exe.replace(chr(92), "/")}"',
        text,
    )
    text = re.sub(
        r'args\s*=\s*\["/path/to/calculator/main\.py"\]',
        f'args = ["{os.path.join(project_root, "main.py").replace(chr(92), "/")}"]',
        text,
    )
    text = re.sub(
        r'PYTHONPATH\s*=\s*"/path/to/calculator"',
        f'PYTHONPATH = "{project_root.replace(chr(92), "/")}"',
        text,
    )
    text = re.sub(
        r'CALCULATOR_CONSUL_ADDR\s*=\s*"http://127\.0\.0\.1:8500"',
        f'CALCULATOR_CONSUL_ADDR = "{consul_url}"',
        text,
    )
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def test():
    skip = skip_if_no_consul() or skip_if_no_nomad()
    if skip:
        return skip
    if not grpc_libs_available():
        return "SKIPPED: grpcio + grpcio-reflection not installed"

    spec = make_spec(
        service_name="Calculator",
        language="python",
        layout="single",
        methods=[make_method("Add", "int32", [("a", "int32"), ("b", "int32")])],
    )

    out_dir, _files = write_scaffold(spec)
    consul = None
    nomad  = None
    job_id = "calculator"
    nomad_bin = find_binary("nomad")
    try:
        consul = spawn_consul_dev()
        # Nomad -dev integrates with Consul on its own when CONSUL_HTTP_ADDR is set
        env_for_nomad = os.environ.copy()
        env_for_nomad["CONSUL_HTTP_ADDR"] = consul["url"].replace("http://", "")
        nomad_log = os.path.join(out_dir, ".nomad.log")
        # Use the same spawn helper but inherit the CONSUL env we set above —
        # spawn_nomad_dev passes through subprocess.Popen's env=None which
        # inherits the current process env.  We exported CONSUL_HTTP_ADDR
        # in env_for_nomad; promote it into our own env so Nomad sees it.
        os.environ["CONSUL_HTTP_ADDR"] = env_for_nomad["CONSUL_HTTP_ADDR"]
        nomad = spawn_nomad_dev(log_path=nomad_log)

        # Compile proto stubs in-place
        code, _ = run_generate_protos_script(out_dir)
        if code != 0:
            return f"FAIL: generate_protos.py exit {code} during L5 setup"

        # Patch the generated .nomad.hcl to point at this project + python
        hcl_path = os.path.join(out_dir, "calculator.nomad.hcl")
        _patch_nomad_hcl(hcl_path, out_dir, sys.executable, consul["url"])

        # Submit the job (stream stdout to a log)
        sub_log = os.path.join(out_dir, ".nomad_run.log")
        with open(sub_log, "w", encoding="utf-8") as logfh:
            sub = subprocess.run(
                [nomad_bin, "job", "run", "-address", nomad["url"], hcl_path],
                stdout=logfh,
                stderr=subprocess.STDOUT,
                timeout=60,
            )
        if sub.returncode != 0:
            with open(sub_log, encoding="utf-8", errors="replace") as fh:
                tail = fh.read()[-500:]
            return f"FAIL: `nomad job run` exit {sub.returncode}; log tail: {tail!r}"

        # Wait for the service to register in Consul
        deadline = time.monotonic() + 30.0
        registered = []
        while time.monotonic() < deadline:
            try:
                registered = consul_health_passing(consul["url"], "calculator")
                if registered:
                    break
            except Exception:
                pass
            time.sleep(0.7)
        if not registered:
            # Diagnostics
            diag = []
            try:
                # Patched HCL so we can see what env vars Nomad actually saw
                with open(hcl_path, encoding="utf-8") as fh:
                    diag.append(f"patched HCL env block:")
                    in_env = False
                    for ln in fh.read().splitlines():
                        if "env {" in ln:
                            in_env = True
                        if in_env:
                            diag.append("  " + ln)
                        if in_env and ln.strip() == "}":
                            break
            except Exception as ex:
                diag.append(f"hcl dump failed: {ex}")
            try:
                # Find the running allocation ID
                allocs = subprocess.run(
                    [nomad_bin, "job", "allocs", "-address", nomad["url"], "-json", job_id],
                    timeout=10, capture_output=True, text=True,
                )
                import json as _j
                alloc_list = _j.loads(allocs.stdout) if allocs.stdout.strip() else []
                if alloc_list:
                    alloc_id = alloc_list[0].get("ID", "")
                    diag.append(f"alloc_id={alloc_id}, ClientStatus={alloc_list[0].get('ClientStatus')}")
                    # Capture stdout + stderr
                    for stream in ("stdout", "stderr"):
                        log = subprocess.run(
                            [nomad_bin, "alloc", "logs", "-address", nomad["url"], f"-{stream}", alloc_id, "server"],
                            timeout=5, capture_output=True, text=True,
                        )
                        diag.append(f"alloc {stream} (last 500): {log.stdout[-500:]}")
                else:
                    diag.append("no allocs found")
            except Exception as ex:
                diag.append(f"alloc inspection failed: {ex}")
            return f"FAIL: calculator_service not in Consul within 30s. Diag:\n" + "\n---\n".join(diag)

        # Reflect at the registered host:port
        node = registered[0]
        host = node["Service"]["Address"] or "127.0.0.1"
        port = node["Service"]["Port"]
        services = list_services_via_reflection(f"{host}:{port}")
        target_fqn = "calculator.v1.CalculatorService"
        if target_fqn not in services:
            return f"FAIL: reflection at {host}:{port} did not list {target_fqn}; got {services}"

        return "OK: Nomad job ran calculator; service registered via Consul; reflection advertises calculator.v1.CalculatorService"

    finally:
        # Always try to stop the job before tearing down agents
        if nomad is not None and nomad_bin:
            try:
                subprocess.run(
                    [nomad_bin, "job", "stop", "-purge", "-address", nomad["url"], job_id],
                    timeout=15,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass
        stop_agent(nomad)
        stop_agent(consul)
        os.environ.pop("CONSUL_HTTP_ADDR", None)
        shutil.rmtree(out_dir, ignore_errors=True)
