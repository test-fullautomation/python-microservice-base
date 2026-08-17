#pragma once

#include "MicroserviceBase/Settings.h"

// Shared settings for the MultiProto multi-service binary.
// All hosted gRPC services use ONE Consul registration, ONE port, ONE
// service name (read from env via the MULTI_PROTO_ prefix).

namespace multi_proto {

struct Settings : public microservice_base::BaseServiceSettings {
    Settings() {
        service_name = "multi_proto";
        loadBaseFromEnv("MULTI_PROTO_");
    }
};

}  // namespace multi_proto
