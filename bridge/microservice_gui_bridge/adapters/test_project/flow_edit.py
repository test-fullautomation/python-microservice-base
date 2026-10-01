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
"""
Edits of a flow file made in its diagram (drag and drop, the properties panel).

A flow file is nodes and edges; an edit names a place in the plan -- before or
after a node, or an empty branch of a decision -- and this module rewires the
edges so the flow stays structured: labels move with the step that leaves a
region ('next', 'continue', 'abort'), a loop or try leaves with 'done', back
edges ('next', 'continue') are never redirected. The result is checked by the
runner's own validator (the fork's ``robot.flow``) before it is accepted, and
written back in one stable layout: a node per line, an edge per line.

Edits (the ``edit`` dict):

    {"op": "insert", "kind": ..., "attrs": {...}, <place>}
    {"op": "move",   "node": id, <place>}
    {"op": "delete", "node": id}
    {"op": "update", "node": id, "attrs": {...}}       # "id" in attrs renames
    {"op": "wrap",   "node": id, "kind": "loop" | "try", "attrs": {...}}

    <place>: "before": id | "after": id | "branch": {"decision": id, "label": "yes" | "no"}

Standard library only; ``robot.flow`` is used for validation when present.
"""

import json
import re

THEN, BODY, NEXT, ON_FAILURE, CONTINUE, ABORT, DONE, YES, NO = (
    "", "body", "next", "on_failure", "continue", "abort", "done", "yes", "no")
BACK = (NEXT, CONTINUE)                       # edges that go back to a loop or try
ACTIONS = ("keyword", "gate", "sleep", "flow")
CONTAINERS = ("loop", "try")
KEY_ORDER = ("id", "kind", "role", "name", "keyword", "file", "args", "assign", "condition",
             "timeout", "interval", "on_timeout", "duration", "max_loops", "max_seconds",
             "every", "label")
PLACEHOLDER = "No Operation"


class FlowEditError(Exception):
    """The edit cannot be made; the message says why, in the flow's terms."""


# ----------------------------------------------------------------------------- entry

def apply_edit(text, edit, validate=True):
    """Return ``(new_text, node)``: the edited file and the node to show."""
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise FlowEditError(f"The file is not valid JSON ({exc}); fix it in Script first.")
    if not isinstance(data, dict) or not isinstance(data.get("nodes"), list):
        raise FlowEditError("Not a flow file: it has no 'nodes'.")
    graph = _Graph(data)
    op = (edit or {}).get("op")
    handler = {"insert": graph.insert, "move": graph.move, "delete": graph.delete,
               "update": graph.update, "wrap": graph.wrap}.get(op)
    if handler is None:
        raise FlowEditError(f"Unknown edit {op!r}.")
    node = handler(edit)
    out = graph.to_data()
    if validate:
        _validate(out)
    return dump(out), node


def _validate(data):
    try:
        from robot.flow import load_flow, structure
        from robot.errors import DataError
    except ImportError:
        return          # without the fork the runner will tell when the flow runs
    try:
        structure(load_flow(data))
    except DataError as exc:
        raise FlowEditError(f"That would not be a valid flow: {exc}")


# ---------------------------------------------------------------------------- writer

def dump(data):
    """The flow file in one stable layout: a node per line, an edge per line."""
    def one(value):
        return json.dumps(value, ensure_ascii=False)

    lines = ["{"]
    keys = [k for k in data if k not in ("nodes", "edges")] + ["nodes", "edges"]
    for i, key in enumerate(keys):
        last = i == len(keys) - 1
        value = data.get(key, [])
        if key in ("nodes", "edges"):
            items = [_ordered(n) for n in value] if key == "nodes" else value
            lines.append(f"  {one(key)}: [")
            for j, item in enumerate(items):
                lines.append(f"    {one(item)}{',' if j < len(items) - 1 else ''}")
            lines.append("  ]" + ("" if last else ","))
        else:
            lines.append(f"  {one(key)}: {one(value)}" + ("" if last else ","))
    lines.append("}")
    return "\n".join(lines) + "\n"


def _ordered(node):
    known = {k: node[k] for k in KEY_ORDER if k in node}
    known.update({k: v for k, v in node.items() if k not in known})
    return known


# ----------------------------------------------------------------------------- graph

class _Graph:

    def __init__(self, data):
        self.data = data
        self.nodes = {}
        for raw in data["nodes"]:
            if isinstance(raw, dict) and isinstance(raw.get("id"), str):
                self.nodes[raw["id"]] = raw
        self.order = [n["id"] for n in data["nodes"] if isinstance(n, dict) and "id" in n]
        self.edges = []
        for raw in data.get("edges") or []:
            if isinstance(raw, list) and len(raw) == 2:
                self.edges.append([raw[0], raw[1], THEN])
            elif isinstance(raw, dict):
                self.edges.append([raw.get("from"), raw.get("to"), raw.get("label") or THEN])

    def to_data(self):
        out = dict(self.data)
        out["nodes"] = [self.nodes[i] for i in self.order]
        out["edges"] = [[s, t] if label == THEN else {"from": s, "to": t, "label": label}
                        for s, t, label in self.edges]
        return out

    # ---- queries

    def kind(self, id):
        return self._node(id).get("kind")

    def _node(self, id):
        if id not in self.nodes:
            raise FlowEditError(f"There is no node '{id}'.")
        return self.nodes[id]

    def incoming(self, id):
        """Edges that lead *forward* into ``id`` (not the back edges of a loop)."""
        return [e for e in self.edges if e[1] == id and e[2] not in BACK]

    def outgoing(self, id):
        return [e for e in self.edges if e[0] == id]

    def exit_edge(self, id):
        """The one edge a step continues with: an action's only edge, a loop's or try's
        'done' (or 'next' / 'continue' / 'abort' when it is the last of a region)."""
        kind = self.kind(id)
        if kind in ACTIONS:
            outs = self.outgoing(id)
            if len(outs) != 1:
                raise FlowEditError(f"'{id}' should have exactly one way out.")
            return outs[0]
        if kind in CONTAINERS:
            outs = [e for e in self.outgoing(id) if e[2] in (DONE, NEXT, CONTINUE, ABORT)]
            if len(outs) != 1:
                raise FlowEditError(f"'{id}' has no single way out.")
            return outs[0]
        raise FlowEditError(f"A {kind} node has no single way out.")

    def new_id(self, base):
        base = re.sub(r"[^a-z0-9_]+", "_", str(base).lower()).strip("_") or "step"
        name, n = base, 1
        while name in self.nodes:
            n += 1
            name = f"{base}_{n}"
        return name

    # ---- primitive rewiring

    def _add_node(self, node, near=None):
        self.nodes[node["id"]] = node
        index = self.order.index(near) + 1 if near in self.order else len(self.order) - 1
        if self.order and self.order[-1] in self.nodes and self.kind(self.order[-1]) == "end" \
                and index > len(self.order) - 1:
            index = len(self.order) - 1
        self.order.insert(index, node["id"])

    def _place(self, edit):
        """Normalise a place to (predecessor-edges to redirect, target, label for the new node's way out)."""
        if edit.get("branch"):
            branch = edit["branch"]
            decision, label = branch.get("decision"), branch.get("label")
            if self.kind(decision) != "decision" or label not in (YES, NO):
                raise FlowEditError("A branch is a decision's 'yes' or 'no'.")
            (edge,) = [e for e in self.outgoing(decision) if e[2] == label] or [None]
            if edge is None:
                raise FlowEditError(f"'{decision}' has no '{label}' branch.")
            return [edge], edge[1], THEN
        if edit.get("before") is not None:
            target = edit["before"]
            kind = self.kind(target)
            if kind == "start":
                raise FlowEditError("Nothing can come before the start.")
            ins = self.incoming(target)
            if not ins:
                raise FlowEditError(f"Nothing leads to '{target}'.")
            return ins, target, THEN
        if edit.get("after") is not None:
            source = edit["after"]
            kind = self.kind(source)
            if kind in ("end",):
                raise FlowEditError("Nothing can come after the end.")
            if kind in ("start", "phase"):
                (edge,) = self.outgoing(source)
                return [edge], edge[1], THEN
            if kind == "decision":
                raise FlowEditError("Drop it before the step where the branches meet.")
            edge = self.exit_edge(source)
            if kind in CONTAINERS:
                # The loop was the last of a region: now the new step is.
                label = edge[2] if edge[2] != DONE else THEN
                edge[2] = DONE
                return [edge], edge[1], label
            label = edge[2]
            edge[2] = THEN
            return [edge], edge[1], label
        raise FlowEditError("Say where: before or after a node, or into a branch.")

    def _splice(self, preds, target, way_out, first, last=None, exit_label=None):
        """Put the region ``first`` .. ``last`` between ``preds`` and ``target``."""
        for edge in preds:
            edge[1] = first
        last = last or first
        if exit_label is not None:          # a loop or try leaves with 'done' (or the region's label)
            self.edges.append([last, target, way_out if way_out in (NEXT, CONTINUE, ABORT) else exit_label])
        else:
            self.edges.append([last, target, way_out])

    # ---- edits

    def insert(self, edit):
        kind = edit.get("kind")
        attrs = dict(edit.get("attrs") or {})
        if kind not in ACTIONS + CONTAINERS + ("decision", "phase"):
            raise FlowEditError(f"Cannot insert a {kind!r} node.")
        node_id = attrs.pop("id", None) or self.new_id(attrs.get("keyword") or attrs.get("name") or kind)
        if node_id in self.nodes:
            raise FlowEditError(f"There is a node '{node_id}' already.")
        node = {"id": node_id, "kind": kind, **attrs}
        if kind == "keyword" and not node.get("keyword"):
            node["keyword"] = PLACEHOLDER
        if kind == "gate":
            node.setdefault("keyword", "Should Be True")
            node.setdefault("timeout", "30s")
        if kind == "sleep":
            node.setdefault("duration", "1s")
        if kind == "decision":
            node.setdefault("condition", "${True}")
        if kind == "loop" and not node.get("max_loops") and not node.get("max_seconds"):
            node["max_loops"] = 3
        if kind == "phase":
            node.setdefault("role", "test")
            if node["role"] == "test":
                node.setdefault("name", "New Test")
        near = edit.get("after") or edit.get("before")
        preds, target, way_out = self._place(edit)
        self._add_node(node, near)
        if kind in CONTAINERS:
            body = {"id": self.new_id(f"{node_id}_step"), "kind": "keyword", "keyword": PLACEHOLDER}
            self._add_node(body, node_id)
            self.edges += [[node_id, body["id"], BODY], [body["id"], node_id, NEXT]]
            self._splice(preds, target, way_out, node_id, exit_label=DONE)
        elif kind == "decision":
            for edge in preds:
                edge[1] = node_id
            if way_out != THEN:
                raise FlowEditError("A decision cannot be the last step of a loop body or a "
                                    "recovery; add it before another step.")
            self.edges += [[node_id, target, YES], [node_id, target, NO]]
        else:
            self._splice(preds, target, way_out, node_id)
        return node_id

    def delete(self, edit, keep=False):
        node_id = edit.get("node")
        kind = self.kind(node_id)
        if kind in ("start", "end"):
            raise FlowEditError(f"The {kind} node stays.")
        if kind == "phase":
            raise FlowEditError("Delete the phase's steps first, then the phase in Script.")
        if kind == "decision":
            branches = {e[2]: e[1] for e in self.outgoing(node_id)}
            if branches.get(YES) != branches.get(NO):
                raise FlowEditError(f"Empty both branches of '{node_id}' first.")
            exit_target, exit_label = branches[YES], THEN
            removed = {node_id}
        elif kind in CONTAINERS:
            removed = self._region(node_id) | {node_id}
            exit_target, exit_label = self.exit_edge(node_id)[1:]
            if exit_label == DONE:
                exit_label = THEN
        else:
            exit_target, exit_label = self.exit_edge(node_id)[1:]
            removed = {node_id}
        ins = self.incoming(node_id)
        self.edges = [e for e in self.edges if e[0] not in removed and e[1] not in removed]
        for source, _, label in ins:
            if source in removed:
                continue
            merged = _merge(label, exit_label, source, node_id)
            if merged is None:          # a recovery that becomes empty: no recovery
                continue
            self.edges.append([source, exit_target, merged])
        for gone in removed:
            if not keep or gone != node_id:
                self.nodes.pop(gone, None)
        self.order = [i for i in self.order if i in self.nodes]
        return exit_target

    def move(self, edit):
        node_id = edit.get("node")
        if self.kind(node_id) not in ACTIONS:
            raise FlowEditError("Only a step (keyword, gate, sleep, sub-flow) can be moved; "
                                "cut a loop, try or decision in Script.")
        target = edit.get("before") or edit.get("after") or (edit.get("branch") or {}).get("decision")
        if target == node_id:
            return node_id
        node = self.nodes[node_id]
        self.delete({"node": node_id})
        place = {k: edit[k] for k in ("before", "after", "branch") if edit.get(k) is not None}
        attrs = {k: v for k, v in node.items() if k not in ("kind",)}
        return self.insert(dict(place, op="insert", kind=node["kind"], attrs=attrs))

    def update(self, edit):
        node_id = edit.get("node")
        node = self._node(node_id)
        attrs = dict(edit.get("attrs") or {})
        new_id = attrs.pop("id", node_id) or node_id
        for key, value in attrs.items():
            if key == "kind":
                continue
            if value is None or value == "" or value == [] or value == {}:
                node.pop(key, None)
            else:
                node[key] = value
        if new_id != node_id:
            if new_id in self.nodes:
                raise FlowEditError(f"There is a node '{new_id}' already.")
            node["id"] = new_id
            self.nodes[new_id] = self.nodes.pop(node_id)
            self.order = [new_id if i == node_id else i for i in self.order]
            for edge in self.edges:
                edge[0] = new_id if edge[0] == node_id else edge[0]
                edge[1] = new_id if edge[1] == node_id else edge[1]
        return new_id

    def wrap(self, edit):
        node_id = edit.get("node")
        kind = edit.get("kind")
        if kind not in CONTAINERS:
            raise FlowEditError("Wrap a step in a loop or a try.")
        if self.kind(node_id) not in ACTIONS + CONTAINERS:
            raise FlowEditError("Only a step, loop or try can be wrapped.")
        attrs = dict(edit.get("attrs") or {})
        wrapper = attrs.pop("id", None) or self.new_id(kind)
        node = {"id": wrapper, "kind": kind, **attrs}
        if kind == "loop" and not node.get("max_loops") and not node.get("max_seconds"):
            node["max_loops"] = 3
        exit_edge = self.exit_edge(node_id)
        target, label = exit_edge[1], exit_edge[2]
        for edge in self.incoming(node_id):
            edge[1] = wrapper
        self.nodes[wrapper] = node
        self.order.insert(self.order.index(node_id), wrapper)
        # The step now ends the body: it returns to the wrapper.
        exit_edge[1], exit_edge[2] = wrapper, NEXT
        self.edges.append([wrapper, node_id, BODY])
        self.edges.append([wrapper, target, label if label in (NEXT, CONTINUE, ABORT) else DONE])
        return wrapper

    def _region(self, container):
        """Every node inside a loop's or try's body and recovery (nested ones too)."""
        try:
            from robot.flow import load_flow, structure
            from robot.flow import graph
        except ImportError:
            raise FlowEditError("Deleting a loop or try needs the RobotFramework AIO fork.")
        flow = structure(load_flow(self.to_data()))
        found = set()

        def walk(steps):
            for step in steps or []:
                if step.id == container:
                    collect(step.body)
                    collect(step.recovery)
                    return True
                for part in ("yes", "no", "body", "recovery"):
                    if walk(getattr(step, part, None)):
                        return True
            return False

        def collect(steps):
            for step in steps or []:
                found.add(step.id)
                for part in ("yes", "no", "body", "recovery"):
                    collect(getattr(step, part, None))

        for phase in [flow.setup, *flow.tests, flow.teardown]:
            if phase and walk(phase.steps):
                break
        # Ends of a branch that re-join inside the region are steps of it too.
        return found


def _merge(into_label, out_label, source, removed):
    """The label of the edge that replaces source -> removed -> target."""
    if into_label == THEN:
        return out_label
    if out_label == THEN:
        return into_label
    if into_label == DONE and out_label in (NEXT, CONTINUE, ABORT):
        return out_label                       # the loop before it is now the last of the region
    if into_label == ON_FAILURE and out_label in (CONTINUE, ABORT):
        return None                            # the recovery is gone
    if into_label == BODY and out_label == NEXT:
        raise FlowEditError(f"'{removed}' is the only step of the body of '{source}'; "
                            f"a body cannot be empty -- delete '{source}' instead.")
    if into_label in (YES, NO) and out_label in (NEXT, CONTINUE, ABORT):
        raise FlowEditError(f"'{removed}' is the only step of the '{into_label}' branch at the end "
                            f"of a region; leave a step there.")
    raise FlowEditError(f"Cannot join '{source}' to what follows '{removed}' "
                        f"({into_label} / {out_label}).")
