#!/usr/bin/env bash
# ===================================================================
# generate_stubs.sh — Generate C++ gRPC stubs from a .proto file.
#
# Run this ONCE after receiving the .proto from the service team.
# The generated files go into gen/ and are regular C++ source that
# you include in your project — no protoc needed for day-to-day builds.
#
# Usage:
#   ./generate_stubs.sh                              (uses defaults)
#   ./generate_stubs.sh proto/hello.proto gen         (custom paths)
#
# Prerequisites:
#   - protoc and grpc_cpp_plugin on PATH, or installed via vcpkg.
# ===================================================================

set -e

PROTO_FILE="${1:-proto/hello.proto}"
OUT_DIR="${2:-gen}"

# ----- Find tools -----
if ! command -v protoc &>/dev/null; then
    if [ -n "$VCPKG_ROOT" ]; then
        export PATH="$VCPKG_ROOT/installed/x64-linux/tools/protobuf:$VCPKG_ROOT/installed/x64-linux/tools/grpc:$PATH"
    fi
fi

if ! command -v protoc &>/dev/null; then
    echo "ERROR: protoc not found."
    echo "       Install via: vcpkg install protobuf grpc"
    echo "       Or: sudo apt-get install protobuf-compiler"
    exit 1
fi

GRPC_PLUGIN=$(command -v grpc_cpp_plugin 2>/dev/null || true)
if [ -z "$GRPC_PLUGIN" ]; then
    echo "ERROR: grpc_cpp_plugin not found."
    echo "       Install via: vcpkg install grpc"
    exit 1
fi

# ----- Generate -----
mkdir -p "$OUT_DIR"

PROTO_DIR=$(dirname "$PROTO_FILE")

echo ""
echo "===== Generating C++ gRPC stubs ====="
echo "  Proto:   $PROTO_FILE"
echo "  Output:  $OUT_DIR"
echo ""

protoc \
    --proto_path="$PROTO_DIR" \
    --cpp_out="$OUT_DIR" \
    --grpc_out="$OUT_DIR" \
    --plugin=protoc-gen-grpc="$GRPC_PLUGIN" \
    "$PROTO_FILE"

echo "===== Generated files ====="
ls -1 "$OUT_DIR"/*.h "$OUT_DIR"/*.cc 2>/dev/null
echo ""
echo "Done. Include these files in your project and build normally."
echo "You do NOT need protoc for day-to-day development after this step."
