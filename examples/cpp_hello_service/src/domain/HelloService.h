// HelloService.h — Pure business logic for the hello sample.
//
// No gRPC, no Consul, no I/O — just a class with two methods.  Mirrors
// examples/hello_service/domain/hello_service.py on the Python side.

#pragma once

#include <string>

namespace hello {

class HelloService {
public:
    explicit HelloService(std::string greeting = "Hello")
        : m_greeting(std::move(greeting)) {}

    // Return a greeting for *name*.
    std::string greet(const std::string& name) const;

    // Return *payload* unchanged.
    std::string echo(const std::string& payload) const { return payload; }

    const std::string& greeting() const { return m_greeting; }

private:
    std::string m_greeting;
};

}  // namespace hello
