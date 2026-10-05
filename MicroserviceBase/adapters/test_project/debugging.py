"""Debugging a test project's run from the Manager GUI.

The bridge's side of ``flow_debug.py`` (the listener in the Robot process),
what the VS Code extension's debug adapter is there: one :class:`DebugSession`
per debugged run. It listens on a local port the run's listener connects to
(``MM_DEBUG_PORT``), sends the breakpoints and the stepping commands, keeps
where the run stopped for the GUI to poll, and asks the listener for
variables and evaluations while it is stopped.

Breakpoints are lines of files, as an editor has them. A line of a flow file
(``*.flow.json``) is the step written there -- anywhere in that step's
object -- and a step of a sub-flow runs as ``<sub-flow name>::<step id>``;
lines of suites and resources stay lines. The stop's frames come back with
the file and line to show, a flow step on the line of its ``"id"``.
"""

from __future__ import annotations

import json
import os
import re
import socket
import threading
from typing import Dict, List, Optional, Tuple

FLOW_SUFFIX = ".flow.json"
LISTENER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "flow_debug.py")
_ID_RE = re.compile(r'"id"\s*:\s*"((?:[^"\\]|\\.)*)"')
_ANSWER_TIMEOUT_S = 30


# ---- lines of a flow file and its steps -------------------------------------

def anchors(text: str) -> List[dict]:
    """``[{id, line, first, last}]``: each step's ``"id"`` line and the lines its object spans."""
    lines = text.splitlines()
    edges = len(lines) + 1
    out: List[dict] = []
    for i, line in enumerate(lines):
        if re.match(r'^\s*"edges"\s*:', line):
            edges = min(edges, i + 1)
        m = _ID_RE.search(line)
        if not m or i + 1 >= edges:
            continue
        first = i + 1
        if "{" not in line[:m.start()]:
            for j in range(i - 1, max(-1, i - 4), -1):
                if re.match(r"^\s*\{\s*$", lines[j]):
                    first = j + 1
                    break
                if lines[j].strip():
                    break
        out.append({"id": json.loads('"%s"' % m.group(1)), "line": i + 1, "first": first, "last": 0})
    for k, a in enumerate(out):
        a["last"] = out[k + 1]["first"] - 1 if k + 1 < len(out) else min(edges - 1, len(lines))
    return out


def step_at(list_: List[dict], line: int) -> Optional[dict]:
    return next((a for a in list_ if a["first"] <= line <= a["last"]), None)


def line_of(list_: List[dict], step_id: str) -> Optional[int]:
    return next((a["line"] for a in list_ if a["id"] == step_id), None)


def _read_json(path: str) -> Optional[dict]:
    try:
        with open(path, encoding="utf-8-sig") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def subflows(flow_file: str) -> Dict[str, str]:
    """The sub-flow files a flow calls (through each other too): normalized path -> run name."""
    found: Dict[str, str] = {}
    top = _norm(flow_file)

    def visit(path: str) -> None:
        for node in (_read_json(path) or {}).get("nodes") or []:
            if isinstance(node, dict) and node.get("kind") == "flow" and isinstance(node.get("file"), str):
                sub = _norm(os.path.join(os.path.dirname(path), node["file"]))
                if sub in found or sub == top:
                    continue
                flow = (_read_json(sub) or {}).get("flow")
                if not isinstance(flow, dict) or not isinstance(flow.get("name"), str):
                    continue
                found[sub] = flow["name"]
                visit(sub)

    visit(os.path.abspath(flow_file))
    return found


def _norm(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _read_text(path: str) -> str:
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


# ---- one debugged run --------------------------------------------------------

class DebugSession:
    """The debugger of one run of ``target`` (absolute; a file, or a folder)."""

    def __init__(self, root: str, target: str, *, stop_on_entry: bool = False,
                 breakpoints: Optional[Dict[str, List[int]]] = None, filters: Optional[List[str]] = None):
        self.root = os.path.abspath(root)
        self.target = os.path.abspath(target)
        self.stop_on_entry = bool(stop_on_entry)
        self.filters = list(filters or [])
        self.subs = subflows(self.target) if self.target.lower().endswith(FLOW_SUFFIX) else {}
        self._lock = threading.Lock()
        self._lines: Dict[str, List[int]] = {}          # absolute file -> lines asked for
        self._conn: Optional[socket.socket] = None
        self._buffer = b""
        self._replies: Dict[int, Tuple[threading.Event, dict]] = {}
        self._next = 1
        self.connected = False
        self.ended = False
        self.stopped: Optional[dict] = None             # {reason, description, frames}
        self.seq = 0                                    # changes whenever the state does
        self.note = ""
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(1)
        self.port = self._server.getsockname()[1]
        for path, lines in (breakpoints or {}).items():
            self._lines[self._abs(path)] = sorted({int(n) for n in lines})
        threading.Thread(target=self._accept, name="debug-accept", daemon=True).start()

    # ---- paths ----------------------------------------------------------------

    def _abs(self, path: str) -> str:
        return os.path.abspath(path if os.path.isabs(path) else os.path.join(self.root, path))

    def _rel(self, path: str) -> Optional[str]:
        """Project-relative with forward slashes, or None outside the project."""
        try:
            rel = os.path.relpath(os.path.abspath(path), self.root)
        except ValueError:          # another drive
            return None
        return None if rel.startswith("..") else rel.replace(os.sep, "/")

    # ---- the listener's connection ----------------------------------------------

    def _accept(self) -> None:
        try:
            conn, _ = self._server.accept()
        except OSError:
            return
        self._conn = conn
        threading.Thread(target=self._read, name="debug-read", daemon=True).start()

    def _send(self, msg: dict) -> None:
        conn = self._conn
        if conn is None:
            return
        try:
            conn.sendall((json.dumps(msg) + "\n").encode("utf-8"))
        except OSError:
            pass

    def _read(self) -> None:
        conn = self._conn
        while conn is not None:
            try:
                chunk = conn.recv(65536)
            except OSError:
                chunk = b""
            if not chunk:
                break
            self._buffer += chunk
            while b"\n" in self._buffer:
                line, self._buffer = self._buffer.split(b"\n", 1)
                if line.strip():
                    try:
                        self._handle(json.loads(line.decode("utf-8")))
                    except ValueError:
                        pass
        with self._lock:
            self.connected = False
            self.stopped = None
            self.seq += 1
            for event, box in self._replies.values():
                box.update(ok=False, error="The run ended.")
                event.set()

    def _handle(self, msg: dict) -> None:
        rid = msg.get("id")
        if rid is not None and rid in self._replies:
            event, box = self._replies.pop(rid)
            box.update(msg)
            event.set()
            return
        event = msg.get("event")
        with self._lock:
            if event == "hello":
                self.connected = True
                self._send({"cmd": "breakpoints", **self._listener_breakpoints()})
                self._send({"cmd": "exceptions", "filters": self.filters})
                self._send({"cmd": "configurationDone", "stopOnEntry": self.stop_on_entry, "python": False})
            elif event == "stopped":
                self.stopped = {"reason": msg.get("reason") or "", "description": msg.get("description") or "",
                                "frames": [self._frame(f) for f in msg.get("frames") or []]}
            elif event == "continued":
                self.stopped = None
            self.seq += 1

    # ---- breakpoints ------------------------------------------------------------------

    def run_name(self, path: str, step_id: str) -> Optional[str]:
        """How a step of flow file `path` is named in this run: its id, or '<sub-flow>::<id>'."""
        if _norm(path) == _norm(self.target):
            return step_id
        name = self.subs.get(_norm(path))
        return None if name is None else "%s::%s" % (name, step_id)

    def _listener_breakpoints(self) -> dict:
        nodes, lines = [], []
        for path, wanted in self._lines.items():
            if path.lower().endswith(FLOW_SUFFIX):
                steps = anchors(_read_text(path))
                for n in wanted:
                    step = step_at(steps, n)
                    name = step and self.run_name(path, step["id"])
                    if name:
                        nodes.append(name)
            else:
                lines += [[path, n] for n in wanted]
        return {"nodes": nodes, "lines": lines}

    def set_breakpoints(self, path: str, lines: List[int]) -> List[dict]:
        """The breakpoints of one file (project-relative or absolute): what each became --
        ``{line, verified, message?}``, a flow line moved to its step's ``"id"`` line."""
        full = self._abs(path)
        wanted = sorted({int(n) for n in lines})
        out = []
        if full.lower().endswith(FLOW_SUFFIX):
            steps = anchors(_read_text(full))
            for n in wanted:
                step = step_at(steps, n)
                if step is None:
                    out.append({"line": n, "verified": False, "message": "Not on a step of the flow."})
                elif self.run_name(full, step["id"]) is None:
                    out.append({"line": step["line"], "verified": False,
                                "message": "%s is not a sub-flow of this run." % os.path.basename(full)})
                else:
                    out.append({"line": step["line"], "verified": True, "step": step["id"]})
        else:
            out = [{"line": n, "verified": True} for n in wanted]
        with self._lock:
            self._lines[full] = wanted
            if self.connected:
                self._send({"cmd": "breakpoints", **self._listener_breakpoints()})
        return out

    def set_filters(self, filters: List[str]) -> None:
        with self._lock:
            self.filters = list(filters)
            if self.connected:
                self._send({"cmd": "exceptions", "filters": self.filters})

    # ---- where it stopped -----------------------------------------------------------------

    def _frame(self, f: dict) -> dict:
        """A listener frame as the GUI shows it: name, file (project-relative when inside), line."""
        node = f.get("node")
        source, line = f.get("source") or "", f.get("lineno") or 0
        name = f.get("name") or "?"
        if node:
            cut = node.rfind("::")
            if cut < 0:
                path, step = self.target, node
            else:
                path = next((p for p, n in self.subs.items() if n == node[:cut]), "")
                step = node[cut + 2:]
            if path:
                source, line = path, line_of(anchors(_read_text(path)), step) or 1
                name = "%s: %s" % (node, name)
        generated = not node and source.lower().endswith(FLOW_SUFFIX)
        known = bool(source) and not generated and os.path.isfile(source)
        out = {"name": name, "node": node, "python": bool(f.get("python")), "ref": f.get("ref"),
               "abs": os.path.abspath(source) if known else None,
               "path": self._rel(source) if known else None,
               "line": line if known else None}
        if f.get("py"):
            out["py"] = f["py"]
        if known and out["path"] is None:
            # Outside the project (a library, Robot itself): the lines around, to show read-only.
            lines = _read_text(source).splitlines()
            first = max(1, int(line or 1) - 12)
            out["snippet"] = {"first": first, "lines": lines[first - 1:first - 1 + 40]}
        return out

    # ---- commands ---------------------------------------------------------------------------

    def command(self, cmd: str) -> None:
        """continue | next | stepIn | stepOut | pause | terminate."""
        if cmd not in ("continue", "next", "stepIn", "stepOut", "pause", "terminate"):
            raise ValueError("Unknown debug command %r." % cmd)
        with self._lock:
            msg = {"cmd": cmd}
            top = (self.stopped or {}).get("frames") or [{}]
            if cmd == "stepIn" and top[0].get("py"):
                msg.update(trace=True, py=top[0]["py"])        # into the keyword's Python function
            if cmd != "pause":
                self.stopped = None
                self.seq += 1
            self._send(msg)

    def ask(self, cmd: str, **args) -> dict:
        """variables (ref) | evaluate (expression), while stopped: the listener's answer."""
        if not self.connected or self.stopped is None:
            return {"ok": False, "error": "The run is not stopped."}
        event = threading.Event()
        box: dict = {}
        with self._lock:
            rid = self._next
            self._next += 1
            self._replies[rid] = (event, box)
            self._send({"cmd": cmd, "id": rid, **args})
        if not event.wait(_ANSWER_TIMEOUT_S):
            self._replies.pop(rid, None)
            return {"ok": False, "error": "No answer from the run."}
        return {"ok": bool(box.get("ok")), "body": box.get("body"), "error": box.get("error")}

    def state(self) -> dict:
        """For the GUI's poll: where the run is stopped, if it is."""
        with self._lock:
            return {"seq": self.seq, "connected": self.connected, "ended": self.ended,
                    "stopped": self.stopped, "filters": list(self.filters), "note": self.note}

    def close(self) -> None:
        with self._lock:
            self.ended = True
            self.stopped = None
            self.seq += 1
        for s in (self._conn, self._server):
            try:
                if s is not None:
                    s.close()
            except OSError:
                pass
