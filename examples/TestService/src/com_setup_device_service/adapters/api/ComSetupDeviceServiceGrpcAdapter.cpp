#include "ComSetupDeviceServiceGrpcAdapter.h"

namespace com_setup_device_service {

grpc::Status ComSetupDeviceServiceGrpcAdapter::SetInterfaceType(
    grpc::ServerContext* /*ctx*/,
    const ::Com_Setup_Device::InterfaceTypeRequest* /*request*/,
    ::Com_Setup_Device::CommandResponse* /*response*/) {
    // TODO: read fields from `request`, call m_domain, populate `response`.
    return grpc::Status(grpc::StatusCode::UNIMPLEMENTED, "TODO: implement SetInterfaceType");
}

grpc::Status ComSetupDeviceServiceGrpcAdapter::GetInterfaceType(
    grpc::ServerContext* /*ctx*/,
    const ::Com_Setup_Device::Empty* /*request*/,
    ::Com_Setup_Device::GetInterfaceTypeResponse* /*response*/) {
    // TODO: read fields from `request`, call m_domain, populate `response`.
    return grpc::Status(grpc::StatusCode::UNIMPLEMENTED, "TODO: implement GetInterfaceType");
}

grpc::Status ComSetupDeviceServiceGrpcAdapter::SetInterfaceConfig(
    grpc::ServerContext* /*ctx*/,
    const ::Com_Setup_Device::SetInterfaceConfigRequest* /*request*/,
    ::Com_Setup_Device::CommandResponse* /*response*/) {
    // TODO: read fields from `request`, call m_domain, populate `response`.
    return grpc::Status(grpc::StatusCode::UNIMPLEMENTED, "TODO: implement SetInterfaceConfig");
}

grpc::Status ComSetupDeviceServiceGrpcAdapter::GetInterfaceConfig(
    grpc::ServerContext* /*ctx*/,
    const ::Com_Setup_Device::SetInterfaceConfigRequest* /*request*/,
    ::Com_Setup_Device::GetInterfaceConfigResponse* /*response*/) {
    // TODO: read fields from `request`, call m_domain, populate `response`.
    return grpc::Status(grpc::StatusCode::UNIMPLEMENTED, "TODO: implement GetInterfaceConfig");
}

grpc::Status ComSetupDeviceServiceGrpcAdapter::LoadInterfaceConfig(
    grpc::ServerContext* /*ctx*/,
    const ::Com_Setup_Device::LoadInterfaceConfigRequest* /*request*/,
    ::Com_Setup_Device::CommandResponse* /*response*/) {
    // TODO: read fields from `request`, call m_domain, populate `response`.
    return grpc::Status(grpc::StatusCode::UNIMPLEMENTED, "TODO: implement LoadInterfaceConfig");
}

grpc::Status ComSetupDeviceServiceGrpcAdapter::Connect(
    grpc::ServerContext* /*ctx*/,
    const ::Com_Setup_Device::Empty* /*request*/,
    ::Com_Setup_Device::CommandResponse* /*response*/) {
    // TODO: read fields from `request`, call m_domain, populate `response`.
    return grpc::Status(grpc::StatusCode::UNIMPLEMENTED, "TODO: implement Connect");
}

grpc::Status ComSetupDeviceServiceGrpcAdapter::DisConnect(
    grpc::ServerContext* /*ctx*/,
    const ::Com_Setup_Device::Empty* /*request*/,
    ::Com_Setup_Device::CommandResponse* /*response*/) {
    // TODO: read fields from `request`, call m_domain, populate `response`.
    return grpc::Status(grpc::StatusCode::UNIMPLEMENTED, "TODO: implement DisConnect");
}

grpc::Status ComSetupDeviceServiceGrpcAdapter::GetConnectState(
    grpc::ServerContext* /*ctx*/,
    const ::Com_Setup_Device::Empty* /*request*/,
    ::Com_Setup_Device::GetConnectStateResponse* /*response*/) {
    // TODO: read fields from `request`, call m_domain, populate `response`.
    return grpc::Status(grpc::StatusCode::UNIMPLEMENTED, "TODO: implement GetConnectState");
}

}  // namespace com_setup_device_service
