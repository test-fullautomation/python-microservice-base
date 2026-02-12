# ADR-004: Electron over Qt for GUI Framework

## Status

Accepted

## Date

2026-02-12

## Author

Nguyen Huynh Tri Cuong (MS/EMC51)

## Reviewer

- Nguyen Huynh Tri Cuong (MS/EMC51)

## History

| Date | Version | Description |
|------|---------|-------------|
| 2026-02-12 | 1.0 | Initial version |

## Context

MicroserviceBase needs a desktop GUI to manage services, view status, configure
aliases, and interact with service-specific panels.  A critical architectural
property is that **services deliver their own GUI as HTML/CSS/JS files** at
runtime.  The manager application downloads these files (as a ZIP via RPC),
extracts them into `web/services/<ServiceName>/`, and dynamically loads them
into the main window.

This means the GUI framework must act as a **full HTML renderer** with:

- Dynamic `innerHTML` injection and `<script>` loading for service plugins
- Full DOM API, ES6+, `fetch()`, `WebSocket`, Bootstrap 5 CDN
- Two-way communication between the native shell and the web layer

The question is: **which desktop framework should host this HTML-based GUI?**

### Candidates

| Framework | Rendering Engine | Scope |
|-----------|-----------------|-------|
| **Electron** | Chromium + Node.js | Cross-platform desktop shell |
| **Qt + WebEngine** | Chromium (stripped) | Cross-platform native toolkit with embedded browser |
| **Qt without WebEngine** | Qt Widgets / QML (no browser) | Native-only UI |
| **MFC + WebView2** | Chromium (Edge) | Windows-only native shell |

## Decision

Use **Electron** as the GUI framework.

The core reasoning: since services deliver HTML GUIs, we need a full browser
engine regardless of which framework we choose.  Electron provides Chromium
natively with the simplest integration path for a web-first application.

## Pro/Con Comparison

### Electron

| | Detail |
|---|---|
| **Pro** | Service HTML/JS/CSS plugins render identically to any browser -- zero compatibility risk |
| **Pro** | `contextBridge` + preload provides clean, secure Native-to-JS API surface |
| **Pro** | Single codebase runs in Electron AND plain browser (our dual-host architecture, ADR-005) |
| **Pro** | No build step -- `web/` folder is plain HTML/JS loadable by `file://` or FastAPI |
| **Pro** | Largest ecosystem for desktop-web hybrid apps (VS Code, Slack, Teams, 1Password) |
| **Pro** | MIT license -- no commercial restrictions |
| **Pro** | 8-week release cycle tracks latest Chromium security patches |
| **Pro** | Cross-platform: Windows, macOS, Linux (x64, ARM64) |
| **Con** | Bundle size ~120 MB (ships full Chromium + Node.js) |
| **Con** | Higher memory baseline (~200-300 MB idle) than native toolkits |
| **Con** | Each Electron app bundles its own Chromium (no shared runtime) |
| **Con** | Chromium CVEs require shipping updated builds to users |

### Qt with WebEngine

| | Detail |
|---|---|
| **Pro** | Qt provides native widgets alongside the web view (menus, dialogs, system tray) |
| **Pro** | `QWebChannel` enables Python-to-JS communication (similar to `contextBridge`) |
| **Pro** | Cross-platform: Windows, macOS, Linux |
| **Pro** | Can mix native Qt widgets with embedded web panels |
| **Con** | **Still bundles Chromium** -- `libQtWebEngineCore` alone is ~111 MB; total 70-300 MB depending on platform |
| **Con** | Chromium version updates only every ~6 months (lags behind Electron's 8-week cycle) |
| **Con** | `QWebEngineView` has no direct DOM access -- must use `runJavaScript()` for all interactions |
| **Con** | Dynamic plugin injection (our `innerHTML` + `<script>` pattern) works but requires careful world-isolation management (`QWebEngineScript` injection points) |
| **Con** | LGPL v3 license -- must distribute Qt source and allow library replacement, or purchase commercial license |
| **Con** | **No dual-host benefit** -- our `web/` code would need Qt-specific adaptations, losing the "open in any browser" capability |
| **Con** | Python integration via PyQt/PySide adds an extra binding layer on top of WebChannel |
| **Con** | Smaller ecosystem for desktop-web hybrid apps; fewer community examples for dynamic plugin architectures |

### Qt without WebEngine (Native Widgets / QML Only)

| | Detail |
|---|---|
| **Pro** | Smallest bundle size (~10-30 MB) |
| **Pro** | Lowest memory footprint |
| **Pro** | True native look and feel on each platform |
| **Con** | **Cannot render service HTML GUIs at all** -- services would need to deliver Qt-native UIs instead of HTML |
| **Con** | Breaks the core architectural property: services can no longer deliver portable HTML GUIs |
| **Con** | Every service author must learn Qt/QML instead of standard web technologies |
| **Con** | Loses all web ecosystem tooling (Bootstrap, CDN libraries, browser DevTools) |
| **Con** | Two completely different skill sets (Python + Qt vs Python + HTML/JS) |

### MFC + WebView2 (Windows Only)

| | Detail |
|---|---|
| **Pro** | WebView2 uses system Edge runtime -- near-zero additional size (~1.7 MB installer) |
| **Pro** | Monthly Chromium updates via Edge |
| **Pro** | Service HTML GUIs render correctly (Chromium engine) |
| **Con** | **Windows only** -- no macOS, no Linux |
| **Con** | MFC is legacy (C++ only, no Python bindings, no modern tooling) |
| **Con** | COM-based communication between native and web layers is complex |
| **Con** | Proprietary Microsoft licensing |
| **Con** | No dual-host browser mode |

## The Service-Delivered GUI Argument

This is the decisive factor.  The MicroserviceBase architecture allows any
service to ship its own GUI:

```
Service (Python) ──RPC──> svc_api_get_gui_files() ──ZIP──> Manager GUI
                                                            │
                                                            ▼
                                                   web/services/MyService1.0.0/
                                                   ├── MyService.html
                                                   ├── MyService.js
                                                   └── MyService.css
```

The manager loads these dynamically:

```javascript
fetch('services/MyService1.0.0/MyService.html')
  .then(r => r.text())
  .then(html => {
    wrapper.innerHTML = html;                // inject HTML
    var s = document.createElement('script');
    s.src = 'services/MyService1.0.0/MyService.js';
    document.head.appendChild(s);            // load JS
  });
```

This pattern requires a **real browser engine**.  The implications:

| Requirement | Electron | Qt+WebEngine | Qt Native | MFC+WebView2 |
|-------------|----------|--------------|-----------|---------------|
| Render service HTML/CSS/JS | Yes | Yes (via `runJavaScript`) | **No** | Yes |
| Dynamic `innerHTML` + `<script>` | Native | Needs world isolation care | **N/A** | Yes |
| Same code works in standalone browser | Yes | No (needs Qt adaptations) | **N/A** | No |
| Service authors use web skills only | Yes | Mostly (some Qt quirks) | **No** | Mostly |
| Full DOM API / ES6+ / WebSocket / fetch | Yes | Yes | **No** | Yes |

**Qt without WebEngine is ruled out** because it fundamentally breaks the
service-delivered GUI architecture.  Services would need to ship Qt-native code
instead of HTML, requiring every service author to learn Qt/QML and eliminating
cross-renderer portability.

Among the frameworks that embed Chromium (Electron, Qt+WebEngine, WebView2),
Electron wins because:

1. **Dual-host architecture** (ADR-005) -- our `web/` code runs in both Electron
   and any plain browser.  Qt+WebEngine would lock us into Qt.
2. **Simpler plugin injection** -- `innerHTML` + `<script>` just works.
   Qt requires `QWebEngineScript` injection-point management.
3. **License** -- MIT vs LGPL/Commercial.
4. **Ecosystem** -- the largest community for desktop-web hybrid apps.

## Consequences

### Positive

- Service authors write standard HTML/CSS/JS -- works in any browser, no framework lock-in
- Dual-host architecture means the GUI works without Electron at all (browser + FastAPI)
- 8-week Chromium update cadence for timely security patches
- Huge ecosystem of community plugins, examples, and tooling
- MIT license -- no compliance overhead

### Negative

- ~120 MB bundle size per installation (Chromium + Node.js)
- Higher memory usage than a pure-native application
- Must ship Electron updates when Chromium CVEs are published
- Chromium CVEs in the past (e.g., CVE-2025-10585, CVE-2025-55305) affect Electron apps

### Neutral

- Qt+WebEngine would have similar bundle size and memory characteristics (same Chromium engine)
- If cross-platform is ever dropped (Windows-only), WebView2 could be reconsidered as a lighter alternative
- Performance for our use case (management UI, not real-time rendering) is more than sufficient with Electron

## Alternatives Considered

### 1. Qt with WebEngine (Rejected)

Full Qt application with QWebEngineView for service HTML rendering.

Rejected because:
- Still bundles Chromium (~111 MB core lib), so no meaningful size advantage
- Breaks dual-host architecture -- `web/` code would need Qt-specific changes
- LGPL license adds compliance requirements or commercial license cost
- Chromium version lags ~6 months behind Electron
- Dynamic plugin injection is more complex (world isolation, `runJavaScript()`)

### 2. Qt without WebEngine (Rejected)

Pure Qt Widgets/QML application -- no web rendering.

Rejected because:
- **Fundamentally incompatible** with service-delivered HTML GUIs
- Would require every service to ship Qt-native UI instead of HTML
- Eliminates cross-renderer portability and browser-based access entirely
- Different skill set (Qt/QML vs web) for service GUI development

### 3. MFC + WebView2 (Rejected)

Windows-only MFC shell with embedded Edge WebView2.

Rejected because:
- Windows only -- no macOS/Linux support
- MFC is legacy C++ with no Python bindings
- COM-based IPC is significantly more complex than `contextBridge`
- No dual-host browser mode
- Proprietary licensing

### 4. Tauri (Deferred)

Rust-based alternative using system webview (WebView2 on Windows, WebKit on macOS/Linux).

Deferred because:
- Promising smaller bundle (~5-10 MB) by using system webview
- However: different rendering engines per platform (Edge vs WebKit) could cause service GUI inconsistencies
- Smaller ecosystem and less mature than Electron
- Requires Rust toolchain for native modules
- Worth re-evaluating as the project matures

## References

- Source: `MicroserviceBase/MicroserviceManagerGUI/electron/`, `MicroserviceBase/MicroserviceManagerGUI/web/`
- Related: ADR-005 (Dual-Host GUI Architecture), ADR-006 (FastAPI Bridge for Browser GUI)
- Qt WebEngine docs: https://doc.qt.io/qt-6/qtwebengine-overview.html
- Electron docs: https://www.electronjs.org/docs
- WebView2 docs: https://learn.microsoft.com/en-us/microsoft-edge/webview2/
