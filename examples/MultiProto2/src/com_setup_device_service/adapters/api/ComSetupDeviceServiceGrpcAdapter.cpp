#include "ComSetupDeviceServiceGrpcAdapter.h"

#include <iostream>

namespace com_setup_device_service {

// Sample implementation pattern — use this as the template for the rest
// of the RPCs in this file.
//
//   1. Read the request fields (typed accessors on the proto message).
//   2. Validate / delegate to the domain layer (m_domain).
//   3. Populate the response.
//   4. Return grpc::Status::OK.  Use grpc::Status(INVALID_ARGUMENT, ...)
//      only when the call itself was malformed (wrong wire format,
//      missing required metadata, etc.) — application-level errors
//      ("unknown interface type") belong in `response->errorcode()` so
//      the client still gets the structured payload back.
grpc::Status ComSetupDeviceServiceGrpcAdapter::SetInterfaceType(
    grpc::ServerContext* /*ctx*/,
    const ::Com_Setup_Device::InterfaceTypeRequest* request,
    ::Com_Setup_Device::CommandResponse* response) {

    // 1. Read the requested interface type.
    //    Documented values (see com_config_device.proto):
    //      0 -> RS232, 1 -> client, 2 -> NI-Visa, 3 -> AG-Visa
    const int32_t requested = request->type();
    std::cout << "[ComSetup] SetInterfaceType(" << requested << ")\n";

    // 2. Validate + (optionally) delegate to the domain.
    //    Once ComSetupDeviceService grows a real setter, swap this for:
    //        const int errorcode = m_domain.set_interface_type(requested);
    int errorcode = 0;
    switch (requested) {
        case 0:  // RS232
        case 1:  // client
        case 2:  // NI-Visa
        case 3:  // AG-Visa
            // m_domain.set_interface_type(requested);   // ← real call goes here
            errorcode = 0;                                // success
            break;
        default:
            std::cerr << "[ComSetup] SetInterfaceType: invalid type "
                      << requested << " (expected 0..3)\n";
            errorcode = -1;                               // business-level error
            break;
    }

    // 3. Populate the response.
    response->set_errorcode(errorcode);

    // 4. Wire-level status: the call succeeded — the structured payload
    //    in `response` carries the business outcome.
    return grpc::Status::OK;
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
