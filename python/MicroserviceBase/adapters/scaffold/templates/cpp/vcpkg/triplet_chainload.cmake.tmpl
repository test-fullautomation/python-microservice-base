# Chainloaded CMake toolchain - pins compilers to Qt's MinGW 13.1.0.
# Override via env var QT_MINGW_BIN if Qt is installed elsewhere.

set(CMAKE_SYSTEM_NAME Windows)
set(CMAKE_SYSTEM_PROCESSOR x86_64)

if(DEFINED ENV{QT_MINGW_BIN})
    set(_qt_mingw_bin "$ENV{QT_MINGW_BIN}")
else()
    set(_qt_mingw_bin "C:/Qt/Tools/mingw1310_64/bin")
endif()

if(NOT EXISTS "${_qt_mingw_bin}/g++.exe")
    message(FATAL_ERROR
        "Qt MinGW not found at: ${_qt_mingw_bin}\n"
        "Set QT_MINGW_BIN env var to your Qt installer's MinGW bin/ folder.")
endif()

set(CMAKE_C_COMPILER   "${_qt_mingw_bin}/gcc.exe")
set(CMAKE_CXX_COMPILER "${_qt_mingw_bin}/g++.exe")
set(CMAKE_RC_COMPILER  "${_qt_mingw_bin}/windres.exe")
set(CMAKE_AR           "${_qt_mingw_bin}/ar.exe"     CACHE FILEPATH "" FORCE)
set(CMAKE_RANLIB       "${_qt_mingw_bin}/ranlib.exe" CACHE FILEPATH "" FORCE)

set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)
