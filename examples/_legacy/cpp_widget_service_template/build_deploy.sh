#!/usr/bin/env bash
# ===================================================================
# build_deploy.sh — Build MyWidgetService + MyWidgetServicePreview
#                   and collect all executables and runtime libraries
#                   into deploy/
# ===================================================================
#
# Usage:
#   ./build_deploy.sh              Build Release (default)
#   ./build_deploy.sh debug        Build Debug
#   ./build_deploy.sh clean        Delete build + deploy folders
#
# Prerequisites:
#   - Qt 6 installed (gcc_64 or clang_64 kit)
#   - vcpkg with librabbitmq and nlohmann-json installed
#   - CMake 3.21+ and Ninja (or Make)
#
# Output:
#   deploy/
#   ├── MyWidgetService             Backend service
#   ├── MyWidgetServicePreview      Widget UI preview
#   ├── service_config.json         Service configuration
#   ├── ui/ServiceUI.ui             Widget UI file
#   ├── GUIs/ServiceUI.ui           Deployed copy (for svc_api_get_gui_files)
#   ├── lib/                        Qt shared libraries
#   └── plugins/                    Qt platform plugins
# ===================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ----- Configurable paths (edit these if your setup differs) -----
# Auto-detect Qt installation
if [ -z "${QT_DIR:-}" ]; then
    for candidate in \
        "$HOME/Qt/6.7.1/gcc_64" \
        "$HOME/Qt/6.*/gcc_64" \
        "/opt/Qt/6.7.1/gcc_64" \
        "/usr/lib/qt6" \
        ; do
        # shellcheck disable=SC2086
        resolved=$(echo $candidate)
        if [ -d "$resolved" ]; then
            QT_DIR="$resolved"
            break
        fi
    done
fi

if [ -z "${VCPKG_ROOT:-}" ]; then
    # Try to read from CMakePresets.json
    if [ -f "$SCRIPT_DIR/CMakePresets.json" ]; then
        tc=$(grep -oP '"toolchainFile"\s*:\s*"\K[^"]+' "$SCRIPT_DIR/CMakePresets.json" 2>/dev/null || true)
        if [ -n "$tc" ]; then
            VCPKG_ROOT="$(dirname "$(dirname "$(dirname "$tc")")")"
        fi
    fi
    # Fallback
    : "${VCPKG_ROOT:=$HOME/vcpkg}"
fi

VCPKG_TOOLCHAIN="$VCPKG_ROOT/scripts/buildsystems/vcpkg.cmake"

# ----- Parse arguments -----
BUILD_TYPE="Release"
PRESET="release"

case "${1:-}" in
    debug|Debug)
        BUILD_TYPE="Debug"
        PRESET="default"
        ;;
    clean)
        echo "Cleaning build and deploy folders..."
        rm -rf "$SCRIPT_DIR/build" "$SCRIPT_DIR/deploy"
        echo "Done."
        exit 0
        ;;
esac

BUILD_DIR="$SCRIPT_DIR/build/$PRESET"
DEPLOY_DIR="$SCRIPT_DIR/deploy"

# ----- Validate prerequisites -----
if ! command -v cmake &>/dev/null; then
    echo "ERROR: cmake not found. Install CMake 3.21+."
    exit 1
fi

if [ -n "${QT_DIR:-}" ] && [ -d "$QT_DIR" ]; then
    echo "Using Qt at: $QT_DIR"
    export PATH="$QT_DIR/bin:$PATH"
    export CMAKE_PREFIX_PATH="$QT_DIR:${CMAKE_PREFIX_PATH:-}"
else
    echo "WARNING: QT_DIR not set or not found. Trying system Qt..."
fi

if [ ! -f "$VCPKG_TOOLCHAIN" ]; then
    echo "WARNING: vcpkg toolchain not found at $VCPKG_TOOLCHAIN"
    echo "         Backend build may fail. Set VCPKG_ROOT if needed."
fi

# ----- Configure -----
echo ""
echo "===== Configuring CMake [$BUILD_TYPE] ====="

# Use preset if available and toolchain exists, otherwise manual configure
if [ -f "$VCPKG_TOOLCHAIN" ]; then
    cmake --preset "$PRESET" "$SCRIPT_DIR"
else
    mkdir -p "$BUILD_DIR"
    cmake -S "$SCRIPT_DIR" -B "$BUILD_DIR" \
        -DCMAKE_BUILD_TYPE="$BUILD_TYPE"
fi

# ----- Build -----
echo ""
echo "===== Building ====="
cmake --build "$BUILD_DIR" --config "$BUILD_TYPE"

# ----- Deploy -----
echo ""
echo "===== Deploying to $DEPLOY_DIR ====="

rm -rf "$DEPLOY_DIR"
mkdir -p "$DEPLOY_DIR"

# Copy executables
FOUND_BACKEND=0
if [ -f "$BUILD_DIR/MyWidgetService" ]; then
    cp "$BUILD_DIR/MyWidgetService" "$DEPLOY_DIR/"
    echo "  Copied MyWidgetService"
    FOUND_BACKEND=1
fi
if [ -f "$BUILD_DIR/MyWidgetServicePreview" ]; then
    cp "$BUILD_DIR/MyWidgetServicePreview" "$DEPLOY_DIR/"
    echo "  Copied MyWidgetServicePreview"
fi

# Copy service config
if [ -f "$SCRIPT_DIR/service_config.json" ]; then
    cp "$SCRIPT_DIR/service_config.json" "$DEPLOY_DIR/"
    echo "  Copied service_config.json"
fi

# Copy UI files
if [ -d "$SCRIPT_DIR/ui" ]; then
    cp -r "$SCRIPT_DIR/ui" "$DEPLOY_DIR/ui"
    echo "  Copied ui/"
fi

# Copy GUIs folder (.ui file served by MyWidgetService via svc_api_get_gui_files)
if [ -d "$SCRIPT_DIR/GUIs" ]; then
    cp -r "$SCRIPT_DIR/GUIs" "$DEPLOY_DIR/GUIs"
    echo "  Copied GUIs/"
fi

# ----- Collect shared library dependencies -----
echo ""
echo "===== Collecting runtime libraries ====="

mkdir -p "$DEPLOY_DIR/lib"

# Try macdeployqt / linuxdeployqt if available
if [ "$(uname)" = "Darwin" ] && command -v macdeployqt &>/dev/null; then
    echo "  Running macdeployqt..."
    macdeployqt "$DEPLOY_DIR/MyWidgetServicePreview" \
        -always-overwrite 2>/dev/null || true
elif command -v linuxdeployqt &>/dev/null; then
    echo "  Running linuxdeployqt..."
    linuxdeployqt "$DEPLOY_DIR/MyWidgetServicePreview" \
        -always-overwrite 2>/dev/null || true
else
    # Manual: copy Qt libraries
    echo "  No deploy tool found. Copying Qt libraries manually..."
    if [ -n "${QT_DIR:-}" ] && [ -d "$QT_DIR/lib" ]; then
        for lib in Core Gui Widgets UiTools Network OpenGL; do
            src="$QT_DIR/lib/libQt6${lib}.so.6"
            if [ -f "$src" ]; then
                cp -L "$src" "$DEPLOY_DIR/lib/"
                echo "    libQt6${lib}.so.6"
            fi
        done

        # Copy platform plugin
        if [ -d "$QT_DIR/plugins/platforms" ]; then
            mkdir -p "$DEPLOY_DIR/plugins/platforms"
            cp "$QT_DIR/plugins/platforms/libqxcb.so" \
               "$DEPLOY_DIR/plugins/platforms/" 2>/dev/null || true
            echo "    Platform plugin (xcb)"
        fi
    fi
fi

# Copy vcpkg shared libraries (rabbitmq-c)
if [ "$FOUND_BACKEND" = "1" ]; then
    VCPKG_LIB_DIR=""
    if [ -d "$VCPKG_ROOT/installed/x64-linux/lib" ]; then
        VCPKG_LIB_DIR="$VCPKG_ROOT/installed/x64-linux/lib"
    elif [ -d "$VCPKG_ROOT/installed/x64-osx/lib" ]; then
        VCPKG_LIB_DIR="$VCPKG_ROOT/installed/x64-osx/lib"
    fi
    if [ -n "$VCPKG_LIB_DIR" ]; then
        for lib in "$VCPKG_LIB_DIR"/librabbitmq*; do
            [ -f "$lib" ] && cp -L "$lib" "$DEPLOY_DIR/lib/" && echo "    $(basename "$lib")"
        done
    fi
fi

# Create launcher scripts with LD_LIBRARY_PATH
cat > "$DEPLOY_DIR/run_service.sh" << 'LAUNCHER'
#!/usr/bin/env bash
DIR="$(cd "$(dirname "$0")" && pwd)"
export LD_LIBRARY_PATH="$DIR/lib:${LD_LIBRARY_PATH:-}"
export QT_PLUGIN_PATH="$DIR/plugins:${QT_PLUGIN_PATH:-}"
exec "$DIR/MyWidgetService" "$@"
LAUNCHER
chmod +x "$DEPLOY_DIR/run_service.sh"

cat > "$DEPLOY_DIR/run_preview.sh" << 'LAUNCHER'
#!/usr/bin/env bash
DIR="$(cd "$(dirname "$0")" && pwd)"
export LD_LIBRARY_PATH="$DIR/lib:${LD_LIBRARY_PATH:-}"
export QT_PLUGIN_PATH="$DIR/plugins:${QT_PLUGIN_PATH:-}"
exec "$DIR/MyWidgetServicePreview" "$@"
LAUNCHER
chmod +x "$DEPLOY_DIR/run_preview.sh"

echo "  Created run_service.sh and run_preview.sh"

# ----- Summary -----
echo ""
echo "===== Build complete ====="
echo ""
echo "  Build type:  $BUILD_TYPE"
echo "  Output:      $DEPLOY_DIR"
echo ""
echo "  Executables:"
[ -f "$DEPLOY_DIR/MyWidgetService" ]        && echo "    MyWidgetService              (backend service)"
[ -f "$DEPLOY_DIR/MyWidgetServicePreview" ] && echo "    MyWidgetServicePreview       (widget UI preview)"
[ ! -f "$DEPLOY_DIR/MyWidgetService" ]      && echo "    [MyWidgetService not built — backend deps may be missing]"
echo ""
echo "  To run:"
echo "    cd $DEPLOY_DIR"
echo "    ./run_service.sh                          # backend"
echo "    ./run_preview.sh                          # widget UI preview (stub mode)"
echo "    ./run_preview.sh --live                   # widget UI preview (live RabbitMQ)"
echo "    ./run_preview.sh --live --broker host:port"
echo ""
