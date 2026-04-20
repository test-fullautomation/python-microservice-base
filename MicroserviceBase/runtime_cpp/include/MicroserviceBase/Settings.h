// Settings.h — Base settings struct shared by every MicroserviceBase C++ service.
//
// Each service subclasses BaseServiceSettings and adds its own fields.
// Values are loaded from environment variables (see loadFromEnv()) — the
// exact prefix is chosen by the subclass (e.g. "HELLO_").
//
// This mirrors MicroserviceBase/runtime/settings.py on the Python side.

#pragma once

#include <cstdlib>
#include <string>

namespace microservice_base {

struct BaseServiceSettings {
    // Logical service name used for Consul registration.
    std::string service_name;

    // Address the gRPC server binds to.  0.0.0.0 = all interfaces.
    std::string service_host = "0.0.0.0";

    // TCP port for the gRPC server.  0 = OS-assigned (dynamic).
    int grpc_port = 0;

    // Address announced to Consul.  Empty = local hostname.
    std::string advertise_addr;

    // Consul HTTP API endpoint.
    std::string consul_addr = "http://localhost:8500";

    // Optional Consul ACL token.
    std::string consul_token;

    // Python-style log level name ("DEBUG", "INFO", ...).
    std::string log_level = "INFO";

    // Read an environment variable into *out* if set.  Subclasses call this
    // from their own loadFromEnv() with the service-specific prefix.
    static void readEnv(const std::string& key, std::string& out) {
        const char* raw = std::getenv(key.c_str());
        if (raw && *raw)
            out = raw;
    }

    static void readEnv(const std::string& key, int& out) {
        const char* raw = std::getenv(key.c_str());
        if (raw && *raw) {
            try {
                out = std::stoi(raw);
            } catch (...) { /* keep default */ }
        }
    }

    // Load the base fields from environment variables with the given prefix.
    // Subclasses usually call this first, then read their own fields.
    void loadBaseFromEnv(const std::string& prefix) {
        readEnv(prefix + "SERVICE_HOST",  service_host);
        readEnv(prefix + "GRPC_PORT",     grpc_port);
        readEnv(prefix + "ADVERTISE_ADDR", advertise_addr);
        readEnv(prefix + "CONSUL_ADDR",   consul_addr);
        readEnv(prefix + "CONSUL_TOKEN",  consul_token);
        readEnv(prefix + "LOG_LEVEL",     log_level);
    }
};

}  // namespace microservice_base
