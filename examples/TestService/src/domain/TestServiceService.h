#pragma once

#include <cstdint>
#include <string>

namespace test_service {

class TestServiceService {
public:
    std::string echo(const std::string& message) const;
    int32_t     add(int32_t a, int32_t b) const;
};

}  // namespace test_service
