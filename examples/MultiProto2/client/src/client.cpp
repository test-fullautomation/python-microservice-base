// Console client for MultiProto2 (multi-proto).
//
// All services are hosted by ONE binary on ONE port, so we make ONE
// channel and instantiate all per-service stubs on it.
//
// Usage:
//   multi_proto2_client                    # discover host:port via Consul (default)
//   multi_proto2_client --direct HOST:PORT # bypass Consul, connect directly

#include <iostream>
#include <memory>
#include <string>

#include <grpcpp/grpcpp.h>
#include "MicroserviceBase/ServiceClient.h"

#include "com_config_device.grpc.pb.h"
#include "power_device.grpc.pb.h"

int main(int argc, char** argv) {
    std::string target;
    bool direct = false;
    for (int i = 1; i < argc; ++i) {
        std::string a(argv[i]);
        if (a == "--direct" && i + 1 < argc) {
            target = argv[++i];
            direct = true;
        }
    }

    if (!direct) {
        // Discover the multi-service binary via Consul.  All hosted services
        // share ONE registration named after the project's snake_name, so
        // one lookup yields the host:port for every service.
        const char* consul_addr_env = std::getenv("MULTI_PROTO2_CONSUL_ADDR");
        std::string consul_addr = consul_addr_env
            ? consul_addr_env : "http://127.0.0.1:8500";
        microservice_base::ConsulResolver resolver(consul_addr);
        auto endpoint = resolver.resolve("multi_proto2");
        if (endpoint.empty()) {
            std::cerr << "Consul lookup for 'multi_proto2' returned no instances. "
                      << "Pass --direct HOST:PORT to bypass." << std::endl;
            return 1;
        }
        target = endpoint;
    }

    std::cout << "Connecting to MultiProto2 @ " << target << std::endl;
    auto channel = grpc::CreateChannel(target, grpc::InsecureChannelCredentials());

    try {
        auto com_setup_device_service_stub = ::Com_Setup_Device::ComSetupDeviceService::NewStub(channel);
        auto power_supply_service_stub = ::power_device::PowerSupplyService::NewStub(channel);

        std::cout << "\nHosted services + methods:" << std::endl;
        std::cout << "  ComSetupDeviceService: SetInterfaceType, GetInterfaceType, SetInterfaceConfig, GetInterfaceConfig, LoadInterfaceConfig, Connect, DisConnect, GetConnectState" << std::endl;
        std::cout << "  PowerSupplyService: SetSubDeviceType, GetSubDeviceType, GetSubDeviceTypeChannelCount, GetSubDeviceType_ListCount, GetSubDeviceType_ID, GetSubDeviceType_Name, InitDevice, SetVoltage, SetCurrentLimit, SetOutputEnabled, ReadCurrent, ReadVoltage" << std::endl;
        std::cout << std::endl;
        std::cout << "TODO: replace this scaffold with your own RPC calls." << std::endl;
        std::cout << "Each *_stub above is ready to use, e.g.:" << std::endl;
        std::cout << "  grpc::ClientContext ctx;" << std::endl;
        std::cout << "  ::ns::FooRequest req;  ::ns::FooResponse resp;" << std::endl;
        std::cout << "  auto status = your_stub->FooMethod(&ctx, req, &resp);" << std::endl;
    } catch (const std::exception& e) {
        std::cerr << "Client error: " << e.what() << std::endl;
        return 1;
    }
    return 0;
}
