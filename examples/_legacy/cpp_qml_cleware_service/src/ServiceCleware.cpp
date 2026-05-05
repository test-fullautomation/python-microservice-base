// ServiceCleware.cpp — Cleware USB switch service implementation.

#include "ServiceCleware.h"
#include "RabbitMQConnection.h"

#include <stdexcept>
#include <iostream>

ServiceCleware::ServiceCleware(const ServiceInfo& info, const ServiceConfig& config)
    : ServiceBase(info, config)
{
    registerMethod("svc_api_get_all_devices_state",
        [this](const json& args) { return svc_api_get_all_devices_state(args); },
        MethodInfo{
            {},
            "dict"
        });

    registerMethod("svc_api_set_switch",
        [this](const json& args) { return svc_api_set_switch(args); },
        MethodInfo{
            {{"device_no", "required", "str", "", "Device serial number or index"},
             {"switch_id", "required", "str", "", "Switch ID (e.g. 0x10)"},
             {"state",     "required", "str", "", "on or off"}},
            "int"
        });
}

json ServiceCleware::svc_api_get_all_devices_state(const json& /*args*/) {
    return m_cleware.getAllDevicesState();
}

json ServiceCleware::svc_api_set_switch(const json& args) {
    if (!args.is_array() || args.size() < 3) {
        throw std::invalid_argument(
            "Expected 3 arguments: [device_no, switch_id, state]");
    }

    // Parse device_no (string or int).
    int deviceNo = 0;
    if (args[0].is_string()) {
        deviceNo = std::stoi(args[0].get<std::string>());
    } else {
        deviceNo = args[0].get<int>();
    }

    // Parse switch_id (string like "0x10" or int like 16).
    int switchId = 0;
    if (args[1].is_string()) {
        std::string s = args[1].get<std::string>();
        switchId = std::stoi(s, nullptr, 0);  // auto-detect base (0x prefix)
    } else {
        switchId = args[1].get<int>();
    }

    // Parse state ("on"/"off" or bool).
    bool on = false;
    if (args[2].is_string()) {
        std::string state = args[2].get<std::string>();
        on = (state == "on" || state == "ON" || state == "1");
    } else {
        on = args[2].get<bool>();
    }

    int ret = m_cleware.setSwitch(deviceNo, switchId, on);

    // Notify connected GUIs of state change.
    notifyUpdates();

    return ret;
}

void ServiceCleware::notifyUpdates() {
    const std::string exchange = "updates_sw_state";
    const auto& cfg = getServiceConfig();

    // Open a short-lived connection to publish the update,
    // mirroring the Python version which opens a separate channel.
    RabbitMQConnection conn;
    if (!conn.Connect(cfg.broker_host, cfg.broker_port,
                      cfg.broker_vhost, cfg.broker_user, cfg.broker_pass)) {
        std::cerr << "[ServiceCleware] Failed to connect for update publish: "
                  << conn.GetLastError() << std::endl;
        return;
    }

    conn.DeclareExchange(exchange, "fanout");

    json state = m_cleware.getAllDevicesState();
    conn.Publish(exchange, "", state.dump());
    conn.Disconnect();

    std::cout << "[ServiceCleware] Published state update: " << state.dump() << std::endl;
}
