// ServiceCleware.h — C++ microservice for Cleware USB switch box devices.
//
// 3-part pattern:
//   1. Infrastructure: ServiceBase (RabbitMQ, dispatch, registration)
//   2. Business API:   svc_api_* methods (this file)
//   3. UI:             ServiceUI.qml (in qml/ folder)

#pragma once

#include <ServiceBase.h>
#include "ClewareAccess.h"

class ServiceCleware : public ServiceBase {
public:
    ServiceCleware(const ServiceInfo& info, const ServiceConfig& config);

private:
    ClewareAccess m_cleware;

    // --- Business API methods ---

    // Get the state of all connected Cleware devices.
    // Request:  {"method": "svc_api_get_all_devices_state", "args": []}
    // Response: {"result": "pass", "result_data": {"651082": {"0": 1, "1": 0, ...}}}
    json svc_api_get_all_devices_state(const json& args);

    // Set a switch on a device.
    // Request:  {"method": "svc_api_set_switch", "args": ["651082", "0x10", "on"]}
    // Response: {"result": "pass", "result_data": 1}
    json svc_api_set_switch(const json& args);

    // Publish current state to the realtime update exchange.
    void notifyUpdates();
};
