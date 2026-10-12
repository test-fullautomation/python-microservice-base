"""Where a running flow is: the node of the flow file each process is in.

Loaded by ``robot_boot.py`` into the Robot process, when the GUI asks for it
(``MM_FLOW_POSITION`` names the file to write). Two parts:

* :func:`install` wraps the emitters of the fork's flow builder
  (``robot.flow.builder``), before Robot builds the suite: every item built
  for a flow node -- a keyword call, a gate, an ``IF``, a ``WHILE``, a
  ``TRY`` -- gets a ``lineno`` from :data:`BASE` up, and :data:`NODES` maps it
  back to the node's id. A flow file has no line numbers of its own, and
  resource keywords keep their real ones, far below :data:`BASE`.
* The module is also the listener (API version 2: Robot 6.1 reports keywords
  only to that one): each start and end of such an item updates the
  position file -- the node the main thread is in now, how often each node
  passed or failed, and the trail of the last :data:`TRAIL` steps entered
  (numbered, so a reader that polls can tell which it has not seen yet) --
  replaced whole, so a reader never sees half.

Runs with the project's interpreter, which need not have MicroserviceBase
installed: standard library only. Without the fork, :func:`install` does
nothing and the run goes on as before.
"""

import collections
import json
import os
import threading
import time

ROBOT_LISTENER_API_VERSION = 2

BASE = 10_000_000
#: lineno - BASE -> node id, filled while the fork builds the suite.
NODES = []

_path = os.environ.get("MM_FLOW_POSITION", "")
#: How many of the latest steps the file carries, for a view to replay what
#: happened between two of its polls.
TRAIL = 30

_state = {"source": "", "stack": [], "since": 0.0, "counts": {}, "last": None, "done": False}
_seq = 0
_step = 0                                   # steps entered so far
_trail = collections.deque(maxlen=TRAIL)    # [step, node], oldest first


def install():
    """Wrap the fork's flow emitters, so the items they build carry their node. False without the fork."""
    try:
        from robot.flow import builder
    except ImportError:
        return False
    emitters = getattr(getattr(builder, "_Emitter", None), "_emitters", None)
    if not isinstance(emitters, dict) or getattr(builder, "_mm_positions", False):
        return bool(emitters)
    for kind, emit in list(emitters.items()):
        emitters[kind] = _stamping(emit)
    # A loop directly in a test phase is built apart, with its checkpoint
    # bookkeeping (``Flow Loop``, the WHILE): the same stamps.
    tracked = getattr(builder._Emitter, "_tracked_loop", None)
    if tracked is not None:
        builder._Emitter._tracked_loop = _stamping(tracked)
    builder._mm_positions = True
    _tolerate_new_output_files()
    _keep_step_mode()
    return True


def _keep_step_mode():
    """The fork's step mode (``FLOW_STEP``) pauses before the steps that have no
    line number -- a flow's own; a step with one is taken for a line of a
    resource. Our stamps give flow steps one: hide it from that check, so the
    flow still pauses before each of its steps."""
    try:
        from robot.flow import control
    except ImportError:
        return
    flow_control = getattr(control, "FlowControl", None)
    step = getattr(flow_control, "step", None)
    if step is None or getattr(step, "_mm_stamps", False):
        return

    def stamp_aware(self, context, item):
        lineno = getattr(item, "lineno", None)
        if not (isinstance(lineno, int) and BASE <= lineno < BASE + len(NODES)):
            return step(self, context, item)
        item.lineno = None
        try:
            return step(self, context, item)
        finally:
            item.lineno = lineno

    stamp_aware._mm_stamps = True
    flow_control.step = stamp_aware


def _tolerate_new_output_files():
    """Robot tells listeners about each file it wrote through ``_<type>_file``,
    for the types it knows. The fork writes more (``--timeline``) without
    such a method, and with a listener registered that ends the run in an
    AttributeError. Unknown types are simply not announced."""
    try:
        from robot.output.listeners import Listeners
    except ImportError:
        return
    if getattr(Listeners.output_file, "_mm_tolerant", False):
        return
    announce = Listeners.output_file

    def output_file(self, file_type, path):
        if hasattr(self, "_%s_file" % str(file_type).lower()):
            announce(self, file_type, path)

    output_file._mm_tolerant = True
    Listeners.output_file = output_file


_BOOKKEEPING = []


def _bookkeeping():
    """Names of the keywords the fork adds for its checkpoint (``Flow Phase``,
    ``Flow Loop``, ``Flow Iteration``); none with an older fork."""
    if not _BOOKKEEPING:
        names = set()
        try:
            from robot.flow import builder
            names.update(getattr(builder, n) for n in ("PHASE_KEYWORD", "LOOP_KEYWORD", "ITERATION_KEYWORD")
                         if isinstance(getattr(builder, n, None), str))
        except ImportError:
            pass
        _BOOKKEEPING.append(frozenset(names))
    return _BOOKKEEPING[0]


def _stamping(emit):
    def wrapper(self, body, step, *more):
        before = len(body)
        emit(self, body, step, *more)
        node = getattr(step, "id", None) or getattr(getattr(step, "node", None), "id", None)
        if node is None:
            return
        # Inside a sub-flow the ids are the sub-flow file's own; its name is
        # unique in the suite, so '<name>::<id>' tells them apart.
        calling = getattr(self, "_calling", None)
        if calling:
            name = getattr(self, "_subflows", {}).get(calling[-1], ("",))[0]
            node = "%s::%s" % (name[len("Flow: "):] if name.startswith("Flow: ") else name, node)
        # A loop builds its deadline, the WHILE and nothing else at this level;
        # every other kind builds exactly one item. Nested steps were stamped
        # by their own emitter already.
        for item in list(body)[before:]:
            if getattr(item, "name", None) in _bookkeeping():
                continue          # the fork's checkpoint keywords (Flow Loop, ...): not a step
            if getattr(item, "lineno", None) is None or item.lineno < BASE:
                item.lineno = BASE + len(NODES)
                NODES.append(str(node))
                # Listeners never hear of an IF's root, only of its branches:
                # they carry the decision's node, so the taken one shows it.
                if getattr(item, "type", None) == "IF/ELSE ROOT":
                    for branch in item.body:
                        if getattr(branch, "lineno", None) is None or branch.lineno < BASE:
                            branch.lineno = item.lineno
    return wrapper


def _node(attrs):
    lineno = attrs.get("lineno")
    if isinstance(lineno, int) and BASE <= lineno < BASE + len(NODES):
        return NODES[lineno - BASE]
    return None


def _view():
    """The stack as shown: a node once, however often Robot re-entered it.

    Robot gives what runs *through* a step the step's line number too: a
    loop's iterations, and the keyword a gate polls (``Run Keyword``)."""
    out = []
    for node in _state["stack"]:
        if not out or out[-1] != node:
            out.append(node)
    return out


_shown = [None]


def _write(force=False):
    global _seq
    if not _path:
        return
    stack = _view()
    key = (tuple(stack), _state["last"] and _state["last"]["time"], _state["done"])
    if key == _shown[0] and not force:
        return
    _shown[0] = key
    _seq += 1
    data = {
        "seq": _seq,
        "time": time.time(),
        "source": _state["source"],
        "node": stack[-1] if stack else None,
        "stack": stack,
        "since": _state["since"],
        "last": _state["last"],
        "counts": _state["counts"],
        "step": _step,
        "trail": list(_trail),
        "done": _state["done"],
    }
    tmp = _path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, separators=(",", ":"))
    except OSError:
        return
    for _ in range(3):
        try:
            os.replace(tmp, _path)
            return
        except PermissionError:
            # The bridge is reading the old one (Windows); it takes a moment.
            time.sleep(0.02)
        except OSError:
            return


def _main_thread():
    # THREAD blocks (the fork) run keywords on other threads; the position is the flow's own.
    return threading.current_thread() is threading.main_thread()


# ---- listener -------------------------------------------------------------

def start_suite(name, attrs):
    if attrs.get("source"):
        _state["source"] = attrs["source"]


def _not_run(attrs):
    # Robot reports the steps of a branch it does not take as well, 'NOT RUN'
    # already at their start: they were never entered.
    return attrs.get("status") == "NOT RUN"


def start_keyword(name, attrs):
    global _step
    node = _node(attrs)
    if node is None or not _main_thread() or _not_run(attrs):
        return
    stack = _state["stack"]
    if not stack or stack[-1] != node:
        # A step entered -- not an iteration or a gate's poll re-entering it.
        _state["since"] = time.time()
        _step += 1
        _trail.append([_step, node])
    stack.append(node)
    _write()


def end_keyword(name, attrs):
    node = _node(attrs)
    if node is None or not _main_thread() or _not_run(attrs):
        return
    stack = _state["stack"]
    if stack and stack[-1] == node:
        stack.pop()
    elif node in stack:
        del stack[len(stack) - 1 - stack[::-1].index(node)]
    # Only the node itself counts, not an iteration or a gate's poll inside it.
    if stack and stack[-1] == node:
        return
    status = attrs.get("status")
    if status in ("PASS", "FAIL"):
        count = _state["counts"].setdefault(node, {"pass": 0, "fail": 0})
        count["pass" if status == "PASS" else "fail"] += 1
        _state["last"] = {"node": node, "status": status, "time": time.time()}
    _state["since"] = time.time()
    _write()


def close():
    _state["stack"] = []
    _state["done"] = True
    _write(force=True)
