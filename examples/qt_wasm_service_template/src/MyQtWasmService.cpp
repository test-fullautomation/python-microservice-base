// MyQtWasmService.cpp — Example service implementing svc_api_* business methods.

#include "MyQtWasmService.h"

#include <numeric>
#include <sstream>
#include <stdexcept>

MyQtWasmService::MyQtWasmService(const ServiceInfo& info, const ServiceConfig& config)
    : ServiceBase(info, config)
{
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
            {{"numbers", "required", "str", "", "Comma-separated numbers to sum"}},
            "number"
        });
}

json MyQtWasmService::svc_api_hello(const json& args) {
    std::string name = "World";
    if (args.is_array() && !args.empty()) {
        name = args[0].get<std::string>();
    } else if (args.is_string()) {
        name = args.get<std::string>();
    }
    return "Hello, " + name + "!";
}

json MyQtWasmService::svc_api_echo(const json& args) {
    if (args.is_array() && !args.empty()) {
        return args[0];
    }
    return args;
}

json MyQtWasmService::svc_api_compute(const json& args) {
    // UI sends input as a string (from QLineEdit), e.g. "1,2,3".
    // Parse the comma-separated numbers.
    std::string input;
    if (args.is_array() && !args.empty()) {
        if (args[0].is_string()) {
            input = args[0].get<std::string>();
        } else if (args[0].is_array()) {
            // Also support direct array format.
            double sum = 0.0;
            for (const auto& n : args[0]) {
                sum += n.get<double>();
            }
            return sum;
        } else {
            throw std::invalid_argument("Expected a comma-separated string or array of numbers");
        }
    } else {
        throw std::invalid_argument("Expected an argument");
    }

    double sum = 0.0;
    std::istringstream ss(input);
    std::string token;
    while (std::getline(ss, token, ',')) {
        auto start = token.find_first_not_of(" \t");
        if (start == std::string::npos) continue;
        token = token.substr(start);
        sum += std::stod(token);
    }
    return sum;
}
