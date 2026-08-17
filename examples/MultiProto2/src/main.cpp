#include <iostream>
#include "MicroserviceBase/ServiceRunner.h"

#include "Settings.h"
#include "com_setup_device_service/domain/ComSetupDeviceService.h"
#include "com_setup_device_service/adapters/api/ComSetupDeviceServiceGrpcAdapter.h"
#include "power_supply_service/domain/PowerSupplyService.h"
#include "power_supply_service/adapters/api/PowerSupplyServiceGrpcAdapter.h"

// Multi-proto / single-binary entry point.  This process hosts
// 2 gRPC services on one port, with one Consul
// registration.  Shutdown signals deregister all services together.

int main() {
    try {
        multi_proto2::Settings settings;

        // Domain instances (pure business logic, no gRPC dependency).
        com_setup_device_service::ComSetupDeviceService com_setup_device_serviceDomain;
        power_supply_service::PowerSupplyService power_supply_serviceDomain;

        // Adapter instances (gRPC service implementations wrapping domain).
        com_setup_device_service::ComSetupDeviceServiceGrpcAdapter com_setup_device_serviceAdapter(com_setup_device_serviceDomain);
        power_supply_service::PowerSupplyServiceGrpcAdapter power_supply_serviceAdapter(power_supply_serviceDomain);

        microservice_base::ServiceRunner runner(settings, {"v1"});
        runner.addService(&com_setup_device_serviceAdapter, "Com_Setup_Device.ComSetupDeviceService");
        runner.addService(&power_supply_serviceAdapter, "power_device.PowerSupplyService");
        runner.serveForever();
    } catch (const std::exception& e) {
        std::cerr << "FATAL: " << e.what() << std::endl;
        return 1;
    }
    return 0;
}
