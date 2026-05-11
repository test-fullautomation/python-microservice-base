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
# infra_helpers.py
#
# Helpers for the L4 / L5 test cases that exercise the runtime stack.
# Detect whether ``consul`` and ``nomad`` are on PATH; spawn a dev-mode
# agent in the background; tear it down on shutdown.  Tests that need
# infra and find it missing should return ``"SKIPPED: <reason>"`` so the
# orchestrator marks them skipped rather than failed.
#
# 10.05.2026
#
# --------------------------------------------------------------------------------------------------------------

import atexit
import errno
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


# --------------------------------------------------------------------------------------------------------------
# Binary discovery
# --------------------------------------------------------------------------------------------------------------

def find_binary(name):
    """Locate a binary by name in a cross-platform way.  Tries
    ``shutil.which`` first; if that fails, falls back to a short list of
    well-known install locations so a freshly-installed Consul / Nomad is
    usable without restarting the shell to pick up updated PATH.

    Returns the absolute path on success, or ``None`` if not found.
    """
    found = shutil.which(name)
    if found:
        return found

    candidates = []
    if sys.platform.startswith("win"):
        local_appdata = os.environ.get("LOCALAPPDATA", "")
        program_files = os.environ.get("ProgramFiles", "C:\\Program Files")
        exe = name + ".exe"
        candidates += [
            os.path.join(local_appdata, "Microsoft", "WinGet", "Links", exe),
            os.path.join(program_files, "HashiCorp", name.capitalize(), exe),
            os.path.join("C:\\HashiCorp", name.capitalize(), exe),
            os.path.join("C:\\ProgramData", "chocolatey", "bin", exe),
        ]
    else:
        # Linux + macOS: HashiCorp's apt/yum repos drop binaries in /usr/bin;
        # release-tarball installs typically land in /usr/local/bin or
        # ~/.local/bin; some teams /opt/hashicorp/bin them.
        home = os.environ.get("HOME", "")
        candidates += [
            os.path.join("/usr/local/bin", name),
            os.path.join("/usr/bin", name),
            os.path.join("/opt/hashicorp/bin", name),
        ]
        if home:
            candidates.append(os.path.join(home, ".local", "bin", name))

    for cand in candidates:
        if os.path.isfile(cand):
            return cand
    return None


# --------------------------------------------------------------------------------------------------------------
# Availability checks
# --------------------------------------------------------------------------------------------------------------

def consul_available():
    """True if a ``consul`` binary is reachable (PATH or known install path)."""
    return find_binary("consul") is not None


def nomad_available():
    """True if a ``nomad`` binary is reachable (PATH or known install path)."""
    return find_binary("nomad") is not None


def _install_hint(name):
    """OS-aware install hint used in SKIPPED messages."""
    if sys.platform.startswith("win"):
        return "winget install Hashicorp." + name.capitalize()
    if sys.platform == "darwin":
        return "brew tap hashicorp/tap && brew install hashicorp/tap/" + name
    # Linux / other: official HashiCorp apt repo is the canonical path.
    return ("install via HashiCorp's apt/yum repos — see "
            "https://developer.hashicorp.com/" + name + "/install")


def skip_if_no_consul():
    """Return a SKIPPED string when consul is not on PATH, else None.

    Pattern in a testfile:

        skip = skip_if_no_consul()
        if skip:
            return skip
    """
    if not consul_available():
        return "SKIPPED: consul agent not found (try `" + _install_hint("consul") + "`)"
    return None


def skip_if_no_nomad():
    if not nomad_available():
        return "SKIPPED: nomad agent not found (try `" + _install_hint("nomad") + "`)"
    return None


# --------------------------------------------------------------------------------------------------------------
# Free port allocation
# --------------------------------------------------------------------------------------------------------------

def free_port():
    """Ask the OS for a free TCP port (race-prone but good enough for
    test-fixture spin-up; we hand the port straight to the agent which
    grabs it within milliseconds).
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_for_port(host, port, timeout=15.0, interval=0.2):
    """Block until a TCP connect to host:port succeeds, or raise after timeout."""
    deadline = time.monotonic() + timeout
    last_err = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=interval):
                return True
        except (OSError, ConnectionRefusedError) as ex:
            last_err = ex
            time.sleep(interval)
    raise TimeoutError(f"port {host}:{port} not reachable after {timeout:.1f}s (last error: {last_err})")


def wait_for_http(url, timeout=15.0, interval=0.3, expected_status=(200, 204)):
    """Poll an HTTP URL until it returns one of ``expected_status``."""
    deadline = time.monotonic() + timeout
    last_err = None
    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=interval) as resp:
                if resp.status in expected_status:
                    return True
                last_err = f"HTTP {resp.status}"
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as ex:
            last_err = ex
        time.sleep(interval)
    raise TimeoutError(f"GET {url} not OK after {timeout:.1f}s (last error: {last_err})")


# --------------------------------------------------------------------------------------------------------------
# Agent spawning + cleanup
# --------------------------------------------------------------------------------------------------------------

# Track every spawned process so atexit can reap leftover agents even
# when a test crashes mid-flight.
_active = []


def _popen_kwargs_new_session():
    """Cross-platform Popen kwargs to put the spawned process in its own
    session/process group so we can kill the whole tree (the agent +
    every raw_exec task it launched) in one shot on teardown.
    """
    if sys.platform.startswith("win"):
        # CREATE_NEW_PROCESS_GROUP lets us send CTRL_BREAK_EVENT to the
        # group and ensures grandchild raw_exec processes are also in the
        # group (so taskkill /T can find them).
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _terminate(proc, name=""):
    """Kill ``proc`` and any descendants it spawned.  On Windows uses
    taskkill /T /F (works without psutil); on POSIX uses
    os.killpg(SIGTERM) → SIGKILL.
    """
    if proc is None or proc.poll() is not None:
        return
    if sys.platform.startswith("win"):
        try:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
        return

    # POSIX: kill the whole process group we created with start_new_session=True.
    import signal as _signal
    try:
        pgid = os.getpgid(proc.pid)
        os.killpg(pgid, _signal.SIGTERM)
        try:
            proc.wait(timeout=5)
            return
        except subprocess.TimeoutExpired:
            os.killpg(pgid, _signal.SIGKILL)
            try:
                proc.wait(timeout=2)
            except Exception:
                pass
    except ProcessLookupError:
        pass
    except Exception:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


@atexit.register
def _cleanup_active_agents():
    for proc, name in _active:
        _terminate(proc, name)


def spawn_consul_dev(http_port=None, log_path=None):
    """Spawn ``consul agent -dev`` on a free HTTP port and wait until it
    serves ``/v1/status/leader``.

    Returns a dict ``{"proc", "http_port", "url", "data_dir"}``.  Caller
    should ``stop_agent(returned_dict)`` when done; otherwise ``atexit``
    will reap the process.
    """
    consul_bin = find_binary("consul")
    if consul_bin is None:
        raise RuntimeError("consul not on PATH or in a known install location")

    port = http_port or free_port()
    url  = f"http://127.0.0.1:{port}"
    data_dir = os.path.join(tempfile.gettempdir(), f"consul_test_{port}")
    os.makedirs(data_dir, exist_ok=True)

    log_handle = open(log_path, "w", encoding="utf-8") if log_path else subprocess.DEVNULL

    # Disable every port we don't actually use so our test agent can
    # coexist with another consul (e.g. one already bound to defaults
    # 8500 / 8600 / 8300 / 8301 / 8302 by a dev workstation).  HTTP is
    # the only port the framework's helpers + tests touch.
    cmd = [
        consul_bin, "agent", "-dev",
        "-http-port", str(port),
        "-grpc-port", "-1",
        "-grpc-tls-port", "-1",
        "-dns-port", "-1",
        "-server-port", str(free_port()),
        "-serf-lan-port", str(free_port()),
        "-serf-wan-port", "-1",
        "-data-dir", data_dir,
        "-disable-host-node-id",
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=log_handle,
        stderr=subprocess.STDOUT if log_handle is not subprocess.DEVNULL else subprocess.DEVNULL,
        shell=False,
        **_popen_kwargs_new_session(),
    )
    _active.append((proc, "consul"))

    try:
        wait_for_http(f"{url}/v1/status/leader", timeout=20.0)
    except TimeoutError:
        _terminate(proc, "consul")
        raise

    return {
        "proc": proc,
        "http_port": port,
        "url": url,
        "data_dir": data_dir,
        "log_path": log_path,
    }


def spawn_nomad_dev(http_port=None, log_path=None):
    """Spawn ``nomad agent -dev`` on a free HTTP port and wait until it
    serves ``/v1/status/leader``.
    """
    nomad_bin = find_binary("nomad")
    if nomad_bin is None:
        raise RuntimeError("nomad not on PATH or in a known install location")

    port = http_port or free_port()
    url  = f"http://127.0.0.1:{port}"
    data_dir = os.path.join(tempfile.gettempdir(), f"nomad_test_{port}")
    os.makedirs(data_dir, exist_ok=True)

    log_handle = open(log_path, "w", encoding="utf-8") if log_path else subprocess.DEVNULL

    cmd = [
        nomad_bin, "agent", "-dev",
        "-bind", "127.0.0.1",
        "-data-dir", data_dir,
    ]
    # Nomad doesn't expose a CLI flag for the HTTP port directly in -dev
    # mode; the only honoured override is via a config file or HTTP_ADDR
    # env.  Always write a tiny agent.hcl so each test gets its own ports
    # for HTTP/RPC/Serf and doesn't collide with the defaults
    # 4646/4647/4648 (which the user's dev nomad may already be bound to).
    rpc_port = free_port()
    serf_port = free_port()
    cfg_path = os.path.join(data_dir, "agent.hcl")
    with open(cfg_path, "w", encoding="utf-8") as fh:
        fh.write(
            'addresses {{ http = "127.0.0.1" }}\n'
            'ports {{ http = {http} rpc = {rpc} serf = {serf} }}\n'
            .format(http=port, rpc=rpc_port, serf=serf_port)
        )
    cmd += ["-config", cfg_path]

    proc = subprocess.Popen(
        cmd,
        stdout=log_handle,
        stderr=subprocess.STDOUT if log_handle is not subprocess.DEVNULL else subprocess.DEVNULL,
        shell=False,
        **_popen_kwargs_new_session(),
    )
    _active.append((proc, "nomad"))

    try:
        wait_for_http(f"{url}/v1/status/leader", timeout=30.0)
    except TimeoutError:
        _terminate(proc, "nomad")
        raise

    return {
        "proc": proc,
        "http_port": port,
        "url": url,
        "data_dir": data_dir,
        "log_path": log_path,
    }


def stop_agent(agent):
    """Terminate a previously-spawned consul / nomad dict.

    Idempotent: safe to call from a finally block even if ``spawn_*`` failed.
    """
    if not agent:
        return
    proc = agent.get("proc")
    if proc is not None:
        _terminate(proc, "agent")


# --------------------------------------------------------------------------------------------------------------
# Consul HTTP helpers (small, no python-consul dep)
# --------------------------------------------------------------------------------------------------------------

def consul_list_services(consul_url):
    """GET /v1/catalog/services -> dict of service_name -> [tags...]."""
    import json as _json
    with urllib.request.urlopen(f"{consul_url}/v1/catalog/services", timeout=5) as resp:
        return _json.loads(resp.read().decode("utf-8"))


def consul_health_passing(consul_url, service_name):
    """GET /v1/health/service/<name>?passing=true -> list of healthy entries."""
    import json as _json
    url = f"{consul_url}/v1/health/service/{service_name}?passing=true"
    with urllib.request.urlopen(url, timeout=5) as resp:
        return _json.loads(resp.read().decode("utf-8"))


# --------------------------------------------------------------------------------------------------------------
