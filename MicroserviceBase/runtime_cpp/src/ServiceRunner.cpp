// ServiceRunner.cpp — gRPC server wrapper with Consul + reflection + health.

#include "MicroserviceBase/ServiceRunner.h"

#include <csignal>
#include <cstdlib>
#include <iostream>
#include <sstream>
#include <thread>

#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#else
#include <netdb.h>
#include <unistd.h>
#endif

#include <grpcpp/health_check_service_interface.h>

namespace microservice_base {

// ---------------------------------------------------------------------------
// Signal handling
// ---------------------------------------------------------------------------

// A single static instance is used so signal handlers (which can't take
// arguments) know who to poke.  ServiceRunner is not typically instantiated
// more than once per process, but this is documented in the header.
namespace {
ServiceRunner* g_activeRunner = nullptr;

void signalHandler(int /*sig*/) {
    if (g_activeRunner) {
        g_activeRunner->requestShutdown();
    }
}

#ifdef _WIN32
BOOL WINAPI consoleCtrlHandler(DWORD ctrlType) {
    if (ctrlType == CTRL_C_EVENT || ctrlType == CTRL_BREAK_EVENT ||
        ctrlType == CTRL_CLOSE_EVENT) {
        if (g_activeRunner) g_activeRunner->requestShutdown();
        return TRUE;
    }
    return FALSE;
}
#endif
}  // namespace

// ---------------------------------------------------------------------------
// ServiceRunner
// ---------------------------------------------------------------------------

ServiceRunner::ServiceRunner(const BaseServiceSettings& settings,
                             std::vector<std::string> tags)
    : m_settings(settings), m_tags(std::move(tags))
{
    if (m_settings.service_name.empty())
        throw std::runtime_error("BaseServiceSettings::service_name must be set");
}

ServiceRunner::~ServiceRunner() {
    if (g_activeRunner == this) {
        g_activeRunner = nullptr;
    }
}

void ServiceRunner::addService(grpc::Service* service,
                               const std::string& full_service_name) {
    m_services.push_back({service, full_service_name});
}

int ServiceRunner::start() {
    // Enable default health check service.  Reflection is optional and
    // only initialised when grpc was built with the reflection lib (CMake
    // sets MB_HAVE_GRPC_REFLECTION=1 in that case).
    grpc::EnableDefaultHealthCheckService(true);
#if defined(MB_HAVE_GRPC_REFLECTION) && MB_HAVE_GRPC_REFLECTION
    grpc::reflection::InitProtoReflectionServerBuilderPlugin();
#endif

    grpc::ServerBuilder builder;

    // Bind the listen port.  grpc stores the selected port into selected_port.
    const std::string bind_target =
        m_settings.service_host + ":" + std::to_string(m_settings.grpc_port);
    int selected_port = 0;
    builder.AddListeningPort(bind_target, grpc::InsecureServerCredentials(),
                             &selected_port);

    for (auto& entry : m_services) {
        builder.RegisterService(entry.service);
    }

    m_server = builder.BuildAndStart();
    if (!m_server) {
        throw std::runtime_error("Failed to start gRPC server on " + bind_target);
    }
    m_boundPort = selected_port;

    std::cout << "[ServiceRunner] gRPC server listening on "
              << m_settings.service_host << ":" << m_boundPort << std::endl;

    // Mark all services SERVING in the default health check.
    auto* health = m_server->GetHealthCheckService();
    if (health) {
        for (const auto& e : m_services)
            health->SetServingStatus(e.full_name, true);
        health->SetServingStatus("", true);
    }
    return m_boundPort;
}

void ServiceRunner::serveForever() {
    if (!m_server) start();

    installSignalHandlers();

    const std::string address =
        m_settings.advertise_addr.empty() ? localHostname()
                                          : m_settings.advertise_addr;

    std::map<std::string, std::string> meta;
    {
        std::ostringstream ss;
        for (size_t i = 0; i < m_services.size(); ++i) {
            if (i) ss << ",";
            ss << m_services[i].full_name;
        }
        meta["grpc_services"] = ss.str();
    }

    m_consul = std::make_unique<ConsulRegistration>(
        m_settings.service_name,
        address,
        m_boundPort,
        m_settings.consul_addr,
        m_tags,
        meta,
        m_settings.consul_token);

    if (!m_consul->registerService()) {
        std::cerr << "[ServiceRunner] WARNING: Consul registration failed: "
                  << m_consul->getLastError()
                  << " - continuing anyway (service still reachable)." << std::endl;
    }

    std::cout << "[ServiceRunner] Service " << m_settings.service_name
              << " ready." << std::endl;

    // Poll the stop flag every 200 ms.  This keeps the API simple without
    // pulling in a full event loop.
    using namespace std::chrono_literals;
    while (!m_stopRequested.load()) {
        std::this_thread::sleep_for(200ms);
    }

    gracefulShutdown();
}

void ServiceRunner::requestShutdown() {
    m_stopRequested.store(true);
}

void ServiceRunner::gracefulShutdown() {
    std::cout << "[ServiceRunner] Shutdown requested." << std::endl;

    if (m_consul) {
        m_consul->deregisterService();
        m_consul.reset();
    }

    if (m_server) {
        auto deadline = std::chrono::system_clock::now() + std::chrono::seconds(5);
        m_server->Shutdown(deadline);
        m_server.reset();
    }
    std::cout << "[ServiceRunner] Service stopped cleanly." << std::endl;
}

void ServiceRunner::installSignalHandlers() {
    g_activeRunner = this;

    std::signal(SIGINT,  signalHandler);
    std::signal(SIGTERM, signalHandler);
#ifdef SIGBREAK
    std::signal(SIGBREAK, signalHandler);
#endif

#ifdef _WIN32
    SetConsoleCtrlHandler(consoleCtrlHandler, TRUE);
#endif
}

std::string ServiceRunner::localHostname() const {
    char buf[256] = {0};
    if (gethostname(buf, sizeof(buf) - 1) != 0) {
        return "127.0.0.1";
    }

    // Resolve to an IPv4 address for Consul.
    addrinfo hints{};
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_STREAM;
    addrinfo* res = nullptr;
    if (getaddrinfo(buf, nullptr, &hints, &res) != 0 || !res) {
        return std::string(buf);
    }

    char ipbuf[INET_ADDRSTRLEN] = {0};
    auto* sa = reinterpret_cast<sockaddr_in*>(res->ai_addr);
    inet_ntop(AF_INET, &sa->sin_addr, ipbuf, sizeof(ipbuf));
    freeaddrinfo(res);
    return std::string(ipbuf);
}

}  // namespace microservice_base
