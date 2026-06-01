// ServiceMessages.h — Request, response, and method metadata structures.
//
// Mirrors MicroserviceBase/domain/messages.py and models.py.

#pragma once

#include <nlohmann/json.hpp>
#include <string>
#include <vector>
#include <functional>

using json = nlohmann::json;

// Callback type for API methods: takes JSON args, returns JSON result.
using ApiHandler = std::function<json(const json& args)>;

// --- Method metadata (mirrors Python ServiceMethod / MethodArgument) --------

struct MethodArgument {
    std::string name;
    std::string condition;   // "required" or "optional"
    std::string type;        // "str", "int", etc.
    std::string default_val;
    std::string description;

    json to_json() const {
        return {
            {"name",        name},
            {"condition",   condition},
            {"type",        type},
            {"default",     default_val.empty() ? json(nullptr) : json(default_val)},
            {"description", description}
        };
    }
};

struct MethodInfo {
    std::vector<MethodArgument> arguments;
    std::string return_type;

    json to_json() const {
        json args = json::array();
        for (auto& arg : arguments) {
            args.push_back(arg.to_json());
        }
        json j = {{"arguments", args}};
        if (!return_type.empty()) {
            j["return_type"] = return_type;
        }
        return j;
    }
};

// --- Service info (mirrors Python ServiceInfo / _SERVICE_INFO) ---------------

struct ServiceInfo {
    std::string name;
    std::string version;
    std::string routing_key;
    std::string description;
    std::string shortdesc;
    std::string group;
    std::string tag;
    bool        gui_support  = false;
    bool        downloadable = false;
    std::vector<std::string>            methods;
    std::map<std::string, MethodInfo>   methods_info;

    json to_json() const {
        json methods_arr = json::array();
        for (auto& m : methods) {
            methods_arr.push_back(m);
        }
        json methods_info_obj = json::object();
        for (auto& [name, info] : methods_info) {
            methods_info_obj[name] = info.to_json();
        }
        return {
            {"name",         name},
            {"version",      version},
            {"routing_key",  routing_key},
            {"description",  description},
            {"shortdesc",    shortdesc},
            {"group",        group},
            {"tag",          tag},
            {"gui_support",  gui_support},
            {"downloadable", downloadable},
            {"methods",      methods_arr},
            {"methods_info", methods_info_obj}
        };
    }

    static ServiceInfo from_json(const json& j) {
        ServiceInfo si;
        si.name         = j.value("name",         "");
        si.version      = j.value("version",      "1.0.0");
        si.routing_key  = j.value("routing_key",  "");
        si.description  = j.value("description",  "");
        si.shortdesc    = j.value("shortdesc",    "");
        si.group        = j.value("group",        "");
        si.tag          = j.value("tag",          "");
        si.gui_support  = j.value("gui_support",  false);
        si.downloadable = j.value("downloadable", false);
        return si;
    }
};

// --- Request (mirrors Python ServiceRequest) ---------------------------------

struct ServiceRequest {
    std::string method;
    json        args;           // null, string, or array
    std::string reply_to;       // Callback queue name
    std::string correlation_id;
    uint64_t    delivery_tag = 0;

    static ServiceRequest from_message(const std::string& body,
                                       const std::string& reply_to,
                                       const std::string& correlation_id,
                                       uint64_t delivery_tag) {
        ServiceRequest req;
        json j           = json::parse(body);
        req.method       = j.value("method", "");
        req.args         = j.contains("args") ? j["args"] : json(nullptr);
        req.reply_to     = reply_to;
        req.correlation_id = correlation_id;
        req.delivery_tag = delivery_tag;
        return req;
    }
};

// --- Response (mirrors Python ServiceResponse) --------------------------------

struct ServiceResponse {
    std::string request;       // Method name that was called
    std::string result;        // "pass", "fail", or "exception"
    json        result_data;   // Return value or error message

    json to_json() const {
        return {
            {"request",     request},
            {"result",      result},
            {"result_data", result_data}
        };
    }

    std::string serialize() const {
        return to_json().dump();
    }

    static ServiceResponse pass(const std::string& method, const json& data) {
        return {method, "pass", data};
    }

    static ServiceResponse fail(const std::string& method, const std::string& msg) {
        return {method, "fail", msg};
    }

    static ServiceResponse exception(const std::string& method, const std::string& msg) {
        return {method, "exception", msg};
    }
};
