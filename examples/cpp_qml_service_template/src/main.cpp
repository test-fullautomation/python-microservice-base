// main.cpp — Entry point for the MyQMLService backend.
//
// Loads configuration, creates the service, registers with RabbitMQ, and serves.

#include "MyQMLService.h"

#include <fstream>
#include <iostream>
#include <csignal>
#include <filesystem>

static MyQMLService* g_service = nullptr;

void signalHandler(int /*sig*/) {
    if (g_service) {
        std::cout << "\n[INFO] Shutdown signal received." << std::endl;
        g_service->unregisterService();
        g_service->shutdown();
    }
}

int main(int argc, char* argv[]) {
    // Determine config file path.
    std::string configPath = "service_config.json";
    if (argc > 1) {
        configPath = argv[1];
    }

    // Load configuration.
    std::ifstream configFile(configPath);
    if (!configFile.is_open()) {
        std::cerr << "ERROR: Cannot open config file: " << configPath << std::endl;
        return 1;
    }

    json configJson;
    try {
        configFile >> configJson;
    } catch (const std::exception& e) {
        std::cerr << "ERROR: Invalid JSON in config file: " << e.what() << std::endl;
        return 1;
    }

    // Build ServiceInfo from config.
    ServiceInfo info = ServiceInfo::from_json(configJson);

    // Build ServiceConfig (broker connection).
    ServiceConfig config;
    config.broker_host  = configJson.value("broker_host",  "localhost");
    config.broker_port  = configJson.value("broker_port",  5672);
    config.broker_vhost = configJson.value("broker_vhost", "/");
    config.broker_user  = configJson.value("broker_user",  "guest");
    config.broker_pass  = configJson.value("broker_pass",  "guest");

    // Set service_dir to the directory containing the config file.
    // This is where the GUIs/ folder lives (for svc_api_get_gui_files).
    {
        std::filesystem::path cfgPath = std::filesystem::absolute(configPath);
        config.service_dir = cfgPath.parent_path().string();
    }

    // Create service.
    MyQMLService service(info, config);
    g_service = &service;

    // Handle Ctrl+C for graceful shutdown.
    std::signal(SIGINT,  signalHandler);
    std::signal(SIGTERM, signalHandler);

    // Register and serve.
    try {
        service.registerService();
        std::cout << "[INFO] " << info.name << " v" << info.version
                  << " started. Press Ctrl+C to stop." << std::endl;
        service.serve();
    } catch (const std::exception& e) {
        std::cerr << "FATAL: " << e.what() << std::endl;
        return 1;
    }

    std::cout << "[INFO] " << info.name << " stopped." << std::endl;
    return 0;
}
