#!/usr/bin/env bash
# Generate C++ gRPC stubs from test_service.proto.
# Run once, then both service and client can build without protoc.
set -e
PROTO_DIR="$(cd "$(dirname "$0")" && pwd)"

# Pull VCPKG_ROOT from the central set_env.sh in the project root.
if [ -f "$PROTO_DIR/../set_env.sh" ]; then
    source "$PROTO_DIR/../set_env.sh"
fi

# ----- Find tools -----
PROTOC=$(command -v protoc 2>/dev/null || true)
GRPC_PLUGIN=$(command -v grpc_cpp_plugin 2>/dev/null || true)

if [ -z "$PROTOC" ] && [ -n "$VCPKG_ROOT" ]; then
    PROTOC="$VCPKG_ROOT/installed/x64-linux/tools/protobuf/protoc"
fi
if [ -z "$GRPC_PLUGIN" ] && [ -n "$VCPKG_ROOT" ]; then
    GRPC_PLUGIN="$VCPKG_ROOT/installed/x64-linux/tools/grpc/grpc_cpp_plugin"
fi

if [ -z "$PROTOC" ] || [ ! -f "$PROTOC" ]; then
    echo "ERROR: protoc not found. Set VCPKG_ROOT or install protobuf."
    exit 1
fi
if [ -z "$GRPC_PLUGIN" ] || [ ! -f "$GRPC_PLUGIN" ]; then
    echo "ERROR: grpc_cpp_plugin not found. Set VCPKG_ROOT or install grpc."
    exit 1
fi

echo "protoc:          $PROTOC"
echo "grpc_cpp_plugin: $GRPC_PLUGIN"
echo ""
echo "Generating stubs from test_service.proto into $PROTO_DIR ..."

"$PROTOC" --proto_path="$PROTO_DIR" \
    --cpp_out="$PROTO_DIR" \
    --grpc_out="$PROTO_DIR" \
    --plugin=protoc-gen-grpc="$GRPC_PLUGIN" \
    "$PROTO_DIR/test_service.proto"

echo ""
echo "Done. Both service and client can now build without protoc."
