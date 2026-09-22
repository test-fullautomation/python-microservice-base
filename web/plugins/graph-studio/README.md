# graph-studio

A `window` plugin: the vendored Signal Graph Studio in its own
BrowserWindow. Its code stays in `graph-studio/` next to `web/` (it runs
Python and `grpcurl`, so the packaged app unpacks it from the asar);
`graph-studio/ipc.js` is the main module (`register()`, `open()`,
`shutdown()`), loaded by `electron/plugins-main.js`. Only in the desktop
app. See `graph-studio/README.md` for the editor itself.