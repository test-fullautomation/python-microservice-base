// Settings.h — Hello-service specific settings.
//
// Environment variables are read with the HELLO_ prefix, e.g.:
//   HELLO_GRPC_PORT=50051
//   HELLO_CONSUL_ADDR=http://127.0.0.1:8500
//   HELLO_GREETING=Hola

#pragma once

#include "MicroserviceBase/Settings.h"

namespace hello {

struct Settings : public microservice_base::BaseServiceSettings {
    std::string greeting = "Hello";

    Settings() {
        service_name = "hello";
        loadBaseFromEnv("HELLO_");
        readEnv("HELLO_GREETING", greeting);
    }
};

}  // namespace hello
