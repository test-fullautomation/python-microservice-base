"""Starts ``python -m robot`` so the Manager GUI can stop it gracefully.

Run by path with the project's interpreter (which need not have
MicroserviceBase installed)::

    python robot_boot.py <robot arguments...>

When ``MM_RUN_STOP_FILE`` names a file, a watcher thread waits for it to
appear and then interrupts the main thread with SIGINT -- exactly what
Ctrl-C does in a terminal. Robot Framework then stops gracefully: the
running keyword ends, teardowns run, and ``output.xml``, ``log.html`` and
``report.html`` are still written. A console control event would need a
console the GUI's bridge does not have; a file needs nothing.
"""

import os
import runpy
import signal
import sys
import threading
import time
import _thread

# This folder must not shadow anything the tests import.
if sys.path and os.path.abspath(sys.path[0] or ".") == os.path.dirname(os.path.abspath(__file__)):
    del sys.path[0]

_STOP_FILE = os.environ.pop("MM_RUN_STOP_FILE", "")


def _watch() -> None:
    while not os.path.exists(_STOP_FILE):
        time.sleep(0.3)
    _thread.interrupt_main(signal.SIGINT)


if _STOP_FILE:
    threading.Thread(target=_watch, name="mm-stop-watch", daemon=True).start()

sys.argv = ["robot"] + sys.argv[1:]
runpy.run_module("robot", run_name="__main__", alter_sys=True)
