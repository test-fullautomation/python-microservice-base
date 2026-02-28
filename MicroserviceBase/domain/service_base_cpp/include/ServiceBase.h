// ServiceBase.h — Cross-platform abstract base for MicroserviceBase-compatible C++ services.
//
// Mirrors MicroserviceBase/domain/service_base.py:
// - registerService / unregisterService via service_information exchange
// - serve() blocking consume loop with 1s timeout poll
// - dispatchRequest via registered method map
//
// Extracted from cpp_mfc_service_template, with MFC/Windows dependencies removed.

#pragma once

#include "RabbitMQConnection.h"
#include "ServiceConfig.h"
#include "ServiceMessages.h"

#include <map>
#include <atomic>
#include <thread>
#include <string>
#include <iostream>
#include <csignal>

class ServiceBase {
public:
    explicit ServiceBase(const ServiceInfo& info, const ServiceConfig& config = {});
    virtual ~ServiceBase();

    // Non-copyable.
    ServiceBase(const ServiceBase&) = delete;
    ServiceBase& operator=(const ServiceBase&) = delete;

    // --- Lifecycle ----------------------------------------------------------

    // Register this service with the registry (publish state="on").
    void registerService();

    // Unregister (publish state="off").
    void unregisterService();

    // Blocking consume loop (runs on the calling thread).
    // Call shutdown() from another thread or from svc_api_shutdown to stop.
    void serve();

    // Signal the consume loop to stop.
    void shutdown();

    // API parity with Python's close().
    void close() { shutdown(); }

    // --- Built-in API methods -----------------------------------------------

    json svc_api_get_version(const json& args);
    json svc_api_shutdown(const json& args);
    json svc_api_get_gui_files(const json& args);
    json svc_api_get_gui_checksum(const json& args);
    json svc_api_get_service_files(const json& args);

    // --- Static helpers -----------------------------------------------------

    // Create a request payload (mirrors Python create_request_data()).
    static json createRequestData(const std::string& method, const json& args) {
        return {{"method", method}, {"args", args}};
    }

    // --- Accessors ----------------------------------------------------------

    const ServiceInfo& getServiceInfo() const { return m_info; }
    const ServiceConfig& getServiceConfig() const { return m_config; }
    bool isServing() const { return m_serving.load(); }
    int  getRequestCount() const { return m_requestCount.load(); }
    const std::string& getLastError() const { return m_lastError; }

protected:
    // Register an API handler (called by subclass constructors).
    void registerMethod(const std::string& name, ApiHandler handler,
                        const MethodInfo& info = {});

    // Service-to-service RPC (call another service).
    json requestService(const json& requestData,
                        const std::string& exchange,
                        const std::string& routingKey,
                        int timeoutSec = 30);

    // Override in subclass to receive notification when a request is processed.
    virtual void onRequestProcessed(const ServiceRequest& req,
                                    const ServiceResponse& resp) {}

    // Dispatch hooks — override in subclass for dynamic method routing.
    // Return true if this method should be dispatched via onSpecificRequest().
    virtual bool isSpecificRequest(const std::string& method) { return false; }
    // Handle a request matched by isSpecificRequest().
    virtual ServiceResponse onSpecificRequest(const ServiceRequest& req) {
        return ServiceResponse::fail(req.method, "Not implemented");
    }

    // Logger hook — override to redirect output (default: std::cout).
    virtual void log(const std::string& message);

private:
    // Register an internal method (dispatchable but not published in service info).
    void registerInternalMethod(const std::string& name, ApiHandler handler);

    ServiceResponse dispatchRequest(const ServiceRequest& req);

    void publishServiceEvent(const std::string& state);

    // Signal handling for graceful shutdown in serve().
    static void signalHandler(int sig);
#ifdef _WIN32
    static int __stdcall consoleCtrlHandler(unsigned long ctrlType);
#endif

    ServiceInfo                         m_info;
    ServiceConfig                       m_config;
    std::map<std::string, ApiHandler>   m_apiMethods;
    std::atomic<bool>                   m_serving{false};
    std::atomic<int>                    m_requestCount{0};
    std::string                         m_lastError;

    static ServiceBase*                 s_activeInstance;
};
