// ConsulRegistration.h — RAII wrapper for Consul service registration.
//
// Usage:
//   ConsulRegistration reg(
//       "hello", address, port,
//       "http://localhost:8500",
//       {"v1", "demo"}, {{"grpc_services", "hello.v1.HelloService"}});
//   if (!reg.registerService()) { ... }
//   // ... run service ...
//   reg.deregisterService();   // or let the destructor do it
//
// Uses libcurl (or any simple HTTP client) to talk to Consul's HTTP API.
// The implementation is deliberately minimal — only /v1/agent/service/register
// and /v1/agent/service/deregister are used.

#pragma once

#include <map>
#include <string>
#include <vector>

namespace microservice_base {

class ConsulRegistration {
public:
    ConsulRegistration(std::string name,
                       std::string address,
                       int port,
                       std::string consul_addr = "http://localhost:8500",
                       std::vector<std::string> tags = {},
                       std::map<std::string, std::string> meta = {},
                       std::string token = "",
                       std::string health_interval = "10s",
                       std::string health_timeout = "2s",
                       std::string deregister_after = "1m");

    ~ConsulRegistration();

    // Non-copyable — the service ID is unique to this instance.
    ConsulRegistration(const ConsulRegistration&) = delete;
    ConsulRegistration& operator=(const ConsulRegistration&) = delete;

    // Register the service with Consul.  Returns true on success.
    // Populates getLastError() on failure.
    bool registerService();

    // Deregister.  Safe to call multiple times; the destructor also calls it.
    void deregisterService();

    const std::string& serviceId() const { return m_serviceId; }
    const std::string& getLastError() const { return m_lastError; }

private:
    std::string buildRegistrationJson() const;
    bool        httpPut(const std::string& path, const std::string& body);

    std::string m_name;
    std::string m_address;
    int         m_port;
    std::string m_consulAddr;
    std::vector<std::string> m_tags;
    std::map<std::string, std::string> m_meta;
    std::string m_token;
    std::string m_healthInterval;
    std::string m_healthTimeout;
    std::string m_deregisterAfter;

    std::string m_serviceId;
    bool        m_registered = false;
    std::string m_lastError;
};

}  // namespace microservice_base
