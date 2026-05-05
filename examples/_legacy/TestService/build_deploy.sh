#!/usr/bin/env bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/set_env.sh"

# ----- Generate proto stubs (idempotent) -----
if [ ! -f "$SCRIPT_DIR/proto/test_service.pb.h" ]; then
    bash "$SCRIPT_DIR/proto/generate_stubs.sh"
fi

# ----- Build service -----
SERVICE_BUILD="$SCRIPT_DIR/build"
mkdir -p "$SERVICE_BUILD"
cmake -S "$SCRIPT_DIR" -B "$SERVICE_BUILD" \
    -DCMAKE_TOOLCHAIN_FILE="$VCPKG_ROOT/scripts/buildsystems/vcpkg.cmake" \
    -DCMAKE_BUILD_TYPE=Release
cmake --build "$SERVICE_BUILD" --parallel $(nproc)

# ----- Build client -----
CLIENT_BUILD="$SCRIPT_DIR/client/build"
mkdir -p "$CLIENT_BUILD"
cmake -S "$SCRIPT_DIR/client" -B "$CLIENT_BUILD" \
    -DCMAKE_TOOLCHAIN_FILE="$VCPKG_ROOT/scripts/buildsystems/vcpkg.cmake" \
    -DCMAKE_BUILD_TYPE=Release
cmake --build "$CLIENT_BUILD" --parallel $(nproc)

# ----- Collect binaries into dist/ -----
DIST="$SCRIPT_DIR/dist"
mkdir -p "$DIST"
cp "$SERVICE_BUILD/test_service"              "$DIST/" 2>/dev/null || true
cp "$CLIENT_BUILD/test_service_client"        "$DIST/" 2>/dev/null || true
cp "$CLIENT_BUILD/test_service_gui"       "$DIST/" 2>/dev/null || true

echo ""
echo "Build complete. Binaries collected in: $DIST"
