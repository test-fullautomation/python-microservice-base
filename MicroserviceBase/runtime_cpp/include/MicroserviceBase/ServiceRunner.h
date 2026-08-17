// ServiceRunner.h — Start a gRPC service with Consul registration,
// reflection, health check, and graceful shutdown.
//
// Mirrors MicroserviceBase/runtime/server.py on the Python side.
//
// Usage:
//
//   grpc::ServerBuilder builder;
//   auto service = std::make_unique<HelloGrpcAdapter>(domain);
//   ServiceRunner runner(settings);
//   runner.addService(service.get(), "hello.v1.HelloService");
//   runner.serveForever();   // blocks until Ctrl+C / SIGTERM
//
// ``full_service_name`` must match the proto ``package.ServiceName`` so that
// gRPC reflection and Consul metadata are consistent with the Python side.

#pragma once

#include <atomic>
#include <memory>
#include <string>
#include <vector>

#include <grpcpp/grpcpp.h>
#include <grpcpp/health_check_service_interface.h>
// gRPC server reflection is optional - vcpkg's grpc 1.76 port doesn't
// build the reflection lib/header.  CMake defines MB_HAVE_GRPC_REFLECTION=1
// when it's available; we skip the InitProto... call otherwise.
#if defined(MB_HAVE_GRPC_REFLECTION) && MB_HAVE_GRPC_REFLECTION
#include <grpcpp/ext/proto_server_reflection_plugin.h>
#endif

#include "Settings.h"
#include "ConsulRegistration.h"

namespace microservice_base {

class ServiceRunner {
public:
    explicit ServiceRunner(const BaseServiceSettings& settings,
                           std::vector<std::string> tags = {});
    ~ServiceRunner();

    ServiceRunner(const ServiceRunner&) = delete;
    ServiceRunner& operator=(const ServiceRunner&) = delete;

    // Register a servicer implementation.
    //
    //   service             - pointer to a grpc::Service subclass (ownership
    //                         stays with the caller)
    //   full_service_name   - e.g. "hello.v1.HelloService"
    void addService(grpc::Service* service, const std::string& full_service_name);

    // Build and start the gRPC server.  Returns the bound port.
    int start();

    // Block until shutdown is requested (Ctrl+C / SIGTERM / SIGBREAK).
    // Calls start() first if it hasn't been called yet, then registers with
    // Consul, waits for shutdown, deregisters, and stops the server cleanly.
    void serveForever();

    // Trigger graceful shutdown from another thread or a signal handler.
    void requestShutdown();

    int boundPort() const { return m_boundPort; }

private:
    void        installSignalHandlers();
    void        gracefulShutdown();
    std::string localHostname() const;

    BaseServiceSettings m_settings;
    std::vector<std::string> m_tags;

    struct ServiceEntry {
        grpc::Service* service;
        std::string    full_name;
    };
    std::vector<ServiceEntry> m_services;

    std::unique_ptr<grpc::Server>                     m_server;
    int                                               m_boundPort = 0;
    std::atomic<bool>                                 m_stopRequested{false};
    std::unique_ptr<ConsulRegistration>               m_consul;
};

}  // namespace microservice_base
