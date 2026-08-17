#!/usr/bin/env bash
# Build the qt_client/ project as a multi-threaded WebAssembly module
# against the Qt 6 WebAssembly kit.
#
# Required env vars:
#   QT_WASM_DIR     Qt for WebAssembly install
#                   e.g. ~/Qt/6.11.0/wasm_multithread
#   QT_HOST_DIR     Matching desktop Qt install (same Qt version)
#                   e.g. ~/Qt/6.11.0/gcc_64 — needed for moc/rcc
#   EMSDK_DIR       emsdk root (e.g. ~/emsdk)
#
# Optional:
#   EMSDK_PYTHON    emsdk-bundled python (auto-detected under $EMSDK_DIR/python)
#
# Usage:
#   ./build_wasm.sh          Build Release
#   ./build_wasm.sh clean    Delete WASM build folder

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "${1:-}" = "clean" ]; then
    rm -rf "${SCRIPT_DIR}/build-wasm"
    echo "Cleaned."
    exit 0
fi

: "${QT_WASM_DIR:?Set QT_WASM_DIR (e.g. ~/Qt/6.11.0/wasm_multithread)}"
: "${QT_HOST_DIR:?Set QT_HOST_DIR (e.g. ~/Qt/6.11.0/gcc_64) — needed for moc/rcc}"
: "${EMSDK_DIR:?Set EMSDK_DIR to your emsdk checkout}"

[ -f "${QT_WASM_DIR}/lib/cmake/Qt6/Qt6Config.cmake" ] \
    || { echo "ERROR: Qt6 not at ${QT_WASM_DIR}"; exit 1; }
[ -f "${QT_WASM_DIR}/lib/cmake/Qt6Grpc/Qt6GrpcConfig.cmake" ] \
    || { echo "ERROR: Qt GRPC module not installed in the WASM kit at ${QT_WASM_DIR}."; \
         echo "       Install via Qt Maintenance Tool: Qt 6.x -> Qt GRPC + Qt Protobuf"; \
         echo "       (under the WebAssembly target)."; exit 1; }
[ -d "${EMSDK_DIR}/upstream/emscripten" ] \
    || { echo "ERROR: emsdk not at ${EMSDK_DIR}/upstream/emscripten"; exit 1; }

# Auto-detect EMSDK_PYTHON if user didn't set one.
if [ -z "${EMSDK_PYTHON:-}" ]; then
    EMSDK_PYTHON="$(find "${EMSDK_DIR}/python" -maxdepth 2 -name 'python3*' -type f 2>/dev/null \
                    | sort -V | tail -n 1)"
    if [ -z "${EMSDK_PYTHON}" ]; then
        EMSDK_PYTHON="$(find "${EMSDK_DIR}/python" -maxdepth 2 -name 'python' -type f 2>/dev/null \
                        | sort -V | tail -n 1)"
    fi
fi
export EMSDK_PYTHON

EMSCRIPTEN_DIR="${EMSDK_DIR}/upstream/emscripten"
export PATH="${EMSCRIPTEN_DIR}:${EMSDK_DIR}:${PATH}"
export EMSDK="${EMSDK_DIR}"

QT_TOOLCHAIN="${QT_WASM_DIR}/lib/cmake/Qt6/qt.toolchain.cmake"
EM_TOOLCHAIN="${EMSCRIPTEN_DIR}/cmake/Modules/Platform/Emscripten.cmake"
BUILD_DIR="${SCRIPT_DIR}/build-wasm"

mkdir -p "${BUILD_DIR}"

echo "Using:"
echo "  QT_WASM_DIR  = ${QT_WASM_DIR}"
echo "  QT_HOST_DIR  = ${QT_HOST_DIR}"
echo "  EMSDK_DIR    = ${EMSDK_DIR}"
echo "  EMSDK_PYTHON = ${EMSDK_PYTHON}"
echo "  BUILD_DIR    = ${BUILD_DIR}"
echo

cmake -G Ninja \
    -DCMAKE_TOOLCHAIN_FILE="${QT_TOOLCHAIN}" \
    -DQT_CHAINLOAD_TOOLCHAIN_FILE="${EM_TOOLCHAIN}" \
    -DQT_HOST_PATH="${QT_HOST_DIR}" \
    -DCMAKE_BUILD_TYPE=Release \
    -B "${BUILD_DIR}" -S "${SCRIPT_DIR}"

cmake --build "${BUILD_DIR}" --parallel

echo
echo "WASM build complete.  Output in: ${BUILD_DIR}"
echo "Serve with:    ./serve_wasm.sh"
echo "Then open:     http://127.0.0.1:8000/test_service_qt_gui.html"
