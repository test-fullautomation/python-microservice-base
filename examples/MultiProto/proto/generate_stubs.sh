#!/usr/bin/env bash
# Generate C++ proto + grpc stubs for all .proto files.
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for proto in com_config_device.proto power_device.proto; do
    echo "[stubs] $proto"
    protoc --proto_path="$SCRIPT_DIR" --cpp_out="$SCRIPT_DIR" --grpc_out="$SCRIPT_DIR" \
        --plugin=protoc-gen-grpc="$(which grpc_cpp_plugin)" \
        "$SCRIPT_DIR/$proto"
done
echo "[stubs] Done."
