cmake_minimum_required(VERSION 3.16)
project(TestServiceClient VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Auto-detect vcpkg from VCPKG_ROOT env var or parent CMakePresets.json
if(NOT CMAKE_TOOLCHAIN_FILE)
    if(DEFINED ENV{VCPKG_ROOT})
        set(CMAKE_TOOLCHAIN_FILE "$ENV{VCPKG_ROOT}/scripts/buildsystems/vcpkg.cmake"
            CACHE PATH "vcpkg toolchain")
    endif()
endif()
if(CMAKE_TOOLCHAIN_FILE AND EXISTS "${CMAKE_TOOLCHAIN_FILE}")
    get_filename_component(_vr "${CMAKE_TOOLCHAIN_FILE}" DIRECTORY)
    get_filename_component(_vr "${_vr}" DIRECTORY)
    get_filename_component(_vr "${_vr}" DIRECTORY)
    if(EXISTS "${_vr}/installed/x64-windows/share")
        list(APPEND CMAKE_PREFIX_PATH "${_vr}/installed/x64-windows")
    endif()
endif()

find_package(gRPC     CONFIG REQUIRED)
find_package(Protobuf CONFIG REQUIRED)

# MicroserviceBase runtime — provides ServiceClient<T>
add_subdirectory(
    "${CMAKE_CURRENT_SOURCE_DIR}/../../../MicroserviceBase/runtime_cpp"
    "${CMAKE_CURRENT_BINARY_DIR}/microservice_base_runtime"
)

# Proto stubs — shared with the service via ../proto/.
# Run proto/generate_stubs.bat (Win) or .sh (Linux) once from the
# parent project.  The generated .pb.h/.pb.cc files live in proto/.
set(PROTO_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../proto")

set(STUB_SRCS
    "${PROTO_DIR}/test_service.pb.cc"
    "${PROTO_DIR}/test_service.grpc.pb.cc"
)

# Check that stubs exist.
if(NOT EXISTS "${PROTO_DIR}/test_service.pb.h")
    message(FATAL_ERROR
        "Proto stubs not found in ${PROTO_DIR}.\n"
        "Run proto/generate_stubs.bat (Win) or .sh (Linux) first.")
endif()

add_executable(test_service_client
    src/client.cpp
    ${STUB_SRCS}
)

target_include_directories(test_service_client PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}/src"
    "${PROTO_DIR}"
)

target_link_libraries(test_service_client PRIVATE
    microservice_base::runtime
    gRPC::grpc++
    protobuf::libprotobuf
)

# ----- Qt Widgets GUI client (test_service_gui) ------------------------------
# Qt 6 discovery: honour QT_DIR / Qt6_DIR env vars (set in set_env.bat/.sh).
#   QT_DIR   = Qt install prefix, e.g. C:\Qt\6.7.1\msvc2019_64
#   Qt6_DIR  = directory containing Qt6Config.cmake (overrides QT_DIR)
if(NOT DEFINED Qt6_DIR AND DEFINED ENV{Qt6_DIR})
    set(Qt6_DIR "$ENV{Qt6_DIR}" CACHE PATH "Qt6 config dir")
endif()
if(DEFINED ENV{QT_DIR} AND NOT Qt6_DIR)
    list(APPEND CMAKE_PREFIX_PATH "$ENV{QT_DIR}")
endif()

find_package(Qt6 COMPONENTS Core Gui Widgets REQUIRED)
qt_standard_project_setup()
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTOUIC ON)
set(CMAKE_AUTOUIC_SEARCH_PATHS "${CMAKE_CURRENT_SOURCE_DIR}/gui")

qt_add_executable(test_service_gui
    gui/main.cpp
    gui/MainWindow.cpp
    gui/MainWindow.h
    gui/MainWindow.ui
    ${STUB_SRCS}
)

target_include_directories(test_service_gui PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}/gui"
    "${PROTO_DIR}"
)

target_link_libraries(test_service_gui PRIVATE
    microservice_base::runtime
    gRPC::grpc++
    protobuf::libprotobuf
    Qt6::Widgets
)

set_target_properties(test_service_gui PROPERTIES
    WIN32_EXECUTABLE OFF
    MACOSX_BUNDLE    ON
)
