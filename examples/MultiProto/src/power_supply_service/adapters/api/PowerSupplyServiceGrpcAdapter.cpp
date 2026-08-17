#include "PowerSupplyServiceGrpcAdapter.h"

namespace power_supply_service {

grpc::Status PowerSupplyServiceGrpcAdapter::SetSubDeviceType(
    grpc::ServerContext* /*ctx*/,
    const ::power_device::SubDeviceTypeRequest* /*request*/,
    ::power_device::CommandResponse* /*response*/) {
    // TODO: read fields from `request`, call m_domain, populate `response`.
    return grpc::Status(grpc::StatusCode::UNIMPLEMENTED, "TODO: implement SetSubDeviceType");
}

grpc::Status PowerSupplyServiceGrpcAdapter::GetSubDeviceType(
    grpc::ServerContext* /*ctx*/,
    const ::power_device::Empty* /*request*/,
    ::power_device::GetSubDeviceTypeResponse* /*response*/) {
    // TODO: read fields from `request`, call m_domain, populate `response`.
    return grpc::Status(grpc::StatusCode::UNIMPLEMENTED, "TODO: implement GetSubDeviceType");
}

grpc::Status PowerSupplyServiceGrpcAdapter::GetSubDeviceTypeChannelCount(
    grpc::ServerContext* /*ctx*/,
    const ::power_device::Empty* /*request*/,
    ::power_device::ChannelCountResponse* /*response*/) {
    // TODO: read fields from `request`, call m_domain, populate `response`.
    return grpc::Status(grpc::StatusCode::UNIMPLEMENTED, "TODO: implement GetSubDeviceTypeChannelCount");
}

grpc::Status PowerSupplyServiceGrpcAdapter::GetSubDeviceType_ListCount(
    grpc::ServerContext* /*ctx*/,
    const ::power_device::Empty* /*request*/,
    ::power_device::GetSubDeviceTypeListCountResponse* /*response*/) {
    // TODO: read fields from `request`, call m_domain, populate `response`.
    return grpc::Status(grpc::StatusCode::UNIMPLEMENTED, "TODO: implement GetSubDeviceType_ListCount");
}

grpc::Status PowerSupplyServiceGrpcAdapter::GetSubDeviceType_ID(
    grpc::ServerContext* /*ctx*/,
    const ::power_device::SubDeviceTypeRequest* /*request*/,
    ::power_device::GetSubDeviceTypeIDResponse* /*response*/) {
    // TODO: read fields from `request`, call m_domain, populate `response`.
    return grpc::Status(grpc::StatusCode::UNIMPLEMENTED, "TODO: implement GetSubDeviceType_ID");
}

grpc::Status PowerSupplyServiceGrpcAdapter::GetSubDeviceType_Name(
    grpc::ServerContext* /*ctx*/,
    const ::power_device::SubDeviceTypeRequest* /*request*/,
    ::power_device::GetSubDeviceTypeNameResponse* /*response*/) {
    // TODO: read fields from `request`, call m_domain, populate `response`.
    return grpc::Status(grpc::StatusCode::UNIMPLEMENTED, "TODO: implement GetSubDeviceType_Name");
}

grpc::Status PowerSupplyServiceGrpcAdapter::InitDevice(
    grpc::ServerContext* /*ctx*/,
    const ::power_device::Empty* /*request*/,
    ::power_device::CommandResponse* /*response*/) {
    // TODO: read fields from `request`, call m_domain, populate `response`.
    return grpc::Status(grpc::StatusCode::UNIMPLEMENTED, "TODO: implement InitDevice");
}

grpc::Status PowerSupplyServiceGrpcAdapter::SetVoltage(
    grpc::ServerContext* /*ctx*/,
    const ::power_device::SetVoltageRequest* /*request*/,
    ::power_device::CommandResponse* /*response*/) {
    // TODO: read fields from `request`, call m_domain, populate `response`.
    return grpc::Status(grpc::StatusCode::UNIMPLEMENTED, "TODO: implement SetVoltage");
}

grpc::Status PowerSupplyServiceGrpcAdapter::SetCurrentLimit(
    grpc::ServerContext* /*ctx*/,
    const ::power_device::SetCurrentLimitRequest* /*request*/,
    ::power_device::CommandResponse* /*response*/) {
    // TODO: read fields from `request`, call m_domain, populate `response`.
    return grpc::Status(grpc::StatusCode::UNIMPLEMENTED, "TODO: implement SetCurrentLimit");
}

grpc::Status PowerSupplyServiceGrpcAdapter::SetOutputEnabled(
    grpc::ServerContext* /*ctx*/,
    const ::power_device::SetOutputEnabledRequest* /*request*/,
    ::power_device::CommandResponse* /*response*/) {
    // TODO: read fields from `request`, call m_domain, populate `response`.
    return grpc::Status(grpc::StatusCode::UNIMPLEMENTED, "TODO: implement SetOutputEnabled");
}

grpc::Status PowerSupplyServiceGrpcAdapter::ReadCurrent(
    grpc::ServerContext* /*ctx*/,
    const ::power_device::ChannelRequest* /*request*/,
    ::power_device::GetMeasurementsResponse* /*response*/) {
    // TODO: read fields from `request`, call m_domain, populate `response`.
    return grpc::Status(grpc::StatusCode::UNIMPLEMENTED, "TODO: implement ReadCurrent");
}

grpc::Status PowerSupplyServiceGrpcAdapter::ReadVoltage(
    grpc::ServerContext* /*ctx*/,
    const ::power_device::ChannelRequest* /*request*/,
    ::power_device::GetMeasurementsResponse* /*response*/) {
    // TODO: read fields from `request`, call m_domain, populate `response`.
    return grpc::Status(grpc::StatusCode::UNIMPLEMENTED, "TODO: implement ReadVoltage");
}

}  // namespace power_supply_service
