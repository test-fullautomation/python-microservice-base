#!/usr/bin/env bash
# Central environment variables for this project.
#
# Edit the defaults below, then every build script (build_deploy.sh,
# proto/generate_stubs.sh, build_wasm.sh) sources this file.
#
# Variables already set in the shell are NOT overwritten, so CI and
# users with global exports still work.

: "${VCPKG_ROOT:=$HOME/vcpkg}"
export VCPKG_ROOT

# CMake / Ninja — point these at your installs if they are NOT on PATH.
: "${CMAKE_DIR:=}"
: "${NINJA_DIR:=}"
[ -n "$CMAKE_DIR" ] && [ -x "$CMAKE_DIR/cmake" ] && export PATH="$CMAKE_DIR:$PATH"
[ -n "$NINJA_DIR" ] && [ -x "$NINJA_DIR/ninja" ] && export PATH="$NINJA_DIR:$PATH"

# Compiler — override if the system default (gcc/clang) is not what you want.
: "${CC:=}"
: "${CXX:=}"
[ -n "$CC" ]  && export CC
[ -n "$CXX" ] && export CXX

# Qt install prefix — needed by the Widgets GUI client (find_package(Qt6)).
: "${QT_DIR:=$HOME/Qt/6.7.1/gcc_64}"
export QT_DIR

