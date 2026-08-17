// main.cpp — Entry point for the C++ hello sample.
//
// Mirrors examples/hello_service/main.py: creates the domain, wires it into
// the gRPC adapter, starts the runtime, and blocks until Ctrl+C.

#include <iostream>

#include "MicroserviceBase/ServiceRunner.h"

#include "Settings.h"
#include "domain/HelloService.h"
#include "adapters/api/HelloGrpcAdapter.h"

int main() {
    try {
        hello::Settings settings;
        hello::HelloService domain(settings.greeting);
        hello::HelloGrpcAdapter adapter(domain);

        microservice_base::ServiceRunner runner(settings, {"v1", "demo"});
        runner.addService(&adapter, "hello.v1.HelloService");
        runner.serveForever();
    } catch (const std::exception& e) {
        std::cerr << "FATAL: " << e.what() << std::endl;
        return 1;
    }
    return 0;
}
