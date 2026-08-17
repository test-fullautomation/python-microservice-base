# MicroserviceBase Documentation

Two formats, same content:

- 📄 **Markdown** → [`md/`](md/index.md) — for terminal / IDE preview / `git grep`
- 🌐 **HTML** → [`html/index.html`](md/index.md) — open in a browser for syntax-highlighted, sidebar-navigated reading

## Layout

```
examples/docs/
├── README.md           ← you are here (GitHub-rendered landing)
├── index.html          ← redirects to html/index.html
├── md/                 ← all .md guides
│   ├── index.md
│   ├── mingw_setup.md
│   ├── qt_grpc_setup.md
│   ├── vcpkg_setup.md
│   ├── service_creation.md
│   └── wasm_cleware_service_guide.md
└── html/               ← all .html guides (mirror of md/)
```

Each `.md` file has a small "Also available as HTML" link at the top
pointing at its `../html/<stem>.html` peer, and vice versa for the
HTML versions. Pick whichever format fits how you're reading at the
moment — they're synchronised by hand-edit (no autogeneration).

## Scope

This folder contains **toolchain setup** + **per-feature walkthrough**
guides. The Manager GUI docs (Service Network ops, Service Creator
wizard) live alongside the GUI itself at
[`../../MicroserviceBase/MicroserviceManagerGUI/docs/`](../../MicroserviceBase/MicroserviceManagerGUI/docs/).

## Contents

| Topic | Markdown | HTML |
|---|---|---|
| Overview / decision tree | [`md/index.md`](md/index.md) | [`html/index.html`](md/index.md) |
| MinGW Setup (MSYS2) | [`md/mingw_setup.md`](md/mingw_setup.md) | [`html/mingw_setup.html`](md/mingw_setup.md) |
| Qt6::Grpc Client Setup | [`md/qt_grpc_setup.md`](md/qt_grpc_setup.md) | [`html/qt_grpc_setup.html`](md/qt_grpc_setup.md) |
| vcpkg + Qt MinGW Setup *(recommended for new teams)* | [`md/vcpkg_setup.md`](md/vcpkg_setup.md) | [`html/vcpkg_setup.html`](md/vcpkg_setup.md) |
| Service Creation Tutorial (manual) | [`md/service_creation.md`](md/service_creation.md) | [`html/service_creation.html`](md/service_creation.md) |
| WASM Cleware Service Guide | [`md/wasm_cleware_service_guide.md`](md/wasm_cleware_service_guide.md) | [`html/wasm_cleware_service_guide.html`](md/wasm_cleware_service_guide.md) |

### Manager GUI guides (live with the GUI)

| Topic | Markdown | HTML |
|---|---|---|
| Operating Consul + Nomad | [`../../MicroserviceBase/MicroserviceManagerGUI/docs/md/ops_consul_nomad.md`](../../MicroserviceBase/MicroserviceManagerGUI/docs/md/ops_consul_nomad.md) | [`../../MicroserviceBase/MicroserviceManagerGUI/docs/html/ops_consul_nomad.html`](../../MicroserviceBase/MicroserviceManagerGUI/docs/md/ops_consul_nomad.md) |
| Service Creator Wizard | [`../../MicroserviceBase/MicroserviceManagerGUI/docs/md/service_creator.md`](../../MicroserviceBase/MicroserviceManagerGUI/docs/md/service_creator.md) | [`../../MicroserviceBase/MicroserviceManagerGUI/docs/html/service_creator.html`](../../MicroserviceBase/MicroserviceManagerGUI/docs/md/service_creator.md) |

Start at the **overview / decision tree** if you're not sure which
guide applies.
