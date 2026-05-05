#include <iostream>
#include "MicroserviceBase/ServiceRunner.h"

#include "Settings.h"
#include "domain/TestServiceService.h"
#include "adapters/api/TestServiceGrpcAdapter.h"

int main() {
    try {
        test_service::Settings settings;
        test_service::TestServiceService domain;
        test_service::TestServiceGrpcAdapter adapter(domain);

        microservice_base::ServiceRunner runner(settings, {"v1"});
        runner.addService(&adapter, "test_service.v1.TestServiceService");
        runner.serveForever();
    } catch (const std::exception& e) {
        std::cerr << "FATAL: " << e.what() << std::endl;
        return 1;
    }
    return 0;
}
