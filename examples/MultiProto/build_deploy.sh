#!/usr/bin/env bash
# Build the MultiProto multi-service binary.
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/set_env.sh"
cmake -S "$SCRIPT_DIR" -B "$SCRIPT_DIR/build" -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build "$SCRIPT_DIR/build" --config Release
echo "[build] OK -> $SCRIPT_DIR/build/multi_proto"
