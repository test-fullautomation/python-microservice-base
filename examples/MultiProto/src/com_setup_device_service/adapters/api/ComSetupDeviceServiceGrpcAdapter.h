#pragma once

#include "com_config_device.grpc.pb.h"
#include "../../domain/ComSetupDeviceService.h"

namespace com_setup_device_service {

// gRPC adapter: thin wrapper translating proto messages <-> domain calls.
class ComSetupDeviceServiceGrpcAdapter final
    : public ::Com_Setup_Device::ComSetupDeviceService::Service {
public:
    explicit ComSetupDeviceServiceGrpcAdapter(ComSetupDeviceService& domain) : m_domain(domain) {}

    grpc::Status SetInterfaceType(grpc::ServerContext* ctx,
        const ::Com_Setup_Device::InterfaceTypeRequest* request,
        ::Com_Setup_Device::CommandResponse* response) override;
    grpc::Status GetInterfaceType(grpc::ServerContext* ctx,
        const ::Com_Setup_Device::Empty* request,
        ::Com_Setup_Device::GetInterfaceTypeResponse* response) override;
    grpc::Status SetInterfaceConfig(grpc::ServerContext* ctx,
        const ::Com_Setup_Device::SetInterfaceConfigRequest* request,
        ::Com_Setup_Device::CommandResponse* response) override;
    grpc::Status GetInterfaceConfig(grpc::ServerContext* ctx,
        const ::Com_Setup_Device::SetInterfaceConfigRequest* request,
        ::Com_Setup_Device::GetInterfaceConfigResponse* response) override;
    grpc::Status LoadInterfaceConfig(grpc::ServerContext* ctx,
        const ::Com_Setup_Device::LoadInterfaceConfigRequest* request,
        ::Com_Setup_Device::CommandResponse* response) override;
    grpc::Status Connect(grpc::ServerContext* ctx,
        const ::Com_Setup_Device::Empty* request,
        ::Com_Setup_Device::CommandResponse* response) override;
    grpc::Status DisConnect(grpc::ServerContext* ctx,
        const ::Com_Setup_Device::Empty* request,
        ::Com_Setup_Device::CommandResponse* response) override;
    grpc::Status GetConnectState(grpc::ServerContext* ctx,
        const ::Com_Setup_Device::Empty* request,
        ::Com_Setup_Device::GetConnectStateResponse* response) override;

private:
    ComSetupDeviceService& m_domain;
};

}  // namespace com_setup_device_service
