// ConsulRegistration.cpp — libcurl-based Consul registration.

#include "MicroserviceBase/ConsulRegistration.h"

#include <chrono>
#include <cstdio>
#include <iostream>
#include <random>
#include <sstream>

#include <curl/curl.h>

namespace microservice_base {

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

namespace {

// Minimal JSON escape — good enough for the short tag/meta strings we emit.
std::string jsonEscape(const std::string& s) {
    std::string out;
    out.reserve(s.size() + 2);
    for (char c : s) {
        switch (c) {
            case '"':  out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n";  break;
            case '\r': out += "\\r";  break;
            case '\t': out += "\\t";  break;
            default:
                if (static_cast<unsigned char>(c) < 0x20) {
                    char buf[8];
                    std::snprintf(buf, sizeof(buf), "\\u%04x", c);
                    out += buf;
                } else {
                    out += c;
                }
        }
    }
    return out;
}

std::string shortId() {
    static std::mt19937 rng{std::random_device{}()};
    std::uniform_int_distribution<int> dist(0, 15);
    const char* hex = "0123456789abcdef";
    std::string out(8, '0');
    for (auto& ch : out) ch = hex[dist(rng)];
    return out;
}

// libcurl write callback — we discard the body, we only care about the status.
size_t discardBody(char*, size_t size, size_t nmemb, void*) {
    return size * nmemb;
}

}  // namespace

// ---------------------------------------------------------------------------
// ConsulRegistration
// ---------------------------------------------------------------------------

ConsulRegistration::ConsulRegistration(std::string name,
                                       std::string address,
                                       int port,
                                       std::string consul_addr,
                                       std::vector<std::string> tags,
                                       std::map<std::string, std::string> meta,
                                       std::string token,
                                       std::string health_interval,
                                       std::string health_timeout,
                                       std::string deregister_after)
    : m_name(std::move(name)),
      m_address(std::move(address)),
      m_port(port),
      m_consulAddr(std::move(consul_addr)),
      m_tags(std::move(tags)),
      m_meta(std::move(meta)),
      m_token(std::move(token)),
      m_healthInterval(std::move(health_interval)),
      m_healthTimeout(std::move(health_timeout)),
      m_deregisterAfter(std::move(deregister_after))
{
    // Strip trailing slash for cleaner URL joining.
    if (!m_consulAddr.empty() && m_consulAddr.back() == '/')
        m_consulAddr.pop_back();

    m_serviceId = m_name + "-" + shortId();
}

ConsulRegistration::~ConsulRegistration() {
    deregisterService();
}

std::string ConsulRegistration::buildRegistrationJson() const {
    std::ostringstream ss;
    ss << "{";
    ss << "\"ID\":\""      << jsonEscape(m_serviceId) << "\",";
    ss << "\"Name\":\""    << jsonEscape(m_name)      << "\",";
    ss << "\"Address\":\"" << jsonEscape(m_address)   << "\",";
    ss << "\"Port\":"      << m_port                   << ",";

    ss << "\"Tags\":[";
    for (size_t i = 0; i < m_tags.size(); ++i) {
        if (i) ss << ",";
        ss << "\"" << jsonEscape(m_tags[i]) << "\"";
    }
    ss << "],";

    ss << "\"Meta\":{";
    bool first = true;
    for (const auto& [k, v] : m_meta) {
        if (!first) ss << ",";
        ss << "\"" << jsonEscape(k) << "\":\"" << jsonEscape(v) << "\"";
        first = false;
    }
    ss << "},";

    ss << "\"Check\":{";
    ss << "\"GRPC\":\"" << m_address << ":" << m_port << "\",";
    ss << "\"GRPCUseTLS\":false,";
    ss << "\"Interval\":\"" << m_healthInterval  << "\",";
    ss << "\"Timeout\":\""  << m_healthTimeout   << "\",";
    ss << "\"DeregisterCriticalServiceAfter\":\"" << m_deregisterAfter << "\"";
    ss << "}";

    ss << "}";
    return ss.str();
}

bool ConsulRegistration::httpPut(const std::string& path, const std::string& body) {
    CURL* curl = curl_easy_init();
    if (!curl) {
        m_lastError = "curl_easy_init failed";
        return false;
    }

    std::string url = m_consulAddr + path;

    struct curl_slist* headers = nullptr;
    headers = curl_slist_append(headers, "Content-Type: application/json");
    if (!m_token.empty()) {
        std::string h = "X-Consul-Token: " + m_token;
        headers = curl_slist_append(headers, h.c_str());
    }

    curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
    curl_easy_setopt(curl, CURLOPT_CUSTOMREQUEST, "PUT");
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, body.c_str());
    curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE, static_cast<long>(body.size()));
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, discardBody);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 5L);

    CURLcode rc = curl_easy_perform(curl);
    long status = 0;
    curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &status);

    curl_slist_free_all(headers);
    curl_easy_cleanup(curl);

    if (rc != CURLE_OK) {
        m_lastError = std::string("libcurl: ") + curl_easy_strerror(rc);
        return false;
    }
    if (status < 200 || status >= 300) {
        m_lastError = "Consul returned HTTP " + std::to_string(status);
        return false;
    }
    return true;
}

bool ConsulRegistration::registerService() {
    if (m_registered) return true;

    const std::string body = buildRegistrationJson();
    std::cout << "[ConsulRegistration] Registering service " << m_name
              << " (id=" << m_serviceId << ") at " << m_address << ":" << m_port
              << std::endl;

    if (!httpPut("/v1/agent/service/register", body)) {
        std::cerr << "[ConsulRegistration] Register failed: " << m_lastError << std::endl;
        return false;
    }
    m_registered = true;
    return true;
}

void ConsulRegistration::deregisterService() {
    if (!m_registered) return;
    std::cout << "[ConsulRegistration] Deregistering service " << m_serviceId << std::endl;
    if (!httpPut("/v1/agent/service/deregister/" + m_serviceId, "")) {
        std::cerr << "[ConsulRegistration] Deregister failed: " << m_lastError << std::endl;
    }
    m_registered = false;
}

}  // namespace microservice_base
