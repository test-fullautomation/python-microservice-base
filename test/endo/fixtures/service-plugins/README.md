# Service plugin fixtures

Packages as a service would serve them over `ServiceGui` (ADR-031): the
folder named by the service's `Meta.gui`, holding the `plugin.json` named by
its `Meta.gui_plugin`. They stand in for the session manager and the
configuration hub while those services do not deliver a GUI yet.

| Folder | Plugin | Stands in for | Shows |
|---|---|---|---|
| `SessionsDemo0.1.0` | `sessions-demo` | a session manager | a navigator and a stage view of the same id; `binds.grpc`; a call to another service (`binds.uses`) and how to read its error |
| `ConfigDemo0.1.0` | `config-demo` | the configuration hub | a navigator and a drawer tab |
| `RefusedDemo0.1.0` | `refused-demo` | a plugin that overreaches | `shell` entries, which a service plugin may not use: refused |

Used by `test/endo/test_endo_plugins.js` (they lint clean, or are refused,
as a service's plugins) and `test/gui/test_gui_service_plugins.js` (offered,
blocked until allowed, applied, bound to their service, gone with it).

The GUI probe runs without a bridge. The modules report the service their
`ctx` is bound to with `ctx.notify`, which the probe reads. The sessions
page calls the catalog (named in `binds.uses`) with a timeout and metadata
and reports the error code, detail types and request id; the probe plays
the bridge and fails that call the way a service does. Its call to a
service it does not name is refused by the GUI.
