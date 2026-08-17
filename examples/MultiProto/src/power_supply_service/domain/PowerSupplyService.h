#pragma once

// Domain layer for PowerSupplyService.
// Pure C++ — no gRPC, no Consul.

#include <string>

namespace power_supply_service {

class PowerSupplyService {
public:
    // TODO: add your methods here.  Expected API surface:
    // rpc SetSubDeviceType(...)  -  wire in adapters/api/PowerSupplyServiceGrpcAdapter.cpp
    // rpc GetSubDeviceType(...)  -  wire in adapters/api/PowerSupplyServiceGrpcAdapter.cpp
    // rpc GetSubDeviceTypeChannelCount(...)  -  wire in adapters/api/PowerSupplyServiceGrpcAdapter.cpp
    // rpc GetSubDeviceType_ListCount(...)  -  wire in adapters/api/PowerSupplyServiceGrpcAdapter.cpp
    // rpc GetSubDeviceType_ID(...)  -  wire in adapters/api/PowerSupplyServiceGrpcAdapter.cpp
    // rpc GetSubDeviceType_Name(...)  -  wire in adapters/api/PowerSupplyServiceGrpcAdapter.cpp
    // rpc InitDevice(...)  -  wire in adapters/api/PowerSupplyServiceGrpcAdapter.cpp
    // rpc SetVoltage(...)  -  wire in adapters/api/PowerSupplyServiceGrpcAdapter.cpp
    // rpc SetCurrentLimit(...)  -  wire in adapters/api/PowerSupplyServiceGrpcAdapter.cpp
    // rpc SetOutputEnabled(...)  -  wire in adapters/api/PowerSupplyServiceGrpcAdapter.cpp
    // rpc ReadCurrent(...)  -  wire in adapters/api/PowerSupplyServiceGrpcAdapter.cpp
    // rpc ReadVoltage(...)  -  wire in adapters/api/PowerSupplyServiceGrpcAdapter.cpp
};

}  // namespace power_supply_service
