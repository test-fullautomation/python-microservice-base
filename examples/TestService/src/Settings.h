#pragma once

#include "MicroserviceBase/Settings.h"

// Shared settings for the TestService multi-service binary.
// All hosted gRPC services use ONE Consul registration, ONE port, ONE
// service name (read from env via the TEST_SERVICE_ prefix).

namespace test_service {

struct Settings : public microservice_base::BaseServiceSettings {
    Settings() {
        service_name = "test_service";
        loadBaseFromEnv("TEST_SERVICE_");
    }
};

}  // namespace test_service
