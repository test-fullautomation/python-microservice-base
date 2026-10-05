# GUI probes

End-to-end checks of the Manager GUI as users get it: the real
`web/index.html` with the real preload, in Electron, driven with real
mouse and keyboard input.

```bash
npm run test:gui                     # all probes
node test/gui/run.js view_roles      # only probes whose file name contains "view_roles"
```

| Variable | Meaning |
|---|---|
| `MB_GUI_TEST_PYTHON` | Interpreter with `MicroserviceBase` installed, for probes that start a bridge (default `python`). Without one, those probes skip what needs it. |
| `MB_FLOW_SRC` | `src` folder of a RobotFramework AIO checkout, for the flow Diagram checks. |
| `MB_GUI_TEST_SHOW=1` | Show the windows while the probes run. |

## How a probe works

Each `test_gui_*.js` is an Electron main script, run by `run.js` in its own
Electron process. It uses `harness.js`:

- `t.open({ query, storage, bridge })` opens the GUI; `query` becomes the
  page's address query (`{ view: 'user' }`), `storage` is put in local
  storage before the app starts.
- `g.click(selector)` and `g.type(selector, text)` send real input events
  (`sendInputEvent`), so focus, hit testing and pointer handlers take part —
  not `element.click()`.
- `g.visible`, `g.waitFor`, `g.waitForSelector`, `g.js` read the page.
- `t.check(label, ok, detail)` records a check; a failed one saves a
  screenshot under `test/gui/output/` (ignored by git).
- Every probe ends with a check that the page logged no errors.

Output follows `test/endo`: one line per check, then `N passed, M failed`;
the exit code is 1 on any failure.

## Isolation

A probe can run on a developer PC or a bench PC without touching what runs
there:

- Electron's `userData` is a fresh temporary folder: the user's settings,
  local storage and installed plugins are neither read nor written.
- A probe that needs the bridge starts its own on a free port and stops it
  (with its child processes) at the end. The GUI is pointed at that bridge;
  the desktop app's default would reach the user's bridge on 1112.
- Test projects are created in temporary folders.
- The page's calls to the Electron main process (window plugins, native
  dialogs) get neutral answers; probes of those need the real main process.

## Probes

| File | Covers | Needs |
|---|---|---|
| `test_gui_view_roles.js` | `?view=` roles: tabs shown or hidden, views outside the roles refused, ribbon opens on click | nothing |
| `test_gui_tile_groups.js` | tile groups: headers before their first tile, full-width rows, a collapsed group hidden *and* suspended, expand with the mouse, collapse with Enter, a hidden component resuming only open groups, the choice remembered, `mountComponent` with `groups` | nothing |
| `test_gui_project_flows.js` | project view: the Flows **+**, the New flow form, a refused name, the created file and its imports, opening on the Diagram; with the fork: the drawing and *Edit flow* | bridge Python; `MB_FLOW_SRC` for the Diagram |

Write a new probe as `test_gui_<topic>.js`; `run.js` picks it up.
