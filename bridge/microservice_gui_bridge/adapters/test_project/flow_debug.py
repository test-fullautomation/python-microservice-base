"""Debugging a Robot Framework run: breakpoints, stepping, variables.

A Robot listener (API version 2: Robot 6.1 reports keywords only to that
one), added to the run with ``--listener``. It connects to a debugger -- the
Manager GUI's bridge (``debugging.py``) or the VS Code extension -- at
``127.0.0.1:$MM_DEBUG_PORT`` when Robot loads it, waits for the
breakpoints, then lets the run go. Standard library only; runs with the
project's interpreter, which need not have MicroserviceBase.

Where it stops, before a keyword or a control structure starts:

* a **flow step** with a breakpoint -- ``flow_position.py`` (the live
  Diagram's listener, loaded first) tells which step of the flow file Robot
  is starting; steps of a sub-flow are ``<sub-flow name>::<step id>``;
* a **line** with a breakpoint in a suite or resource (``source`` and
  ``lineno`` are where the keyword is called);
* the next step after Step Over / Into / Out or Pause;
* a keyword that failed, when the "Failed keyword" exception filter is on
  (before its parents report the failure too).

Protocol: one JSON object per line each way. The extension sends
``breakpoints``, ``exceptions``, ``configurationDone``, ``pause``,
``continue``, ``next``, ``stepIn``, ``stepOut``, ``terminate`` (no answer),
and ``variables`` / ``evaluate`` with an ``id`` (answered with that ``id``).
The listener sends ``{"event": "stopped", "reason", "description",
"frames": [{name, node, source, lineno}, ...] innermost first}`` and
``{"event": "continued"}``.

Only the main thread stops: THREAD blocks (the fork) run on others.

Python, two ways. Built in: ``stepIn`` with ``"trace": true`` on a keyword
whose frame has ``py`` traces its function (``sys.settrace``, the user's
code only) and stops on its lines like on Robot's -- the stop's frames are
then the Python ones (``"python": true``, a ``ref`` for their locals) above
the Robot ones; ``evaluate`` there is a Python expression in that frame;
Step Over / Into / Out move through the Python code, and when the function
returns the run stops at Robot's next step. Or a real Python debugger (the
VS Code extension): with ``MM_DEBUGPY`` set, debugpy listens in this process (the
interpreter's own debugpy, else the one in ``MM_DEBUGPY_PATH``) and the
``hello`` says on which port; the extension attaches VS Code's Python
debugger there. A frame of a keyword implemented in a Python library of
the user's (not Robot Framework's own, not site-packages unless
``MM_PY_ALL``) carries ``py``: the file and first body line of its
function, where the extension sets a one-time breakpoint for Step Into.
"""

import json
import os
import select
import socket
import sys
import threading

ROBOT_LISTENER_API_VERSION = 2

_PORT = int(os.environ.get("MM_DEBUG_PORT") or 0)
_MAX_CHILDREN = 200
_MAX_REPR = 1000


class _Link:
    """The socket to the extension: JSON lines, a poll that does not block."""

    def __init__(self, port):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=10)
        self.sock.settimeout(None)
        self.buffer = b""
        self.closed = False

    def send(self, message):
        if self.closed:
            return
        try:
            self.sock.sendall((json.dumps(message, default=str) + "\n").encode("utf-8"))
        except OSError:
            self.closed = True

    def _lines(self):
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            if line.strip():
                yield json.loads(line.decode("utf-8"))

    def read(self, block):
        """The messages that have arrived; with ``block``, wait for at least one."""
        out = list(self._lines())
        while not self.closed and (block and not out or not block):
            if not block:
                ready, _, _ = select.select([self.sock], [], [], 0)
                if not ready:
                    break
            try:
                chunk = self.sock.recv(65536)
            except OSError:
                chunk = b""
            if not chunk:
                self.closed = True
                break
            self.buffer += chunk
            out += list(self._lines())
            if not block:
                continue
        return out


def _start_debugpy():
    """debugpy listening in this process: (port, None), or (None, why not)."""
    try:
        try:
            import debugpy
        except ImportError:
            extra = os.environ.get("MM_DEBUGPY_PATH", "")
            if not extra or not os.path.isdir(extra):
                return None, "debugpy is not installed in %s" % sys.executable
            sys.path.append(extra)
            import debugpy
        # Robot's own child processes are not debugged.
        debugpy.configure(subProcess=False)
        _host, port = debugpy.listen(("127.0.0.1", 0))
        return port, None
    except Exception as exc:  # noqa: BLE001 -- the Robot side works without it
        return None, "%s: %s" % (type(exc).__name__, exc)


_link = None
_debugpy_port = None
if _PORT:
    try:
        _link = _Link(_PORT)
    except OSError as exc:
        sys.__stderr__.write("[flow_debug] cannot reach the debugger on port %s: %s\n" % (_PORT, exc))
        _link = None
    if _link:
        hello = {"event": "hello", "pid": os.getpid(), "python": sys.version.split()[0]}
        if os.environ.get("MM_DEBUGPY"):
            _debugpy_port, why = _start_debugpy()
            hello.update(debugpy=_debugpy_port, debugpyError=why)
        _link.send(hello)

_state = {
    "mode": "run",            # run | step (stop at the next start within `depth`) | pause
    "depth": None,            # step: stop when the stack is at most this deep (None: anywhere)
    "nodes": set(),           # flow steps with a breakpoint
    "lines": set(),           # (normcase(source), line)
    "on_failure": False,
    "failure_seen": False,    # a failure was reported; its parents' ends are not new ones
    "evaluating": False,      # a keyword run from the Debug Console: not stepped through
}
_stack = []                   # [{name, node, source, lineno, args}] outermost first
_refs = {}                    # variablesReference -> object, for the current stop


def _key(source, lineno):
    return (os.path.normcase(os.path.abspath(source)) if source else "", int(lineno or 0))


def _apply(msg):
    """A message that changes how the run goes on. True when it ends a stop."""
    cmd = msg.get("cmd")
    if cmd == "breakpoints":
        _state["nodes"] = set(msg.get("nodes") or [])
        _state["lines"] = {_key(s, l) for s, l in msg.get("lines") or []}
    elif cmd == "exceptions":
        _state["on_failure"] = "failed" in (msg.get("filters") or [])
    elif cmd == "pause":
        _state["mode"], _state["depth"] = "pause", None
    elif cmd == "continue":
        _state["mode"], _state["depth"] = "run", None
        return True
    elif cmd in ("next", "stepIn", "stepOut"):
        here = len(_stack)
        _state["mode"] = "step"
        _state["depth"] = {"next": here, "stepIn": None, "stepOut": here - 1}[cmd]
        if cmd == "stepIn" and msg.get("trace") and msg.get("py"):
            # Into the keyword's Python function; Robot itself steps over it.
            code = _py_codes.get((msg["py"].get("file"), msg["py"].get("function")))
            if code is not None:
                _state["depth"] = here
                _py_begin(code)
        return True
    elif cmd == "terminate":
        # The extension stops the process (its stop file); no more stops until then.
        _state.update(mode="run", depth=None, nodes=set(), lines=set(), on_failure=False)
        return True
    elif cmd == "configurationDone":
        return True
    return False


def _handshake():
    """Wait for the breakpoints before the run starts (Stop on Entry is a pause)."""
    while _link and not _link.closed:
        for msg in _link.read(block=True):
            if _apply(msg) and msg.get("cmd") == "configurationDone":
                if msg.get("stopOnEntry"):
                    _state["mode"] = "pause"
                if msg.get("python") and _debugpy_port:
                    _wait_for_python()
                return


def _wait_for_python(seconds=20):
    """Let the Python debugger finish attaching (its breakpoints set) before the run starts."""
    import debugpy
    done = threading.Event()

    def wait():
        try:
            debugpy.wait_for_client()
        finally:
            done.set()

    threading.Thread(target=wait, name="mm-debugpy-wait", daemon=True).start()
    done.wait(seconds)


if _link:
    _handshake()


def _position():
    return sys.modules.get("flow_position")


def _node(attrs):
    pos = _position()
    return pos._node(attrs) if pos is not None else None


def _main_thread():
    return threading.current_thread() is threading.main_thread()


# ---- variables -------------------------------------------------------------

def _builtin():
    from robot.libraries.BuiltIn import BuiltIn
    return BuiltIn()


def _describe(name, value):
    ref = 0
    kind = type(value).__name__
    if isinstance(value, dict) and value:
        ref = _remember(value)
        shown = "{%d items}" % len(value)
    elif isinstance(value, (list, tuple, set)) and value:
        ref = _remember(list(value))
        shown = "[%d items]" % len(value)
    else:
        try:
            shown = repr(value) if not isinstance(value, str) else value
        except Exception as exc:  # noqa: BLE001 -- an object whose repr fails
            shown = "<%s: repr failed: %s>" % (kind, exc)
    if len(shown) > _MAX_REPR:
        shown = shown[:_MAX_REPR] + "…"
    return {"name": str(name), "value": shown, "type": kind, "variablesReference": ref}


def _remember(obj):
    ref = len(_refs) + 100
    _refs[ref] = obj
    return ref


def _variables(ref):
    obj = _refs.get(ref)
    if isinstance(obj, tuple) and obj[0] == "frame":       # a Python frame's locals
        items = [(k, v) for k, v in obj[1].f_locals.items() if not (k.startswith("__") and k.endswith("__"))]
        return [_describe(k, v) for k, v in items[:_MAX_CHILDREN]]
    if ref == 1:              # every variable Robot has in scope here
        items = sorted(_builtin().get_variables().items(), key=lambda kv: str(kv[0]).lower())
        return [_describe(k, v) for k, v in items]
    if ref == 2:              # the arguments the current keyword was called with
        args = (_stack[-1].get("args") if _stack else None) or []
        return [_describe(str(i + 1), a) for i, a in enumerate(args)]
    obj = _refs.get(ref)
    if isinstance(obj, dict):
        return [_describe(k, v) for k, v in list(obj.items())[:_MAX_CHILDREN]]
    if isinstance(obj, list):
        return [_describe("[%d]" % i, v) for i, v in enumerate(obj[:_MAX_CHILDREN])]
    return []


_CELLS = __import__("re").compile(r"  +|\t+")


def _evaluate(expression):
    """``${var}`` (also ``${var}[0]``, ``${var.attr}``) or a keyword call, cells
    separated by two spaces: ``Log To Console  hello``."""
    text = expression.strip()
    if not text:
        return {"result": "", "variablesReference": 0}
    builtin = _builtin()
    if text[:2] in ("${", "@{", "&{", "%{") and text.endswith(("}", "]")):
        # One variable (with [item] or .attr) comes back as the object itself.
        value = builtin.replace_variables(text)
        d = _describe(text, value)
        return {"result": d["value"], "type": d["type"], "variablesReference": d["variablesReference"]}
    cells = [c for c in _CELLS.split(text) if c != ""]
    _state["evaluating"] = True
    try:
        value = builtin.run_keyword(cells[0], *cells[1:])
    finally:
        _state["evaluating"] = False
    d = _describe(cells[0], value)
    return {"result": d["value"], "type": d["type"], "variablesReference": d["variablesReference"]}


# ---- stopping ----------------------------------------------------------------

def _frames():
    out = []
    for f in reversed(_stack):
        out.append({"name": f["name"], "node": f["node"], "source": f["source"], "lineno": f["lineno"]})
    if out and _stack[-1].get("library"):
        py = _python_of(_stack[-1]["full"])
        if py:
            out[0]["py"] = py
    return out


def _excluded_dirs():
    import sysconfig
    dirs = [os.path.dirname(os.path.abspath(__file__))]
    try:
        import robot
        dirs.append(os.path.dirname(os.path.abspath(robot.__file__)))
    except ImportError:
        pass
    if not os.environ.get("MM_PY_ALL"):
        paths = sysconfig.get_paths()
        dirs += [paths.get(k) for k in ("stdlib", "platstdlib", "purelib", "platlib") if paths.get(k)]
    return [os.path.normcase(os.path.abspath(d)) + os.sep for d in dirs]


def _python_of(name):
    """``{file, line, function}`` of the Python function behind keyword ``name``
    (its first body line), when it is the user's code; else None."""
    try:
        import dis
        import inspect
        from robot.running import EXECUTION_CONTEXTS
        runner = EXECUTION_CONTEXTS.current.get_runner(name)
        handler = getattr(runner, "_handler", None)
        if handler is None or not hasattr(handler, "current_handler"):
            return None               # a user keyword: Robot steps into it itself
        fn = inspect.unwrap(handler.current_handler())
        code = getattr(fn, "__code__", None)
        if code is None:
            return None
        file = os.path.abspath(inspect.getsourcefile(fn) or code.co_filename)
        if any(os.path.normcase(file).startswith(d) for d in _excluded_dirs()):
            return None
        src, start = inspect.getsourcelines(fn)
        offset = next((i for i, line in enumerate(src) if line.lstrip().startswith(("def ", "async def "))), 0)
        def_line = start + offset
        body = sorted({line for _, line in dis.findlinestarts(code) if line and line > def_line})
        _py_codes[(file, code.co_name)] = code
        return {"file": file, "line": body[0] if body else def_line, "function": code.co_name}
    except Exception:  # noqa: BLE001 -- no Python step-in for this keyword
        return None


def _stop(reason, description=""):
    """Tell the debugger where we are and serve it until it lets the run go."""
    _refs.clear()
    _state["mode"], _state["depth"] = "run", None
    _serve({"event": "stopped", "reason": reason, "description": description, "frames": _frames()}, _apply)


def _serve(stopped, apply, frame=None):
    """Send `stopped`, answer variables and evaluate (in Python `frame`, when
    stopped in Python) until a message `apply` takes ends the stop."""
    _link.send(stopped)
    while not _link.closed:
        for msg in _link.read(block=True):
            rid = msg.get("id")
            cmd = msg.get("cmd")
            if cmd in ("variables", "evaluate"):
                try:
                    if cmd == "variables":
                        body = _variables(int(msg.get("ref") or 0))
                    else:
                        body = _evaluate_in(frame, str(msg.get("expression") or ""))
                    _link.send({"id": rid, "ok": True, "body": body})
                except Exception as exc:  # noqa: BLE001 -- the Debug Console shows it
                    _link.send({"id": rid, "ok": False, "error": "%s: %s" % (type(exc).__name__, exc)})
            elif apply(msg):
                _link.send({"event": "continued"})
                return


def _evaluate_in(frame, text):
    """In a Python frame: a Python expression there (``${var}`` is still Robot's)."""
    if frame is None or text.strip()[:2] in ("${", "@{", "&{", "%{"):
        return _evaluate(text)
    value = eval(text, frame.f_globals, frame.f_locals)  # noqa: S307 -- the user's own console
    d = _describe(text, value)
    return {"result": d["value"], "type": d["type"], "variablesReference": d["variablesReference"]}


# ---- stepping through Python (built in) ----------------------------------------
#
# sys.settrace on the main thread, from the keyword's function down through the
# user's code (not Robot's, not the standard library or site-packages): every
# line event decides whether to stop, by how deep it is below the function.

_py_codes = {}                # (file, function) -> code, of the keywords _python_of saw
_py = {"active": False, "code": None, "entry": None, "mode": "in", "depth": 0}
_excluded = []


def _py_begin(code):
    _py.update(active=True, code=code, entry=None, mode="in", depth=0)
    _excluded[:] = _excluded_dirs()
    sys.settrace(_py_global)


def _py_end():
    _py.update(active=False, code=None, entry=None)
    sys.settrace(None)


def _py_depth(frame):
    """How many calls below the keyword's function `frame` is; -1 when not below it."""
    depth, f = 0, frame
    while f is not None and f is not _py["entry"]:
        f, depth = f.f_back, depth + 1
    return depth if f is not None else -1


def _py_user(code):
    file = os.path.normcase(os.path.abspath(code.co_filename))
    return not any(file.startswith(d) for d in _excluded)


def _py_global(frame, event, arg):
    if not _py["active"] or not _main_thread():
        return None
    if _py["entry"] is None:
        if frame.f_code is not _py["code"]:
            return None
        _py["entry"] = frame
        return _py_local
    if _py_depth(frame) < 0 or not _py_user(frame.f_code):
        return None
    return _py_local


def _py_local(frame, event, arg):
    if not _py["active"]:
        return None
    if event == "line":
        depth, mode = _py_depth(frame), _py["mode"]
        if mode == "in" or (mode == "over" and depth <= _py["depth"]) or (mode == "out" and depth < _py["depth"]):
            _py_stop(frame)
    elif event == "return" and frame is _py["entry"]:
        _py_end()                 # back in Robot: its step stops at the next item
    return _py_local


def _py_stop(frame):
    _refs.clear()
    frames, f = [], frame
    while f is not None:
        frames.append({"name": f.f_code.co_name, "node": None, "python": True, "ref": _remember(("frame", f)),
                       "source": os.path.abspath(f.f_code.co_filename), "lineno": f.f_lineno})
        if f is _py["entry"]:
            break
        f = f.f_back
    robot = _frames()
    if robot:
        robot[0].pop("py", None)
    here = _py_depth(frame)

    def apply(msg):
        cmd = msg.get("cmd")
        if cmd == "next":
            _py.update(mode="over", depth=here)
        elif cmd == "stepIn":
            _py.update(mode="in", depth=here)
        elif cmd == "stepOut":
            _py.update(mode="out", depth=here)
        elif cmd in ("continue", "terminate"):
            _py_end()
            return _apply(msg)
        else:
            return _apply(msg)    # breakpoints, exceptions, pause: Robot's
        return True

    _serve({"event": "stopped", "reason": "step", "description": "", "frames": frames + robot}, apply, frame)


def _poll():
    """Messages that came while running: breakpoints changed, Pause."""
    for msg in _link.read(block=False):
        _apply(msg)


# ---- listener ------------------------------------------------------------------

def start_keyword(name, attrs):
    if not _link or _link.closed or _state["evaluating"] or not _main_thread():
        return
    if attrs.get("status") == "NOT RUN":
        return
    node = _node(attrs)
    source, lineno = attrs.get("source") or "", attrs.get("lineno") or 0
    label = attrs.get("kwname") or name
    if attrs.get("type") not in (None, "KEYWORD", "SETUP", "TEARDOWN"):
        label = ("%s %s" % (attrs.get("type"), name or "")).strip()
    _stack.append({"name": label or attrs.get("type") or "?", "node": node, "source": source,
                   "lineno": lineno, "args": attrs.get("args"), "full": name,
                   "library": attrs.get("libname") if attrs.get("type") in (None, "KEYWORD", "SETUP", "TEARDOWN") else None})
    _state["failure_seen"] = False
    _poll()
    # Somewhere to show: a flow step, or a line of a suite or resource -- not
    # the keywords the fork generates around a flow's phases and sub-flows.
    shown = node is not None or bool(source and lineno and not source.lower().endswith(".flow.json"))
    reason = None
    if node is not None and node in _state["nodes"]:
        reason = "breakpoint"
    elif source and lineno and node is None and _key(source, lineno) in _state["lines"]:
        reason = "breakpoint"
    elif not shown:
        reason = None
    elif _state["mode"] == "pause":
        reason = "pause"
    elif _state["mode"] == "step" and (_state["depth"] is None or len(_stack) <= _state["depth"]):
        # `depth` is how deep the stack was where it stopped: Step Over stops at the
        # next item as deep or shallower, Step Out shallower, Step Into anywhere.
        reason = "step"
    if reason:
        _stop(reason)


def end_keyword(name, attrs):
    if not _link or _link.closed or _state["evaluating"] or not _main_thread():
        return
    if attrs.get("status") == "NOT RUN":
        return                # its start was not pushed either
    if attrs.get("status") == "FAIL" and _state["on_failure"] and not _state["failure_seen"]:
        _state["failure_seen"] = True
        _stop("exception", "%s failed" % (attrs.get("kwname") or name))
    if _stack:
        _stack.pop()


def close():
    if _link and not _link.closed:
        _link.send({"event": "done"})
        try:
            _link.sock.close()
        except OSError:
            pass
