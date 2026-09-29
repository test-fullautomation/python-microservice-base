# robot-grid

The **Grid** tab of Robot Framework suites and resources in the project view.

- **File view `grid`** (`file.views`, `for: ["robot-grid"]`): the text in
  Script (unsaved edits included) as a grid, one row per statement. The first
  column holds the keyword a row calls (or the setting, `FOR`, `IF`, ...),
  then one cell per argument, each labelled with the parameter it fills.
  FOR / IF / TRY / WHILE bodies are indented.
- The project's runner resolves every keyword the way the run will
  (`robot_grid.py`, run with the project's interpreter): BuiltIn, the file's
  libraries and resources -- and theirs, since a resource's imports reach the
  suite -- and the file's own keywords, with Libdoc for arguments, types and
  documentation. The cells after `Run Keyword`, `Wait Until Keyword
  Succeeds` and the like are labelled with the parameters of the keyword they
  name.
- Marked in the grid: a keyword that none of the imports provides, values a
  keyword does not take, and required parameters no value reaches. Imports
  that could not be read are listed above the grid.
- Hover a keyword for its parameters (types, defaults, required) and
  documentation; click a line number to find it in Script
  (`ctx.reveal({ line })`).

**Editing** (files the user owns, open in the editor):

- Click a step to change it: an optional `${result}`, the keyword -- with
  completion over every keyword the file can call ("sh be eq" finds Should
  Be Equal; `Owner.` narrows to one library or resource) -- and one input
  per parameter of the chosen keyword: required ones marked, defaults shown,
  `*args` and `**kwargs` values added with **+**. Choosing another keyword
  carries the values over by parameter name.
- **Apply** (Enter) sends the step to the project view (`ctx.edit`), which
  has the runner apply it with Robot's own model (`robot_grid.py --edit`):
  only that step changes; indentation, separators, line endings, comments
  and every other line stay as they were. The text lands in Script as an
  unsaved change -- Save, Check and conflict detection stay Script's.
- **+ Add step** (or a **FOR / IF / WHILE / TRY** block) at the end of every
  test and keyword; in an editor, **Insert below**, **Move up / down** (a
  step or a whole block) and **Delete**; **Undo last change** puts the text
  from before a grid change back (until you type in Script).
- **Blocks:** a FOR row edits its loop variables, `IN` / `IN RANGE` / `IN
  ENUMERATE` / `IN ZIP` and values; IF / ELSE IF / WHILE their condition
  (WHILE its limit); EXCEPT its patterns and `AS` variable. From a block's
  first row: **+ ELSE IF**, **+ ELSE** (IF), **+ EXCEPT**, **+ FINALLY**
  (TRY), and deleting the block with everything in it; from a branch row,
  deleting that branch. A new block starts with one `No Operation` step
  (Robot refuses empty blocks).
- **Steps inside a block:** click its **END** row for **+ Add step here** (or
  a nested block) at the end of the block -- of the last branch for an IF or
  TRY; every block and branch row also offers **Inside: step / FOR / IF /
  ...** for the end of that part. **Insert below** on a step inside a block
  adds next to it, in the same block.
- **THREAD** (RobotFramework AIO): offered only when the project's Robot has
  it (the view data's `features.thread`). Its row edits the thread's name
  and how long it runs: until its test ends (`daemon` True) or on to the end
  of the suite (False).
- **Setups and teardowns** (`[Setup]`, `Suite Setup`, ...) use the keyword
  editor; **settings, imports and variables** (`[Documentation]`, `[Tags]`,
  `Library`, `Resource`, `${VAR}` ...) edit their values, Documentation as
  text; **+ Add setting / variable** at the end of those sections. Next to
  every test's and keyword's name: **+ Setting** (its own `[Documentation]`,
  `[Tags]`, `[Setup]`, `[Teardown]`, `[Timeout]`, `[Template]`; a keyword's
  `[Arguments]` -- the ones it has not got yet, written where Robot style
  puts them: documentation first, a teardown after the steps), **Rename**
  and **Delete**.
- The toolbar at the end adds a **test case**, **keyword**, **setting** or
  **variable** -- creating the section when the file has none.
- Every value input completes **`${variables}`** in scope at that step, the
  nearest first: `[Arguments]`, assignments and FOR / EXCEPT variables above
  it and `Set Test / Suite / Global Variable`, then the file's and its
  resources' Variables sections, then Robot's built-in ones. A typed `@{`
  or `&{` is kept.
- A skipped optional parameter makes the ones after it named
  (`name=value`); a value that would read as a named argument is escaped.
- Generated files stay read-only; so do rows the grid does not know
  (`[Template]` data rows, `RETURN` inside `IF`, ...): change them in Script.

Runs in a sandboxed frame and needs no capability: the project view pushes
the runner's data as the frame's selection (`editable` and `undo` added by
the host), and every change goes back through `ctx.edit`. `render.js` is the
markup alone (`renderGrid(data)`, `renderCard(keyword)`) and `edit.js` the
editing logic (`filterKeywords`, `slotsFor`, `argsFromSlots`,
`variablesInScope`, `variableAt`, `parseFor` ...), so both are tested
without a browser.
