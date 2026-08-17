#!/usr/bin/env bash
# Pre-generate Qt6::Protobuf + Qt6::Grpc client stubs from every .proto
# in THIS folder.  One-shot helper; the CMake build does the same thing
# via qt_add_protobuf / qt_add_grpc.

set -euo pipefail

PROTO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
: "${QT_DIR:?Set QT_DIR to your Qt install prefix}"

PROTOC="${PROTOC:-$(command -v protoc || true)}"
[[ -n "$PROTOC" ]] || { echo "protoc not found"; exit 1; }

QTPB_PLUGIN="$QT_DIR/bin/qtprotobufgen"
QTGRPC_PLUGIN="$QT_DIR/bin/qtgrpcgen"
[[ -x "$QTPB_PLUGIN"   ]] || { echo "qtprotobufgen not found at $QTPB_PLUGIN"; exit 1; }
[[ -x "$QTGRPC_PLUGIN" ]] || { echo "qtgrpcgen not found at $QTGRPC_PLUGIN"; exit 1; }

shopt -s nullglob
protos=("$PROTO_DIR"/*.proto)
shopt -u nullglob
if [ ${#protos[@]} -eq 0 ]; then
    echo "WARN: no .proto files found in $PROTO_DIR"
    exit 1
fi

for proto in "${protos[@]}"; do
    echo "Generating stubs for $(basename "$proto")"
    "$PROTOC" \
        --plugin=protoc-gen-qtprotobuf="$QTPB_PLUGIN" \
        --qtprotobuf_out="$PROTO_DIR" \
        --proto_path="$PROTO_DIR" \
        "$proto"

    "$PROTOC" \
        --plugin=protoc-gen-qtgrpc="$QTGRPC_PLUGIN" \
        --qtgrpc_opt=GENERATE_PACKAGE_SUBFOLDERS=false \
        --qtgrpc_out="$PROTO_DIR" \
        --proto_path="$PROTO_DIR" \
        "$proto"
done

echo "Qt stubs generated in $PROTO_DIR"
