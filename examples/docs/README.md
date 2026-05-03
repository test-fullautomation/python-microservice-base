# MicroserviceBase Documentation

Two formats, same content:

- 📄 **Markdown** → [`md/`](md/index.md) — for terminal / IDE preview / `git grep`
- 🌐 **HTML** → [`html/index.html`](html/index.html) — open in a browser for syntax-highlighted, sidebar-navigated reading

## Layout

```
examples/docs/
├── README.md           ← you are here (GitHub-rendered landing)
├── index.html          ← redirects to html/index.html
├── md/                 ← all .md guides
│   ├── index.md
│   ├── mingw_setup.md
│   ├── qt_grpc_setup.md
│   ├── service_creation.md
│   └── wasm_cleware_service_guide.md
└── html/               ← all .html guides
    ├── index.html
    ├── mingw_setup.html
    ├── qt_grpc_setup.html
    ├── service_creation.html
    └── wasm_cleware_service_guide.html
```

Each `.md` file has a small "Also available as HTML" link at the top
pointing at its `../html/<stem>.html` peer, and vice versa for the
HTML versions. Pick whichever format fits how you're reading at the
moment — they're synchronised by hand-edit (no autogeneration).

## Contents

| Topic | Markdown | HTML |
|---|---|---|
| Overview / decision tree | [`md/index.md`](md/index.md) | [`html/index.html`](html/index.html) |
| MinGW Setup (MSYS2) | [`md/mingw_setup.md`](md/mingw_setup.md) | [`html/mingw_setup.html`](html/mingw_setup.html) |
| Qt6::Grpc Client Setup | [`md/qt_grpc_setup.md`](md/qt_grpc_setup.md) | [`html/qt_grpc_setup.html`](html/qt_grpc_setup.html) |
| Service Creator Wizard (Manager GUI) | [`md/gui_wizard.md`](md/gui_wizard.md) | [`html/gui_wizard.html`](html/gui_wizard.html) |
| Service Creation Tutorial (manual) | [`md/service_creation.md`](md/service_creation.md) | [`html/service_creation.html`](html/service_creation.html) |
| WASM Cleware Service Guide | [`md/wasm_cleware_service_guide.md`](md/wasm_cleware_service_guide.md) | [`html/wasm_cleware_service_guide.html`](html/wasm_cleware_service_guide.html) |

Start at the **overview / decision tree** if you're not sure which
guide applies.
