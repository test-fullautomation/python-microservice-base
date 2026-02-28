// MyQtWasmService.h — Example C++ microservice with svc_api_* methods.
//
// Demonstrates the 3-part pattern:
//   1. Infrastructure: ServiceBase (handles RabbitMQ, dispatch, registration)
//   2. Business API:   svc_api_* methods (this file)
//   3. UI:             MainWidget (Qt Widgets, compiled to WASM for browser)

#pragma once

#include <ServiceBase.h>

class MyQtWasmService : public ServiceBase {
public:
    MyQtWasmService(const ServiceInfo& info, const ServiceConfig& config);

private:
    // --- Business API methods ---
    json svc_api_hello(const json& args);
    json svc_api_echo(const json& args);
    json svc_api_compute(const json& args);
};
