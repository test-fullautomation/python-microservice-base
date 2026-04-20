#pragma once

#include "MicroserviceBase/Settings.h"

namespace test_service {

struct Settings : public microservice_base::BaseServiceSettings {
    Settings() {
        service_name = "test_service";
        loadBaseFromEnv("TEST_SERVICE_");
    }
};

}  // namespace test_service
