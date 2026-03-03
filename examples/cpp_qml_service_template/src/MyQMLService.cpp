// MyQMLService.cpp — Example service implementing svc_api_* business methods.

#include "MyQMLService.h"

#include <numeric>
#include <stdexcept>

MyQMLService::MyQMLService(const ServiceInfo& info, const ServiceConfig& config)
    : ServiceBase(info, config)
{
    // Register business API methods with metadata.

    registerMethod("svc_api_hello",
        [this](const json& args) { return svc_api_hello(args); },
        MethodInfo{
            {{"name", "required", "str", "", "Name to greet"}},
            "str"
        });

    registerMethod("svc_api_echo",
        [this](const json& args) { return svc_api_echo(args); },
        MethodInfo{
            {{"message", "required", "str", "", "Message to echo back"}},
            "str"
        });

    registerMethod("svc_api_compute",
        [this](const json& args) { return svc_api_compute(args); },
        MethodInfo{
            {{"numbers", "required", "list", "", "List of numbers to sum"}},
            "number"
        });
}

json MyQMLService::svc_api_hello(const json& args) {
    std::string name = "World";
    if (args.is_array() && !args.empty()) {
        name = args[0].get<std::string>();
    } else if (args.is_string()) {
        name = args.get<std::string>();
    }
    return "Hello, " + name + "!";
}

json MyQMLService::svc_api_echo(const json& args) {
    if (args.is_array() && !args.empty()) {
        return args[0];
    }
    return args;
}

json MyQMLService::svc_api_compute(const json& args) {
    json numbers;
    if (args.is_array() && !args.empty()) {
        numbers = args[0];
    } else {
        throw std::invalid_argument("Expected an array of numbers");
    }

    if (!numbers.is_array()) {
        throw std::invalid_argument("Expected an array of numbers");
    }

    double sum = 0.0;
    for (const auto& n : numbers) {
        sum += n.get<double>();
    }
    return sum;
}
