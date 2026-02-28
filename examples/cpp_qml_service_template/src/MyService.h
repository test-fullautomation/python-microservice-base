// MyService.h — Example C++ microservice with svc_api_* methods.
//
// Demonstrates the 3-part pattern:
//   1. Infrastructure: ServiceBase (handles RabbitMQ, dispatch, registration)
//   2. Business API:   svc_api_* methods (this file)
//   3. UI:             ServiceUI.qml (in qml/ folder, designed in Qt Creator)

#pragma once

#include <ServiceBase.h>

class MyService : public ServiceBase {
public:
    MyService(const ServiceInfo& info, const ServiceConfig& config);

private:
    // --- Business API methods ---

    // Say hello to someone.
    // Request:  {"method": "svc_api_hello", "args": ["World"]}
    // Response: {"result": "pass", "result_data": "Hello, World!"}
    json svc_api_hello(const json& args);

    // Echo back the input data.
    // Request:  {"method": "svc_api_echo", "args": ["test"]}
    // Response: {"result": "pass", "result_data": "test"}
    json svc_api_echo(const json& args);

    // Compute the sum of numbers.
    // Request:  {"method": "svc_api_compute", "args": [[1, 2, 3]]}
    // Response: {"result": "pass", "result_data": 6}
    json svc_api_compute(const json& args);
};
