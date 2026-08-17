#pragma once

#include "power_device.grpc.pb.h"
#include "../../domain/PowerSupplyService.h"

namespace power_supply_service {

// gRPC adapter: thin wrapper translating proto messages <-> domain calls.
class PowerSupplyServiceGrpcAdapter final
    : public ::power_device::PowerSupplyService::Service {
public:
    explicit PowerSupplyServiceGrpcAdapter(PowerSupplyService& domain) : m_domain(domain) {}

    grpc::Status SetSubDeviceType(grpc::ServerContext* ctx,
        const ::power_device::SubDeviceTypeRequest* request,
        ::power_device::CommandResponse* response) override;
    grpc::Status GetSubDeviceType(grpc::ServerContext* ctx,
        const ::power_device::Empty* request,
        ::power_device::GetSubDeviceTypeResponse* response) override;
    grpc::Status GetSubDeviceTypeChannelCount(grpc::ServerContext* ctx,
        const ::power_device::Empty* request,
        ::power_device::ChannelCountResponse* response) override;
    grpc::Status GetSubDeviceType_ListCount(grpc::ServerContext* ctx,
        const ::power_device::Empty* request,
        ::power_device::GetSubDeviceTypeListCountResponse* response) override;
    grpc::Status GetSubDeviceType_ID(grpc::ServerContext* ctx,
        const ::power_device::SubDeviceTypeRequest* request,
        ::power_device::GetSubDeviceTypeIDResponse* response) override;
    grpc::Status GetSubDeviceType_Name(grpc::ServerContext* ctx,
        const ::power_device::SubDeviceTypeRequest* request,
        ::power_device::GetSubDeviceTypeNameResponse* response) override;
    grpc::Status InitDevice(grpc::ServerContext* ctx,
        const ::power_device::Empty* request,
        ::power_device::CommandResponse* response) override;
    grpc::Status SetVoltage(grpc::ServerContext* ctx,
        const ::power_device::SetVoltageRequest* request,
        ::power_device::CommandResponse* response) override;
    grpc::Status SetCurrentLimit(grpc::ServerContext* ctx,
        const ::power_device::SetCurrentLimitRequest* request,
        ::power_device::CommandResponse* response) override;
    grpc::Status SetOutputEnabled(grpc::ServerContext* ctx,
        const ::power_device::SetOutputEnabledRequest* request,
        ::power_device::CommandResponse* response) override;
    grpc::Status ReadCurrent(grpc::ServerContext* ctx,
        const ::power_device::ChannelRequest* request,
        ::power_device::GetMeasurementsResponse* response) override;
    grpc::Status ReadVoltage(grpc::ServerContext* ctx,
        const ::power_device::ChannelRequest* request,
        ::power_device::GetMeasurementsResponse* response) override;

private:
    PowerSupplyService& m_domain;
};

}  // namespace power_supply_service
