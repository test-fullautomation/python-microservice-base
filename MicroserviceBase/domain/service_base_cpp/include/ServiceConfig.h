// ServiceConfig.h — Configuration for a C++ microservice.

#pragma once

#include <string>

struct ServiceConfig {
    // RabbitMQ broker connection
    std::string broker_host = "localhost";
    int         broker_port = 5672;
    std::string broker_vhost = "/";
    std::string broker_user = "guest";
    std::string broker_pass = "guest";

    // Path to the service's root directory (where GUIs/ lives).
    // Set automatically from the config file path in main(), or manually.
    std::string service_dir;
};
