#pragma once

#include "MicroserviceBase/Settings.h"

// Shared settings for the MultiProto2 multi-service binary.
// All hosted gRPC services use ONE Consul registration, ONE port, ONE
// service name (read from env via the MULTI_PROTO2_ prefix).

namespace multi_proto2 {

struct Settings : public microservice_base::BaseServiceSettings {
    Settings() {
        service_name = "multi_proto2";
        loadBaseFromEnv("MULTI_PROTO2_");
    }
};

}  // namespace multi_proto2
