// ConsulResolver.cpp — Lightweight Consul HTTP lookup for ServiceClient.
//
// Uses raw sockets (no libcurl) so the client side has zero extra
// dependencies beyond grpc++ itself.  The resolver is intentionally
// simple: one HTTP GET to /v1/health/service/{name}?passing=true,
// parse the first healthy instance's Address + Port from the JSON.

#include "MicroserviceBase/ServiceClient.h"

#include <cstring>
#include <sstream>
#include <string>

#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
#pragma comment(lib, "ws2_32.lib")
#else
#include <sys/socket.h>
#include <netdb.h>
#include <unistd.h>
#define closesocket close
#endif

namespace microservice_base {
namespace detail {

// -----------------------------------------------------------------------
// Minimal HTTP GET over a raw TCP socket
// -----------------------------------------------------------------------

static std::string httpGet(const std::string& host, int port,
                           const std::string& path) {
#ifdef _WIN32
    WSADATA wsa;
    WSAStartup(MAKEWORD(2, 2), &wsa);
#endif

    addrinfo hints{}, *res = nullptr;
    hints.ai_family   = AF_INET;
    hints.ai_socktype = SOCK_STREAM;

    if (getaddrinfo(host.c_str(), std::to_string(port).c_str(),
                    &hints, &res) != 0 || !res) {
        return {};
    }

    int fd = static_cast<int>(socket(res->ai_family, res->ai_socktype, 0));
    if (fd < 0) { freeaddrinfo(res); return {}; }

    if (connect(fd, res->ai_addr, static_cast<int>(res->ai_addrlen)) != 0) {
        closesocket(fd);
        freeaddrinfo(res);
        return {};
    }
    freeaddrinfo(res);

    std::string req =
        "GET " + path + " HTTP/1.0\r\n"
        "Host: " + host + "\r\n"
        "Connection: close\r\n\r\n";
    send(fd, req.c_str(), static_cast<int>(req.size()), 0);

    std::string raw;
    char buf[4096];
    int n;
    while ((n = recv(fd, buf, sizeof(buf), 0)) > 0)
        raw.append(buf, n);
    closesocket(fd);

    auto pos = raw.find("\r\n\r\n");
    if (pos != std::string::npos)
        return raw.substr(pos + 4);
    return raw;
}

// -----------------------------------------------------------------------
// Naive JSON value extraction
// -----------------------------------------------------------------------

static std::string jsonStr(const std::string& json, const std::string& key) {
    std::string needle = "\"" + key + "\"";
    auto pos = json.find(needle);
    if (pos == std::string::npos) return {};
    pos = json.find('"', json.find(':', pos + needle.size()) + 1);
    if (pos == std::string::npos) return {};
    auto end = json.find('"', pos + 1);
    if (end == std::string::npos) return {};
    return json.substr(pos + 1, end - pos - 1);
}

static int jsonInt(const std::string& json, const std::string& key) {
    std::string needle = "\"" + key + "\"";
    auto pos = json.find(needle);
    if (pos == std::string::npos) return 0;
    pos = json.find(':', pos + needle.size()) + 1;
    while (pos < json.size() && (json[pos] == ' ' || json[pos] == '\t')) pos++;
    try { return std::stoi(json.substr(pos)); }
    catch (...) { return 0; }
}

// -----------------------------------------------------------------------
// Parse Consul URL into host + port
// -----------------------------------------------------------------------

static void parseUrl(const std::string& url, std::string& host, int& port) {
    auto start = url.find("://");
    std::string hp = (start != std::string::npos) ? url.substr(start + 3) : url;
    if (!hp.empty() && hp.back() == '/') hp.pop_back();
    auto colon = hp.rfind(':');
    if (colon != std::string::npos) {
        host = hp.substr(0, colon);
        try { port = std::stoi(hp.substr(colon + 1)); }
        catch (...) { port = 8500; }
    } else {
        host = hp;
        port = 8500;
    }
}

// -----------------------------------------------------------------------
// Public API
// -----------------------------------------------------------------------

ResolvedEndpoint resolveConsul(const std::string& consulAddr,
                               const std::string& serviceName) {
    std::string host;
    int port;
    parseUrl(consulAddr, host, port);

    std::string path =
        "/v1/health/service/" + serviceName + "?passing=true";

    std::string body = httpGet(host, port, path);
    if (body.empty())
        return {};

    // Find the first "Service" block in the JSON array.
    auto svcPos = body.find("\"Service\"");
    if (svcPos == std::string::npos)
        return {};

    std::string block = body.substr(svcPos);

    ResolvedEndpoint ep;
    ep.address = jsonStr(block, "Address");
    ep.port    = jsonInt(block, "Port");
    return ep;
}

}  // namespace detail
}  // namespace microservice_base
