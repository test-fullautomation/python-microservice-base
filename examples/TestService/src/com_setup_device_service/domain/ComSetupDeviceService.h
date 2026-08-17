#pragma once

// Domain layer for ComSetupDeviceService.
// Pure C++ — no gRPC, no Consul.

#include <string>

namespace com_setup_device_service {

class ComSetupDeviceService {
public:
    // TODO: add your methods here.  Expected API surface:
    // rpc SetInterfaceType(...)  -  wire in adapters/api/ComSetupDeviceServiceGrpcAdapter.cpp
    // rpc GetInterfaceType(...)  -  wire in adapters/api/ComSetupDeviceServiceGrpcAdapter.cpp
    // rpc SetInterfaceConfig(...)  -  wire in adapters/api/ComSetupDeviceServiceGrpcAdapter.cpp
    // rpc GetInterfaceConfig(...)  -  wire in adapters/api/ComSetupDeviceServiceGrpcAdapter.cpp
    // rpc LoadInterfaceConfig(...)  -  wire in adapters/api/ComSetupDeviceServiceGrpcAdapter.cpp
    // rpc Connect(...)  -  wire in adapters/api/ComSetupDeviceServiceGrpcAdapter.cpp
    // rpc DisConnect(...)  -  wire in adapters/api/ComSetupDeviceServiceGrpcAdapter.cpp
    // rpc GetConnectState(...)  -  wire in adapters/api/ComSetupDeviceServiceGrpcAdapter.cpp
};

}  // namespace com_setup_device_service
