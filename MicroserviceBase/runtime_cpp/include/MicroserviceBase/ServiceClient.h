// ServiceClient.h — Generic gRPC client with Consul service discovery.
//
// This is the client-side counterpart of ServiceRunner.  A service
// developer provides their .proto file; the consumer generates stubs
// with protoc and uses ServiceClient to handle:
//
//   - Consul service discovery (resolve name → host:port)
//   - gRPC channel creation and caching
//   - Automatic re-resolution on connection failure
//   - Direct host:port mode (no Consul) for testing
//
// Usage:
//
//   #include "MicroserviceBase/ServiceClient.h"
//   #include "hello.grpc.pb.h"     // generated from the service's .proto
//
//   using hello::v1::HelloService;
//
//   // Consul-based discovery (recommended for production):
//   ServiceClient<HelloService> client("hello");
//
//   // Direct connection (for testing / debugging):
//   ServiceClient<HelloService> client("hello", "127.0.0.1:50051");
//
//   // Call an RPC:
//   auto& stub = client.stub();
//   grpc::ClientContext ctx;
//   hello::v1::GreetRequest req;
//   req.set_name("World");
//   hello::v1::GreetResponse resp;
//   auto status = stub.Greet(&ctx, req, &resp);
//
// The template parameter is the generated Service class (e.g.
// hello::v1::HelloService).  ServiceClient creates a Stub internally.

#pragma once

#include <memory>
#include <mutex>
#include <string>
#include <stdexcept>

#include <grpcpp/grpcpp.h>

#include "Settings.h"

namespace microservice_base {

// -----------------------------------------------------------------------
// Consul lookup (self-contained, no libcurl dependency on the client side)
// -----------------------------------------------------------------------
namespace detail {

struct ResolvedEndpoint {
    std::string address;
    int         port = 0;

    std::string target() const {
        return address + ":" + std::to_string(port);
    }
    bool valid() const { return !address.empty() && port > 0; }
};

// Resolve a Consul service name to host:port by calling
// GET /v1/health/service/{name}?passing=true on the Consul HTTP API.
// Uses raw sockets — no libcurl needed on the client side.
ResolvedEndpoint resolveConsul(const std::string& consulAddr,
                               const std::string& serviceName);

}  // namespace detail

// -----------------------------------------------------------------------
// ServiceClient<T>
// -----------------------------------------------------------------------

template <typename ServiceT>
class ServiceClient {
public:
    using StubType = typename ServiceT::Stub;

    /// Construct a client that discovers the service via Consul.
    ///
    /// @param serviceName   The Consul service name (e.g. "hello").
    /// @param consulAddr    Consul HTTP API URL.  Defaults to the
    ///                      CONSUL_ADDR environment variable, or
    ///                      http://127.0.0.1:8500 if not set.
    explicit ServiceClient(const std::string& serviceName,
                           const std::string& consulAddr = "")
        : m_serviceName(serviceName)
        , m_consulAddr(consulAddr)
        , m_direct(false)
    {
        if (m_consulAddr.empty()) {
            const char* env = std::getenv("CONSUL_ADDR");
            m_consulAddr = env ? env : "http://127.0.0.1:8500";
        }
        resolve();
    }

    /// Construct a client that connects directly to a known host:port.
    ///
    /// @param serviceName   Logical name (for logging; not used for lookup).
    /// @param target        Direct gRPC target, e.g. "127.0.0.1:50051".
    ServiceClient(const std::string& serviceName,
                  const std::string& target,
                  bool /*direct_tag*/)
        : m_serviceName(serviceName)
        , m_target(target)
        , m_direct(true)
    {
        connect(m_target);
    }

    /// Get the gRPC stub.  The first call triggers Consul resolution
    /// (if not already connected) and channel creation.
    ///
    /// Throws std::runtime_error if resolution fails.
    StubType& stub() {
        std::lock_guard<std::mutex> lock(m_mu);
        if (!m_stub) {
            throw std::runtime_error(
                "ServiceClient: not connected to " + m_serviceName +
                (m_lastError.empty() ? "" : " — " + m_lastError));
        }
        return *m_stub;
    }

    /// Force re-resolution from Consul and reconnection.  Useful after
    /// a transient failure or when you suspect the service moved.
    void reconnect() {
        std::lock_guard<std::mutex> lock(m_mu);
        if (m_direct) {
            connect(m_target);
        } else {
            resolve();
        }
    }

    /// Return the current gRPC target string (host:port).
    std::string target() const {
        std::lock_guard<std::mutex> lock(m_mu);
        return m_target;
    }

    /// Return the Consul address used for discovery.
    const std::string& consulAddr() const { return m_consulAddr; }

    /// Return the logical service name.
    const std::string& serviceName() const { return m_serviceName; }

    /// Check if the underlying channel is in READY state.
    bool isConnected() const {
        std::lock_guard<std::mutex> lock(m_mu);
        if (!m_channel) return false;
        return m_channel->GetState(false) == GRPC_CHANNEL_READY;
    }

    // -- Static factory helpers ------------------------------------------

    /// Create a Consul-based client.
    static ServiceClient fromConsul(const std::string& serviceName,
                                    const std::string& consulAddr = "") {
        return ServiceClient(serviceName, consulAddr);
    }

    /// Create a direct-connection client (no Consul).
    static ServiceClient fromDirect(const std::string& serviceName,
                                    const std::string& target) {
        return ServiceClient(serviceName, target, true);
    }

private:
    void resolve() {
        auto ep = detail::resolveConsul(m_consulAddr, m_serviceName);
        if (!ep.valid()) {
            m_lastError = "Consul lookup failed for '" + m_serviceName +
                          "' at " + m_consulAddr;
            m_stub.reset();
            return;
        }
        m_target = ep.target();
        connect(m_target);
    }

    void connect(const std::string& target) {
        m_channel = grpc::CreateChannel(
            target, grpc::InsecureChannelCredentials());
        m_stub = ServiceT::NewStub(m_channel);
        m_lastError.clear();
    }

    std::string                        m_serviceName;
    std::string                        m_consulAddr;
    std::string                        m_target;
    bool                               m_direct;
    std::string                        m_lastError;
    std::shared_ptr<grpc::Channel>     m_channel;
    std::unique_ptr<StubType>          m_stub;
    mutable std::mutex                 m_mu;
};

}  // namespace microservice_base
