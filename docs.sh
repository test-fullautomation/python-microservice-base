#!/usr/bin/env bash
# ===================================================================
#  Build / serve / verify the ProperDocs site (Linux / macOS / Git Bash).
#
#  Usage:
#    ./docs.sh                 Serve with live reload on http://127.0.0.1:8000
#    ./docs.sh serve [PORT]    Serve on a specific port
#    ./docs.sh build           One-off build into site/
#    ./docs.sh verify          Build, then decode every diagram and fail on errors
#    ./docs.sh open            Open the last built site in your browser
#    ./docs.sh clean           Delete site/ and the generated docs/gui, docs/examples
#
#  Override the interpreter with PYTHON_EXE, e.g.
#    PYTHON_EXE=/usr/bin/python3.12 ./docs.sh build
# ===================================================================
set -euo pipefail

cd "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null && pwd)"

# --- Interpreter ---------------------------------------------------
if [[ -z "${PYTHON_EXE:-}" ]]; then
    for candidate in \
        "/c/Program Files/RobotFramework/python3/python.exe" \
        "C:/Program Files/RobotFramework/python3/python.exe" \
        "$(command -v python3 || true)" \
        "$(command -v python || true)"
    do
        if [[ -n "$candidate" && -x "$candidate" ]]; then
            PYTHON_EXE="$candidate"
            break
        fi
    done
fi
if [[ -z "${PYTHON_EXE:-}" ]]; then
    echo "[ERROR] No Python interpreter found. Set PYTHON_EXE." >&2
    exit 1
fi

CMD="${1:-serve}"

# --- Preflight: toolchain ------------------------------------------
if ! "$PYTHON_EXE" -c "import properdocs" >/dev/null 2>&1; then
    cat >&2 <<EOF
[ERROR] properdocs is not installed for:
        $PYTHON_EXE

  Install the toolchain with:
    "$PYTHON_EXE" -m pip install properdocs properdocs-theme-readthedocs plantuml-markdown mkdocs-glightbox
EOF
    exit 1
fi

# --- Preflight: Java + PlantUML jar ---------------------------------
if [[ "$CMD" != "clean" && "$CMD" != "open" ]]; then
    command -v java >/dev/null 2>&1 || \
        echo "[WARN] java not on PATH - diagrams will render as error images." >&2

    if [[ ! -f tools/plantuml.jar ]]; then
        cat >&2 <<'EOF'
[ERROR] tools/plantuml.jar is missing (it is gitignored).

  Copy one in, e.g. from the VS Code PlantUML extension:
    cp ~/.vscode/extensions/jebbs.plantuml-*/plantuml.jar tools/

  Or download:
    curl -fsSL -o tools/plantuml.jar \
      https://github.com/plantuml/plantuml/releases/download/v1.2024.3/plantuml-1.2024.3.jar
EOF
        exit 1
    fi

    # Graph diagrams (class / component / state) need Graphviz; sequence
    # diagrams do not. Without dot they render as error images.
    command -v dot >/dev/null 2>&1 || \
        echo "[WARN] Graphviz 'dot' not found - graph diagrams may fail (apt install graphviz)." >&2
fi

open_browser() {
    local target="$1"
    if command -v xdg-open >/dev/null 2>&1;   then xdg-open "$target"
    elif command -v open >/dev/null 2>&1;     then open "$target"
    elif command -v start >/dev/null 2>&1;    then start "$target"
    else echo "Open manually: $target"
    fi
}

case "$CMD" in
    serve)
        PORT="${2:-8000}"
        echo
        echo "  Serving on http://127.0.0.1:${PORT}/"
        echo "  First render takes ~45s (25 PlantUML diagrams); edits reload in seconds."
        echo "  Press Ctrl+C to stop."
        echo
        exec "$PYTHON_EXE" -m properdocs serve --dev-addr "127.0.0.1:${PORT}"
        ;;

    build)
        echo "Building site/ ..."
        "$PYTHON_EXE" -m properdocs build --clean --strict -f properdocs.yml
        echo
        echo "[OK] Built to site/  -  run './docs.sh open' to view it."
        ;;

    verify)
        echo "Building site/ ..."
        "$PYTHON_EXE" -m properdocs build --clean --strict -f properdocs.yml
        echo
        echo "Verifying diagrams (decodes each SVG - a failed diagram renders as a"
        echo "valid image saying \"Syntax Error\", so counting them is not enough)..."
        "$PYTHON_EXE" tools/verify_diagrams.py site
        echo
        echo "[OK] Build and diagrams verified - this is what CI runs."
        ;;

    open)
        [[ -f site/index.html ]] || { echo "[ERROR] site/index.html not found - run './docs.sh build' first." >&2; exit 1; }
        open_browser site/index.html
        ;;

    clean)
        rm -rf site docs/gui docs/examples
        echo "[OK] Removed site/, docs/gui/, docs/examples/"
        ;;

    *)
        echo "Unknown command: $CMD" >&2
        echo "Usage: ./docs.sh [serve|build|verify|open|clean]" >&2
        exit 2
        ;;
esac
