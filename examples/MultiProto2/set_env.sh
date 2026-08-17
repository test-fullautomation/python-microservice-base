#!/usr/bin/env bash
# Central environment for native (gcc/clang) builds.
#
# THESE VALUES ALWAYS OVERWRITE whatever is in the parent shell.  Edit
# them directly to match your machine — that way a previous bad export
# can't stick around and break subsequent runs.

export VCPKG_ROOT="$HOME/vcpkg"

# CMake / Ninja — absolute paths (leave empty to use system PATH).
export CMAKE_DIR=""
export NINJA_DIR=""
[ -n "$CMAKE_DIR" ] && [ -x "$CMAKE_DIR/cmake" ] && export PATH="$CMAKE_DIR:$PATH"
[ -n "$NINJA_DIR" ] && [ -x "$NINJA_DIR/ninja" ] && export PATH="$NINJA_DIR:$PATH"

# Compiler — leave empty for the system default (gcc/clang).
export CC=""
export CXX=""
export QT_DIR="$HOME/Qt/6.7.1/gcc_64"

echo "==== set_env applied ===="
echo "  VCPKG_ROOT = $VCPKG_ROOT"
echo "  CMAKE_DIR  = $CMAKE_DIR"
echo "  NINJA_DIR  = $NINJA_DIR"
echo "  CC / CXX   = $CC / $CXX"
echo "  QT_DIR     = $QT_DIR"
echo "========================="
