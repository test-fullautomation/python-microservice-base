# test-project

Robot Framework test projects: the **Project** tab under the left pane,
the project view, and the **Test project** group on the Developer tab.
The view is the shell's (`renderTestProjectView()` in `web/js/app.js`,
`/api/test-project/*` on the bridge); this plugin contributes where it is
reached from, so disabling it removes the tab and the group.

The view also runs tests (▶, *Run all…*, *Runs*, *Run settings…*) through
whatever runner the project names; see *Running tests* in
`docs/md/index.md`.