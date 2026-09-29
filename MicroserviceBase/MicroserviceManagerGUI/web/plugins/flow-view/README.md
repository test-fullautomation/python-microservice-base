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
