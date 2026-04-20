#include "TestServiceService.h"

namespace test_service {

std::string TestServiceService::echo(const std::string& message) const {
    return "echo: " + message;
}

int32_t TestServiceService::add(int32_t a, int32_t b) const {
    return a + b;
}

}  // namespace test_service
