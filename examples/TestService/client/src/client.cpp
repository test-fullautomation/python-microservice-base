// client.cpp — gRPC client for TestService using ServiceClient<T>.
//
// Usage:
//   test_service_client test_service                  # all RPCs via Consul
//   test_service_client test_service <Method> <args>  # specific RPC
//   test_service_client --direct host:port    # no Consul

#include <iostream>
#include <string>
#include <grpcpp/grpcpp.h>
#include "test_service.grpc.pb.h"
#include "MicroserviceBase/ServiceClient.h"

using test_service::v1::TestServiceService;

int main(int argc, char* argv[]) {
    if (argc < 2) {
        std::cerr << "Usage: test_service_client <service_name|--direct host:port> [method] [args...]" << std::endl;
        return 1;
    }

    std::string arg1 = argv[1];
    std::unique_ptr<microservice_base::ServiceClient<TestServiceService>> client;

    try {
        if (arg1 == "--direct") {
            if (argc < 3) { std::cerr << "Missing host:port" << std::endl; return 1; }
            client = std::make_unique<microservice_base::ServiceClient<TestServiceService>>(
                "test_service", argv[2], true);
            std::cout << "Connected directly to " << client->target() << std::endl;
        } else {
            client = std::make_unique<microservice_base::ServiceClient<TestServiceService>>(arg1);
            std::cout << "Resolved " << arg1 << " via Consul -> "
                      << client->target() << std::endl;
        }
    } catch (const std::exception& e) {
        std::cerr << "Connection failed: " << e.what() << std::endl;
        return 1;
    }

    auto& stub = client->stub();

    // TODO: Add RPC calls here. Example:
    // grpc::ClientContext ctx;
    // test_service::v1::DoSomethingRequest req;
    // req.set_input("test");
    // test_service::v1::DoSomethingResponse resp;
    // auto status = stub.DoSomething(&ctx, req, &resp);

    std::cout << "Client ready. Add RPC calls to src/client.cpp." << std::endl;
    return 0;
}
