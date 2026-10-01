"""
Tests for the managed-agent start watch (adapters/ui_bridge/fastapi_bridge.py).

A Consul or Nomad agent that rejects its configuration exits within a
second. The bridge has to notice that and answer with the agent's own
error, instead of reporting a successful start and leaving the GUI to
report the agent as unreachable.
"""

import os
import socket
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))

from MicroserviceBase.adapters.ui_bridge.fastapi_bridge import (  # noqa: E402
    _agent_start_failure,
    _port_open,
)


class FakeProc:
    """A subprocess.Popen stand-in: alive until it "exits" after N polls."""

    def __init__(self, exit_after=None, returncode=1):
        self.pid = 4242
        self._polls = 0
        self._exit_after = exit_after
        self.returncode = None
        self._code = returncode

    def poll(self):
        self._polls += 1
        if self._exit_after is not None and self._polls > self._exit_after:
            self.returncode = self._code
            return self._code
        return None


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Test_ExitedAgent:

    def test_reports_the_agents_own_error(self):
        log = ["==> Loading configuration from bad.hcl",
               "==> Error loading configuration from bad.hcl: invalid key: job"]
        failure = _agent_start_failure("Nomad agent", FakeProc(exit_after=0), log,
                                       lambda: False, timeout=2)
        assert failure is not None
        assert failure["success"] is False
        assert failure["exit_code"] == 1
        assert "invalid key: job" in failure["message"]
        assert "Nomad agent exited immediately" in failure["message"]

    def test_keeps_the_log_tail_for_the_gui(self):
        log = ["line %d" % i for i in range(40)] + ["Error: nope"]
        failure = _agent_start_failure("Consul agent", FakeProc(exit_after=0), log,
                                       lambda: False, timeout=2)
        assert failure["log_tail"][-1] == "Error: nope"
        assert len(failure["log_tail"]) <= 12

    def test_first_error_line_wins_over_later_noise(self):
        log = ["==> Error loading configuration: invalid key: job",
               "some trailing failed retry line"]
        failure = _agent_start_failure("Nomad agent", FakeProc(exit_after=0), log,
                                       lambda: False, timeout=2)
        assert "invalid key: job" in failure["message"]

    def test_silent_exit_still_reports_the_code(self):
        failure = _agent_start_failure("Nomad agent", FakeProc(exit_after=0, returncode=2), [],
                                       lambda: False, timeout=2)
        assert failure["exit_code"] == 2
        assert "no output" in failure["message"]

    def test_an_exit_during_the_watch_is_caught(self):
        # Alive for the first polls, then gone -- the window must not end early.
        failure = _agent_start_failure("Nomad agent", FakeProc(exit_after=3),
                                       ["Error: died late"], lambda: False,
                                       timeout=3, poll=0.05)
        assert failure is not None
        assert "died late" in failure["message"]


class Test_HealthyAgent:

    def test_no_failure_once_the_port_answers(self):
        failure = _agent_start_failure("Nomad agent", FakeProc(), [],
                                       lambda: True, timeout=2)
        assert failure is None

    def test_returns_as_soon_as_the_port_opens(self):
        opened = []

        def port_open():
            opened.append(1)
            return len(opened) > 2

        t0 = time.time()
        failure = _agent_start_failure("Nomad agent", FakeProc(), [], port_open,
                                       timeout=5, poll=0.05)
        assert failure is None
        assert time.time() - t0 < 2      # not the full window

    def test_a_slow_agent_is_not_called_failed(self):
        # Still alive when the window passes: the GUI waits for it instead.
        failure = _agent_start_failure("Nomad agent", FakeProc(), [],
                                       lambda: False, timeout=0.4, poll=0.05)
        assert failure is None


class Test_PortOpen:

    def test_true_while_something_listens(self):
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        threading.Thread(target=lambda: None, daemon=True).start()
        try:
            assert _port_open("127.0.0.1", port) is True
        finally:
            srv.close()

    def test_false_on_a_free_port(self):
        assert _port_open("127.0.0.1", _free_port()) is False

    def test_unspecified_address_is_probed_on_loopback(self):
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        try:
            assert _port_open("0.0.0.0", port) is True
        finally:
            srv.close()
