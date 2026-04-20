#include "HelloService.h"

#include <algorithm>

namespace hello {

std::string HelloService::greet(const std::string& name) const {
    std::string who = name;
    // Trim + default.
    const auto not_space = [](char c) { return c != ' ' && c != '\t'; };
    auto left = std::find_if(who.begin(), who.end(), not_space);
    auto right = std::find_if(who.rbegin(), who.rend(), not_space).base();
    who = (left < right) ? std::string(left, right) : std::string();
    if (who.empty()) who = "world";
    return m_greeting + ", " + who + "!";
}

}  // namespace hello
