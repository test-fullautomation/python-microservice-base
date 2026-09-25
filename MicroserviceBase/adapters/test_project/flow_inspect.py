"""Describe a flow file for the Manager GUI: its structure and its Robot text.

Run by path with the project's interpreter (the one that has the
RobotFramework AIO fork's ``robot.flow`` on its path)::

    python flow_inspect.py <path/to/file.flow.json>   < flow text on stdin

The text comes on stdin so unsaved editor content can be drawn; the path is
where the file lives (imports are resolved relative to it when rendering).
Prints one JSON object:

* ``{"ok": true, "flow": {...}, "robot": "..."}`` -- ``flow`` is the fork's
  own structure (:func:`robot.flow.graph.structure`): phases, each a list of
  steps; loops and tries carry ``body`` / ``recovery``, decisions ``yes`` /
  ``no``. Nothing here re-implements the structuring rules.
* ``{"ok": false, "error": "...", "node": "<id>"|null, "line": n|null}`` --
  the fork refused the file; ``node`` is the node its message names, ``line``
  the line of a JSON syntax error.
* ``{"ok": false, "missing": true, "error": "..."}`` -- no ``robot.flow`` on
  this interpreter's path.
"""

import json
import os
import re
import sys

# This folder must not shadow anything the flow imports.
if sys.path and os.path.abspath(sys.path[0] or ".") == os.path.dirname(os.path.abspath(__file__)):
    del sys.path[0]


def _text(value):
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return [_text(v) for v in value]
    return str(value)


def _steps(steps):
    return [_step(s) for s in steps or []]


def _step(step):
    from robot.flow import graph
    node = step.node
    out = {"id": node.id, "kind": node.kind, "label": getattr(node, "label", node.id)}
    if isinstance(step, graph.KeywordStep):
        out.update(keyword=step.keyword, args=_text(step.args or []), assign=_text(step.assign or []))
    if isinstance(step, graph.GateStep):
        out.update(timeout=_text(step.timeout), interval=_text(step.interval), on_timeout=_text(step.on_timeout))
    if isinstance(step, graph.SleepStep):
        out.update(duration=_text(step.duration))
    if isinstance(step, graph.Decision):
        out.update(condition=_text(step.condition), yes=_steps(step.yes), no=_steps(step.no))
    if isinstance(step, graph.Guarded):
        out.update(body=_steps(step.body),
                   recovery=_steps(step.recovery) if step.recovery is not None else None,
                   then=_text(step.then))
    if isinstance(step, graph.Loop):
        out.update(max_loops=_text(step.max_loops), max_seconds=_text(step.max_seconds), every=_text(step.every))
    return out


def _phase(phase):
    if phase is None:
        return None
    return {"id": phase.node.id if phase.node is not None else None,
            "role": phase.role, "name": phase.name, "steps": _steps(phase.steps)}


def main():
    path = sys.argv[1]
    text = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
    # JSON syntax needs no fork: report it first, with its line.
    try:
        data = json.loads(text)
    except ValueError as exc:
        return {"ok": False, "node": None, "line": getattr(exc, "lineno", None),
                "error": f"Invalid JSON: {exc}"}
    try:
        from robot.flow import build_suite, load_flow, render_robot, structure
        from robot.errors import DataError
    except ImportError as exc:
        return {"ok": False, "missing": True,
                "error": f"This interpreter has no robot.flow ({exc}). Point the project's "
                         "Run settings at a RobotFramework AIO checkout that brings it."}
    try:
        flow = structure(load_flow(data))
        robot = render_robot(build_suite(flow, source=os.path.abspath(path)))
    except DataError as exc:
        message = str(exc)
        match = (re.match(r"Node '([^']+)'", message)
                 or re.match(r"Unreachable node\(s\): ([^,.\s]+)", message))
        return {"ok": False, "node": match.group(1) if match else None, "error": message}
    return {"ok": True, "robot": robot, "flow": {
        "name": flow.name,
        "setup": _phase(flow.setup),
        "tests": [_phase(p) for p in flow.tests],
        "teardown": _phase(flow.teardown),
    }}


if __name__ == "__main__":
    sys.stdout.write(json.dumps(main()))
