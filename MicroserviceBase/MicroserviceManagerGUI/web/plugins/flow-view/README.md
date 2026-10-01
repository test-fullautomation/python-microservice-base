# flow-view

The **Diagram** tab of flow files in the project view.

- **File view `diagram`** (`file.views`, `for: ["flow-graph"]`): draws the
  flow the project's runner reports for the file (for Robot Framework flow
  files, `*.flow.json`: the RobotFramework AIO fork's own structure of the
  text in Script, unsaved edits included). One lane per phase; loops and
  tries are frames with their recovery to the right; decisions are
  diamonds whose yes / no branches re-join below.
- Clicking a node (or Enter on it) asks the project view to show that node
  in Script (`ctx.reveal({ node })`).
- **Sub-flows** (`kind: "flow"`, a call of another flow file): a box with a
  bar on each side ("predefined process"), its arguments underneath and a
  **+** that opens the sub-flow's steps in place (`render(flow, { expanded })`).
  Opened steps carry the runner's ids `'<sub-flow name>::<id>'` -- the same
  the live position reports -- and are not revealed or edited here: they
  belong to the sub-flow's own file. Live, a closed sub-flow lights its box.
- **Editing** (`editable: true` -- the file open in Script; `edit.js`):
  *Edit flow* shows a palette and drop zones (`render(flow, { edit: true })`
  draws a **+** before every step, after the last step of a region and in an
  empty decision branch). Dragging a palette item onto a **+** inserts that
  kind of step; dragging a step moves it; clicking a step opens its fields
  (Apply, Delete, Wrap in loop / try). Every change is one `ctx.edit()`:
  `{op: insert | move | delete | update | wrap, ...place}`, applied by the
  runner (`flow_edit.py`, checked by the fork's validator) to the text in
  Script, which pushes the redrawn flow back; `{op: 'undo'}` is the host's.
  One edit at a time; a drop while one is in flight says so.
- **File view `group`** (`for: ["flow-group"]`): the Diagram of a run group
  -- processes started together that wait for each other through the bench.
  One column per member, read top to bottom, and a dashed arrow across the
  channel from a step of one member to the gate of another that waits for
  it (the links come from the runner's `inspect_group`). Clicking a node
  reveals `{ member, node }`: the project view opens that member's file.

- **Live** (the Runs view): the same data with `live` -- where the run is,
  `{ node, stack, last, counts, done }` per process (for a group
  `{ <member>: position }`), from the runner's `flow_position.json` -- and
  `zoom` (`'fit'`, `0.75`, `'natural'`) and `motion` (`'tail'`, `'hop'`,
  `'off'`): how the steps in the position's `trail` that were not shown yet
  replay before the mark settles (`replay()`; at most 8, within 0.6 s). Pushed again with a new `live`, the
  drawing stays and only the marks move (`live.js`): the running step
  (`.fv-now`), the frames around it (`.fv-on-path`), a step that just failed
  (`.fv-just-failed`) and a count on each step. When the running step
  changes, the view reports where it is (`ctx.reveal({ follow, node, top,
  bottom })`, for a group `{ follow, nodes }`) so the host can keep it in
  view; sideways, at 75% / 100%, the frame does that itself.

Runs in a sandboxed frame and needs no capability: the project view pushes
the runner's data as the frame's selection (`{ flow, error?, live?, zoom? }`,
or `{ members, links, live?, zoom? }` for a group), and the view only draws
it. `flow.js` is the layout alone (`render(flow, opts)` and
`renderGroup(members, links)` return SVG markup), so it can be tested
without a browser.

Turned off under Administrator → Plugins, the Diagram tab says which
plugin draws it and where to turn it on.
