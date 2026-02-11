#  Copyright 2020-2025 Robert Bosch GmbH
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
# *******************************************************************************
#
# File: service_executor.py
#
# Initially created by Nguyen Huynh Tri Cuong (MS/EMC51) / Feb 2026.
#
# Description:
#
#   Custom ProcessHub executor that sends an RPC shutdown command to a
#   MicroserviceBase service before falling back to signal-based termination.
#
# *******************************************************************************
"""
Service-aware process executor.

Wraps a ``SimpleExecutor`` and attempts graceful RPC shutdown
(``svc_api_shutdown``) before falling back to signal-based stop.
"""

import json
import logging
import os
import shutil
import subprocess
import sys
import time
import uuid
from typing import Callable, Optional

from ProcessHub.process import ProcessExecutor, SimpleExecutor

logger = logging.getLogger(__name__)


class ServiceExecutor(ProcessExecutor):
    """
Process executor that sends an RPC shutdown to MicroserviceBase services.

Delegates all operations to a wrapped ``SimpleExecutor``.  On ``stop()``,
it first tries to send ``svc_api_shutdown`` via RabbitMQ to the service's
queue.  If the service exits within ``shutdown_timeout`` seconds the
process is considered stopped.  Otherwise it falls back to the delegate's
signal-based stop (CTRL_BREAK_EVENT on Windows, SIGTERM on Linux).
    """

    def __init__(
        self,
        broker_host: str = "localhost",
        broker_port: int = 5672,
        start_callback: Optional[Callable] = None,
        stop_callback: Optional[Callable] = None,
        stop_timeout: float = 5.0,
        shutdown_timeout: float = 5.0,
        log_dir: Optional[str] = None,
    ):
        self._broker_host = broker_host
        self._broker_port = int(broker_port)
        self._shutdown_timeout = shutdown_timeout
        self._log_dir = log_dir
        self._log_handles: dict[str, object] = {}  # name -> open file
        self._configs: dict[str, dict] = {}  # name -> config (for RPC lookup)
        self._delegate = SimpleExecutor(
            start_callback=start_callback,
            stop_callback=stop_callback,
            stop_timeout=stop_timeout,
        )

        if self._log_dir:
            os.makedirs(self._log_dir, exist_ok=True)

    # -- Delegated methods --------------------------------------------------

    def start(self, name, config):
        """
Start a named process using the given config.

**Arguments:**

* ``name``

  / *Condition*: required / *Type*: str /

  Process name.

* ``config``

  / *Condition*: required / *Type*: dict /

  Process configuration dict with 'script', 'args', 'cwd', etc.
        """
        self._configs[name] = config
        if self._log_dir:
            return self._start_logged(name, config)
        cwd = config.get("cwd") or None
        if cwd:
            return self._start_with_cwd(name, config, cwd)
        return self._delegate.start(name, config)

    def _get_log_path(self, name):
        """
Return the log file path for a process.

**Arguments:**

* ``name``

  / *Condition*: required / *Type*: str /

  Process name.
        """
        if not self._log_dir:
            return None
        return os.path.join(self._log_dir, f"{name}.log")

    def get_log_path(self, name):
        """
Public accessor for log file path.

**Arguments:**

* ``name``

  / *Condition*: required / *Type*: str /

  Process name.
        """
        return self._get_log_path(name)

    def _start_logged(self, name, config):
        """
Start a process with stdout/stderr redirected to a log file.

Handles both regular and ``cwd``-based (``python -m``) execution.

**Arguments:**

* ``name``

  / *Condition*: required / *Type*: str /

  Process name.

* ``config``

  / *Condition*: required / *Type*: dict /

  Process configuration dict.
        """
        if self._delegate.is_running(name):
            pid = self._delegate.get_pid(name)
            return True, f"Process {name} is already running", pid

        script = config.get("script", "")
        args = config.get("args", [])
        wait_time = config.get("wait_time", 2.0)
        env = config.get("env", {})
        cwd = config.get("cwd") or None

        if not script:
            return False, "No script specified", None

        # Pre-checks for cwd / -m execution
        if cwd:
            if not os.path.isdir(cwd):
                return False, f"Working directory does not exist: {cwd}", None
            if len(args) >= 2 and args[0] == "-m":
                module_dir = os.path.join(cwd, args[1])
                if not os.path.isdir(module_dir):
                    return False, f"Module directory not found: {module_dir}", None
                if not os.path.isfile(os.path.join(module_dir, '__main__.py')):
                    return False, f"__main__.py not found in {module_dir}", None

        script = os.path.expandvars(script)

        # Resolve script path
        if not os.path.exists(script):
            found = shutil.which(script)
            if found:
                script = found
            else:
                return False, f"Script not found: {script}", None

        # Build command
        if script.endswith(".py"):
            cmd = [sys.executable, script] + args
        else:
            cmd = [script] + args

        # Prepare environment
        proc_env = os.environ.copy()
        proc_env.update(env)

        # Open log file (truncate on each start so it shows latest run)
        log_path = self._get_log_path(name)
        try:
            log_fh = open(log_path, 'w', encoding='utf-8')
        except Exception as exc:
            return False, f"Cannot open log file {log_path}: {exc}", None

        try:
            proc = subprocess.Popen(
                cmd,
                cwd=cwd,
                env=proc_env,
                stdout=log_fh,
                stderr=log_fh,
                creationflags=(
                    subprocess.CREATE_NEW_PROCESS_GROUP
                    if sys.platform == "win32"
                    else 0
                ),
            )

            self._delegate._processes[name] = proc
            self._delegate._pids[name] = proc.pid
            self._log_handles[name] = log_fh

            if wait_time > 0:
                time.sleep(wait_time)

            if proc.poll() is not None:
                # Process exited — close log handle and read the output
                self._close_log(name)
                self._delegate._processes.pop(name, None)
                self._delegate._pids.pop(name, None)
                msg = f"Process {name} exited immediately"
                # Read the log to show what went wrong
                tail = self._read_log_tail(name, 8)
                if tail:
                    msg += ": " + " | ".join(tail.splitlines())
                logger.error("%s — log: %s", msg, tail)
                return False, msg, None

            logger.info(
                "Started process %s (pid=%d, log=%s%s)",
                name, proc.pid, log_path,
                f", cwd={cwd}" if cwd else "",
            )
            return True, f"Started {name}", proc.pid

        except Exception as e:
            log_fh.close()
            self._log_handles.pop(name, None)
            logger.exception("Failed to start process %s", name)
            return False, str(e), None

    def _start_with_cwd(self, name, config, cwd):
        """
Start a process with cwd but without log file (fallback).

**Arguments:**

* ``name``

  / *Condition*: required / *Type*: str /

  Process name.

* ``config``

  / *Condition*: required / *Type*: dict /

  Process configuration dict.

* ``cwd``

  / *Condition*: required / *Type*: str /

  Working directory for the process.
        """
        if self._delegate.is_running(name):
            pid = self._delegate.get_pid(name)
            return True, f"Process {name} is already running", pid

        script = config.get("script", "")
        args = config.get("args", [])
        wait_time = config.get("wait_time", 2.0)
        env = config.get("env", {})

        if not script:
            return False, "No script specified", None

        if not os.path.isdir(cwd):
            return False, f"Working directory does not exist: {cwd}", None

        if len(args) >= 2 and args[0] == "-m":
            module_dir = os.path.join(cwd, args[1])
            if not os.path.isdir(module_dir):
                return False, f"Module directory not found: {module_dir}", None
            if not os.path.isfile(os.path.join(module_dir, '__main__.py')):
                return False, f"__main__.py not found in {module_dir}", None

        script = os.path.expandvars(script)

        if not os.path.exists(script):
            found = shutil.which(script)
            if found:
                script = found
            else:
                return False, f"Script not found: {script}", None

        if script.endswith(".py"):
            cmd = [sys.executable, script] + args
        else:
            cmd = [script] + args

        proc_env = os.environ.copy()
        proc_env.update(env)

        try:
            proc = subprocess.Popen(
                cmd,
                cwd=cwd,
                env=proc_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=(
                    subprocess.CREATE_NEW_PROCESS_GROUP
                    if sys.platform == "win32"
                    else 0
                ),
            )

            self._delegate._processes[name] = proc
            self._delegate._pids[name] = proc.pid

            if wait_time > 0:
                time.sleep(wait_time)

            if proc.poll() is not None:
                stderr_text = ""
                try:
                    _, stderr = proc.communicate(timeout=2)
                    stderr_text = stderr.decode('utf-8', errors='replace').strip()
                except Exception:
                    pass
                self._delegate._processes.pop(name, None)
                self._delegate._pids.pop(name, None)
                msg = f"Process {name} exited immediately"
                if stderr_text:
                    lines = stderr_text.splitlines()
                    tail = lines[-5:] if len(lines) > 5 else lines
                    msg += ": " + " | ".join(tail)
                logger.error("%s — stderr: %s", msg, stderr_text)
                return False, msg, None

            logger.info("Started process %s (pid=%d, cwd=%s)", name, proc.pid, cwd)
            return True, f"Started {name}", proc.pid

        except Exception as e:
            logger.exception("Failed to start process %s", name)
            return False, str(e), None

    def _close_log(self, name):
        """
Close the log file handle for a process.

**Arguments:**

* ``name``

  / *Condition*: required / *Type*: str /

  Process name.
        """
        fh = self._log_handles.pop(name, None)
        if fh:
            try:
                fh.close()
            except Exception:
                pass

    def _read_log_tail(self, name, max_lines=50):
        """
Read the last *max_lines* lines from a process log file.

**Arguments:**

* ``name``

  / *Condition*: required / *Type*: str /

  Process name.

* ``max_lines``

  / *Condition*: optional / *Type*: int / *Default*: 50 /

  Maximum number of lines to read from the tail.
        """
        log_path = self._get_log_path(name)
        if not log_path or not os.path.isfile(log_path):
            return ""
        try:
            with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
            tail = lines[-max_lines:] if len(lines) > max_lines else lines
            return "".join(tail).strip()
        except Exception:
            return ""

    def read_log(self, name, tail=100):
        """
Public method to read process log. Returns the text content.

**Arguments:**

* ``name``

  / *Condition*: required / *Type*: str /

  Process name.

* ``tail``

  / *Condition*: optional / *Type*: int / *Default*: 100 /

  Number of lines to read from the tail.
        """
        return self._read_log_tail(name, tail)

    def is_running(self, name):
        """
Check if a named process is running.

**Arguments:**

* ``name``

  / *Condition*: required / *Type*: str /

  Process name.
        """
        return self._delegate.is_running(name)

    def get_pid(self, name):
        """
Get the PID of a named process.

**Arguments:**

* ``name``

  / *Condition*: required / *Type*: str /

  Process name.
        """
        return self._delegate.get_pid(name)

    # -- Stop with RPC shutdown attempt -------------------------------------

    def stop(self, name, force=False):
        """
Stop a named process, attempting RPC shutdown first.

**Arguments:**

* ``name``

  / *Condition*: required / *Type*: str /

  Process name.

* ``force``

  / *Condition*: optional / *Type*: bool / *Default*: False /

  If True, skip graceful shutdown and force-kill.
        """
        if self._delegate.is_running(name):
            if self._try_rpc_shutdown(name):
                # Process exited gracefully after RPC
                self._delegate._processes.pop(name, None)
                self._delegate._pids.pop(name, None)
                self._close_log(name)
                self._delegate._invoke_stop_callback(name)
                return True, f"Process {name} stopped gracefully via RPC"
        # Fallback to signal-based stop
        result = self._delegate.stop(name, force=force)
        self._close_log(name)
        return result

    def _try_rpc_shutdown(self, process_name):
        """
Send ``svc_api_shutdown`` RPC to the service queue.

The service's actual RabbitMQ queue name (``_SERVICE_INFO['name']``)
may differ from the hub process name.  If a ``service_name`` field
is present in the stored config, use that as the routing key for the
default exchange; otherwise fall back to *process_name*.

**Arguments:**

* ``process_name``

  / *Condition*: required / *Type*: str /

  Process name to shut down.

**Returns:**

  / *Type*: bool /

  ``True`` if the process exited within the timeout.
        """
        import pika

        # Resolve the actual queue name the service is consuming on.
        config = self._configs.get(process_name, {})
        queue_name = config.get("service_name") or process_name

        try:
            conn = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=self._broker_host, port=self._broker_port
                )
            )
            ch = conn.channel()
            # Temporary reply queue — required because on_request publishes to
            # props.reply_to; without it the handler would error.
            result = ch.queue_declare(queue="", exclusive=True)
            ch.basic_publish(
                exchange="",
                routing_key=queue_name,
                properties=pika.BasicProperties(
                    reply_to=result.method.queue,
                    correlation_id=str(uuid.uuid4()),
                ),
                body=json.dumps({"method": "svc_api_shutdown", "args": None}),
            )
            conn.close()
            logger.info(
                "Sent svc_api_shutdown RPC to queue '%s' (process='%s')",
                queue_name, process_name,
            )
        except Exception:
            logger.debug(
                "RPC shutdown failed for '%s', will fall back to signal",
                process_name,
                exc_info=True,
            )
            return False

        # Poll for process exit
        deadline = time.monotonic() + self._shutdown_timeout
        while time.monotonic() < deadline:
            if not self._delegate.is_running(process_name):
                logger.info(
                    "Process '%s' exited gracefully after RPC shutdown",
                    process_name,
                )
                return True
            time.sleep(0.3)

        logger.warning(
            "Process '%s' did not exit within %.1fs after RPC shutdown",
            process_name,
            self._shutdown_timeout,
        )
        return False
