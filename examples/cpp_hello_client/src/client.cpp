// client.cpp — Demo gRPC client using the ServiceClient library.
//
// The service provides its .proto file.  The client:
//   1. Generates stubs with protoc (handled by CMake)
//   2. Includes the generated header
//   3. Uses ServiceClient<T> which handles Consul discovery + channel
//
// Usage:
//   hello_client hello                         # all RPCs, Consul lookup
//   hello_client hello greet Cuong             # one RPC, Consul lookup
//   hello_client --direct 127.0.0.1:50051     # all RPCs, no Consul
//   hello_client --direct 127.0.0.1:50051 greet Cuong

#include <cstdlib>
#include <iostream>
#include <string>

#include <grpcpp/grpcpp.h>
#include "hello.grpc.pb.h"   // generated from the service's .proto

// The only framework header the client needs:
#include "MicroserviceBase/ServiceClient.h"

using hello::v1::HelloService;
using hello::v1::GreetRequest;
using hello::v1::GreetResponse;
using hello::v1::EchoRequest;
using hello::v1::EchoResponse;
using hello::v1::TickRequest;
using hello::v1::TickEvent;

// -----------------------------------------------------------------------
// RPC calls — pure business logic, no discovery/connection code
// -----------------------------------------------------------------------

void callGreet(HelloService::Stub& stub, const std::string& name) {
    GreetRequest req;
    req.set_name(name);

    GreetResponse resp;
    grpc::ClientContext ctx;

    std::cout << "[Greet] Calling with name=\"" << name << "\"..." << std::endl;
    auto status = stub.Greet(&ctx, req, &resp);

    if (status.ok())
        std::cout << "[Greet] Response: " << resp.message() << std::endl;
    else
        std::cerr << "[Greet] FAILED: " << status.error_message() << std::endl;
}

void callEcho(HelloService::Stub& stub, const std::string& payload) {
    EchoRequest req;
    req.set_payload(payload);

    EchoResponse resp;
    grpc::ClientContext ctx;

    std::cout << "[Echo] Calling with payload=\"" << payload << "\"..." << std::endl;
    auto status = stub.Echo(&ctx, req, &resp);

    if (status.ok())
        std::cout << "[Echo] Response: " << resp.payload() << std::endl;
    else
        std::cerr << "[Echo] FAILED: " << status.error_message() << std::endl;
}

void callTick(HelloService::Stub& stub, int count, int interval_ms) {
    TickRequest req;
    req.set_count(count);
    req.set_interval_ms(interval_ms);

    grpc::ClientContext ctx;

    std::cout << "[Tick] Streaming " << count << " events ("
              << interval_ms << "ms interval)..." << std::endl;

    auto reader = stub.Tick(&ctx, req);
    TickEvent event;
    int received = 0;
    while (reader->Read(&event)) {
        std::cout << "[Tick] #" << event.sequence()
                  << ": " << event.message() << std::endl;
        received++;
    }

    auto status = reader->Finish();
    if (status.ok())
        std::cout << "[Tick] Done. " << received << " event(s)." << std::endl;
    else
        std::cerr << "[Tick] FAILED: " << status.error_message() << std::endl;
}

void runAll(HelloService::Stub& stub) {
    std::cout << "\n=== Greet ===" << std::endl;
    callGreet(stub, "World");

    std::cout << "\n=== Echo ===" << std::endl;
    callEcho(stub, "Hello from C++ client!");

    std::cout << "\n=== Tick ===" << std::endl;
    callTick(stub, 5, 300);
}

// -----------------------------------------------------------------------
// Main
// -----------------------------------------------------------------------

void printUsage() {
    std::cerr << "Usage:" << std::endl;
    std::cerr << "  hello_client <service_name> [greet|echo|tick] [args...]" << std::endl;
    std::cerr << "  hello_client --direct <host:port> [greet|echo|tick] [args...]" << std::endl;
    std::cerr << std::endl;
    std::cerr << "Examples:" << std::endl;
    std::cerr << "  hello_client hello                # all RPCs via Consul" << std::endl;
    std::cerr << "  hello_client hello greet Cuong    # Greet via Consul" << std::endl;
    std::cerr << "  hello_client --direct 127.0.0.1:50051 greet Cuong" << std::endl;
    std::cerr << std::endl;
    std::cerr << "Environment:" << std::endl;
    std::cerr << "  CONSUL_ADDR   Consul URL (default: http://127.0.0.1:8500)" << std::endl;
}

int main(int argc, char* argv[]) {
    if (argc < 2) { printUsage(); return 1; }

    std::string arg1 = argv[1];

    // -- Create the client -----------------------------------------------
    //
    // This is the ONLY framework interaction.  Everything after this line
    // is pure gRPC stub calls — no Consul, no sockets, no JSON.

    std::unique_ptr<microservice_base::ServiceClient<HelloService>> client;
    int argStart = 2;

    try {
        if (arg1 == "--direct") {
            if (argc < 3) { printUsage(); return 1; }
            client = std::make_unique<microservice_base::ServiceClient<HelloService>>(
                "hello", argv[2], /*direct_tag=*/true);
            argStart = 3;
            std::cout << "Connected directly to " << client->target() << std::endl;
        } else if (arg1 == "--help" || arg1 == "-h") {
            printUsage(); return 0;
        } else {
            // Default: Consul discovery by service name.
            client = std::make_unique<microservice_base::ServiceClient<HelloService>>(arg1);
            std::cout << "Resolved " << arg1 << " via Consul -> "
                      << client->target() << std::endl;
        }
    } catch (const std::exception& e) {
        std::cerr << "Connection failed: " << e.what() << std::endl;
        return 1;
    }

    // -- Call RPCs -------------------------------------------------------

    auto& stub = client->stub();

    if (argc <= argStart) {
        runAll(stub);
        return 0;
    }

    std::string cmd = argv[argStart];

    if (cmd == "greet") {
        callGreet(stub, argc > argStart + 1 ? argv[argStart + 1] : "World");
    } else if (cmd == "echo") {
        callEcho(stub, argc > argStart + 1 ? argv[argStart + 1] : "hello");
    } else if (cmd == "tick") {
        int count    = argc > argStart + 1 ? std::atoi(argv[argStart + 1]) : 5;
        int interval = argc > argStart + 2 ? std::atoi(argv[argStart + 2]) : 500;
        callTick(stub, count, interval);
    } else {
        std::cerr << "Unknown command: " << cmd << std::endl;
        return 1;
    }

    return 0;
}
