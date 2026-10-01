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
  ``no``. Nothing here re-implements the structuring rules. ``variables``
  are the file's own defaults, as written.
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


def _steps(steps, where):
    return [_step(s, where) for s in steps or []]


def _step(step, where):
    """``where``: (folder sub-flow files resolve from, files of the calls above)."""
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
        out.update(condition=_text(step.condition), yes=_steps(step.yes, where), no=_steps(step.no, where))
    if isinstance(step, graph.Guarded):
        out.update(body=_steps(step.body, where),
                   recovery=_steps(step.recovery, where) if step.recovery is not None else None,
                   then=_text(step.then))
    if isinstance(step, graph.Loop):
        out.update(max_loops=_text(step.max_loops), max_seconds=_text(step.max_seconds), every=_text(step.every))
    if getattr(graph, "FlowStep", None) and isinstance(step, graph.FlowStep):
        out.update(file=step.file, args={str(k): _text(v) for k, v in (step.args or {}).items()},
                   subflow=_subflow(step.file, where))
    return out


def _subflow(file, where):
    """The called sub-flow's name and steps, for the diagram to open in place."""
    from robot.flow import load_flow, structure
    from robot.errors import DataError
    folder, calling = where
    path = os.path.normcase(os.path.abspath(os.path.join(folder, file)))
    if path in calling:
        return {"name": None, "error": "calls itself (a cycle of sub-flows)"}
    try:
        flow = structure(load_flow(path))
    except DataError as exc:
        return {"name": None, "error": str(exc)}
    return {"name": flow.name, "file": file,
            "steps": _steps(flow.tests[0].steps if flow.tests else [],
                            (os.path.dirname(path), calling | {path}))}


def _phase(phase, where):
    if phase is None:
        return None
    return {"id": phase.node.id if phase.node is not None else None,
            "role": phase.role, "name": phase.name, "steps": _steps(phase.steps, where)}


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
    variables = data.get("variables") if isinstance(data.get("variables"), dict) else {}
    here = os.path.abspath(path)
    where = (os.path.dirname(here), frozenset({os.path.normcase(here)}))
    return {"ok": True, "robot": robot, "flow": {
        "name": flow.name,
        "variables": {str(k): _text(v) for k, v in variables.items()},
        "setup": _phase(flow.setup, where),
        "tests": [_phase(p, where) for p in flow.tests],
        "teardown": _phase(flow.teardown, where),
    }}


def edit():
    """``--edit``: stdin is {"text": ..., "edit": {...}}; the answer is the new text."""
    import importlib.util
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8-sig", errors="replace"))
        text, change = payload["text"], payload["edit"]
    except (ValueError, KeyError, TypeError) as exc:
        return {"ok": False, "error": f"Bad edit request: {exc}"}
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "flow_edit.py")
    spec = importlib.util.spec_from_file_location("mm_flow_edit", here)
    flow_edit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(flow_edit)
    try:
        new_text, node = flow_edit.apply_edit(text, change)
    except flow_edit.FlowEditError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "text": new_text, "node": node}


if __name__ == "__main__":
    sys.stdout.write(json.dumps(edit() if "--edit" in sys.argv[1:] else main()))
