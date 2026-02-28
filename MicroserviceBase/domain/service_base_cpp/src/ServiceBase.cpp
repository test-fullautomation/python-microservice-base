// ServiceBase.cpp — Cross-platform protocol implementation for MicroserviceBase-compatible services.
//
// Extracted from cpp_mfc_service_template, with MFC/Windows dependencies removed.
// Uses blocking serve() instead of background thread + HWND notifications.

#include "ServiceBase.h"

#include <iostream>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <filesystem>
#include <algorithm>
#include <cstring>

#ifdef _WIN32
#  include <winsock2.h>
#  include <windows.h>
#  include <wincrypt.h>
#  pragma comment(lib, "advapi32.lib")
#else
#  include <openssl/md5.h>
#endif

#ifdef HAS_ZLIB
#  include <zlib.h>
#endif

namespace fs = std::filesystem;

// Static member for signal handling.
ServiceBase* ServiceBase::s_activeInstance = nullptr;

// ---------------------------------------------------------------------------
// Construction / destruction
// ---------------------------------------------------------------------------

ServiceBase::ServiceBase(const ServiceInfo& info, const ServiceConfig& config)
    : m_info(info), m_config(config)
{
    // Register built-in API methods.
    // svc_api_get_version is published (Python publishes it too).
    registerMethod("svc_api_get_version",
        [this](const json& args) { return svc_api_get_version(args); },
        MethodInfo{{}, "str"});

    // Internal methods: dispatchable via RPC but not published in methods/methods_info.
    registerInternalMethod("svc_api_shutdown",
        [this](const json& args) { return svc_api_shutdown(args); });

    registerInternalMethod("svc_api_get_gui_files",
        [this](const json& args) { return svc_api_get_gui_files(args); });

    registerInternalMethod("svc_api_get_gui_checksum",
        [this](const json& args) { return svc_api_get_gui_checksum(args); });

    registerInternalMethod("svc_api_get_service_files",
        [this](const json& args) { return svc_api_get_service_files(args); });
}

ServiceBase::~ServiceBase() {
    try { unregisterService(); } catch (...) {}
    shutdown();
}

// ---------------------------------------------------------------------------
// Method registration
// ---------------------------------------------------------------------------

void ServiceBase::registerMethod(const std::string& name, ApiHandler handler,
                                  const MethodInfo& info) {
    m_apiMethods[name] = std::move(handler);
    m_info.methods.push_back(name);
    m_info.methods_info[name] = info;
}

void ServiceBase::registerInternalMethod(const std::string& name, ApiHandler handler) {
    m_apiMethods[name] = std::move(handler);
}

// ---------------------------------------------------------------------------
// Built-in API methods
// ---------------------------------------------------------------------------

json ServiceBase::svc_api_get_version(const json& /*args*/) {
    return m_info.version;
}

json ServiceBase::svc_api_shutdown(const json& /*args*/) {
    unregisterService();
    shutdown();
    return json{{"status", "shutting_down"}};
}

// ---------------------------------------------------------------------------
// Helpers for GUI file APIs
// ---------------------------------------------------------------------------

namespace {

// Base64 encode (RFC 4648)
std::string base64Encode(const std::vector<uint8_t>& data) {
    static const char table[] =
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    std::string out;
    out.reserve(((data.size() + 2) / 3) * 4);
    size_t i = 0;
    for (; i + 2 < data.size(); i += 3) {
        uint32_t n = (uint32_t(data[i]) << 16) | (uint32_t(data[i+1]) << 8) | data[i+2];
        out += table[(n >> 18) & 0x3F];
        out += table[(n >> 12) & 0x3F];
        out += table[(n >>  6) & 0x3F];
        out += table[ n        & 0x3F];
    }
    if (i + 1 == data.size()) {
        uint32_t n = uint32_t(data[i]) << 16;
        out += table[(n >> 18) & 0x3F];
        out += table[(n >> 12) & 0x3F];
        out += '=';
        out += '=';
    } else if (i + 2 == data.size()) {
        uint32_t n = (uint32_t(data[i]) << 16) | (uint32_t(data[i+1]) << 8);
        out += table[(n >> 18) & 0x3F];
        out += table[(n >> 12) & 0x3F];
        out += table[(n >>  6) & 0x3F];
        out += '=';
    }
    return out;
}

// MD5 hex digest of a byte sequence.
std::string md5Hex(const std::vector<uint8_t>& data) {
#ifdef _WIN32
    HCRYPTPROV hProv = 0;
    HCRYPTHASH hHash = 0;
    CryptAcquireContextW(&hProv, nullptr, nullptr, PROV_RSA_AES,
                          CRYPT_VERIFYCONTEXT);
    CryptCreateHash(hProv, CALG_MD5, 0, 0, &hHash);
    CryptHashData(hHash, data.data(), static_cast<DWORD>(data.size()), 0);
    BYTE hash[16];
    DWORD hashLen = 16;
    CryptGetHashParam(hHash, HP_HASHVAL, hash, &hashLen, 0);
    CryptDestroyHash(hHash);
    CryptReleaseContext(hProv, 0);
#else
    unsigned char hash[16];
    MD5(data.data(), data.size(), hash);
#endif
    char hex[33];
    for (int i = 0; i < 16; ++i)
        snprintf(hex + i * 2, 3, "%02x", hash[i]);
    return std::string(hex, 32);
}

// Read an entire file into a byte vector.
std::vector<uint8_t> readFileBytes(const fs::path& path) {
    std::ifstream f(path, std::ios::binary | std::ios::ate);
    if (!f) return {};
    auto sz = f.tellg();
    f.seekg(0);
    std::vector<uint8_t> buf(static_cast<size_t>(sz));
    f.read(reinterpret_cast<char*>(buf.data()), sz);
    return buf;
}

// ---------------------------------------------------------------------------
// Minimal ZIP creator (STORE + optional DEFLATE via zlib).
// Creates a valid ZIP file in memory from a list of {arcname, data} entries.
// ---------------------------------------------------------------------------

struct ZipEntry {
    std::string name;
    std::vector<uint8_t> data;
};

void writeLe16(std::vector<uint8_t>& out, uint16_t v) {
    out.push_back(static_cast<uint8_t>(v));
    out.push_back(static_cast<uint8_t>(v >> 8));
}

void writeLe32(std::vector<uint8_t>& out, uint32_t v) {
    out.push_back(static_cast<uint8_t>(v));
    out.push_back(static_cast<uint8_t>(v >> 8));
    out.push_back(static_cast<uint8_t>(v >> 16));
    out.push_back(static_cast<uint8_t>(v >> 24));
}

// CRC-32 (ISO 3309)
uint32_t crc32Calc(const uint8_t* data, size_t len) {
    uint32_t crc = 0xFFFFFFFF;
    for (size_t i = 0; i < len; ++i) {
        crc ^= data[i];
        for (int j = 0; j < 8; ++j)
            crc = (crc >> 1) ^ (0xEDB88320 & (-(crc & 1)));
    }
    return ~crc;
}

// Compression method constants for ZIP.
constexpr uint16_t ZIP_STORE   = 0;
constexpr uint16_t ZIP_DEFLATE = 8;

#ifdef HAS_ZLIB
// Raw DEFLATE compress (windowBits=-15 for ZIP-compatible raw deflate).
std::vector<uint8_t> deflateCompress(const uint8_t* data, size_t len) {
    z_stream strm{};
    // -15 = raw deflate (no zlib/gzip header)
    if (deflateInit2(&strm, Z_DEFAULT_COMPRESSION, Z_DEFLATED,
                     -15, 8, Z_DEFAULT_STRATEGY) != Z_OK) {
        return {};
    }
    strm.next_in  = const_cast<Bytef*>(data);
    strm.avail_in = static_cast<uInt>(len);

    std::vector<uint8_t> out;
    out.resize(deflateBound(&strm, static_cast<uLong>(len)));
    strm.next_out  = out.data();
    strm.avail_out = static_cast<uInt>(out.size());

    int ret = deflate(&strm, Z_FINISH);
    deflateEnd(&strm);
    if (ret != Z_STREAM_END) return {};

    out.resize(strm.total_out);
    return out;
}
#endif

std::vector<uint8_t> createZip(const std::vector<ZipEntry>& entries,
                               uint16_t compression = ZIP_STORE) {
    std::vector<uint8_t> out;
    struct CentralRec { uint32_t offset; std::string name; uint32_t crc;
                        uint32_t compSize; uint32_t uncompSize; uint16_t method; };
    std::vector<CentralRec> central;

    for (auto& e : entries) {
        CentralRec rec;
        rec.offset     = static_cast<uint32_t>(out.size());
        rec.name       = e.name;
        rec.crc        = crc32Calc(e.data.data(), e.data.size());
        rec.uncompSize = static_cast<uint32_t>(e.data.size());
        rec.method     = ZIP_STORE;

        const std::vector<uint8_t>* fileData = &e.data;
        std::vector<uint8_t> compressed;

#ifdef HAS_ZLIB
        if (compression == ZIP_DEFLATE && !e.data.empty()) {
            compressed = deflateCompress(e.data.data(), e.data.size());
            if (!compressed.empty()) {
                fileData = &compressed;
                rec.method = ZIP_DEFLATE;
            }
        }
#endif
        rec.compSize = static_cast<uint32_t>(fileData->size());

        // Local file header
        writeLe32(out, 0x04034b50);       // signature
        writeLe16(out, 20);               // version needed
        writeLe16(out, 0);                // flags
        writeLe16(out, rec.method);       // compression method
        writeLe16(out, 0);                // mod time
        writeLe16(out, 0);                // mod date
        writeLe32(out, rec.crc);
        writeLe32(out, rec.compSize);     // compressed size
        writeLe32(out, rec.uncompSize);   // uncompressed size
        writeLe16(out, static_cast<uint16_t>(e.name.size()));
        writeLe16(out, 0);                // extra length
        out.insert(out.end(), e.name.begin(), e.name.end());
        out.insert(out.end(), fileData->begin(), fileData->end());

        central.push_back(std::move(rec));
    }

    // Central directory
    uint32_t cdOffset = static_cast<uint32_t>(out.size());
    for (auto& rec : central) {
        writeLe32(out, 0x02014b50);       // signature
        writeLe16(out, 20);               // version made by
        writeLe16(out, 20);               // version needed
        writeLe16(out, 0);                // flags
        writeLe16(out, rec.method);       // compression method
        writeLe16(out, 0);                // mod time
        writeLe16(out, 0);                // mod date
        writeLe32(out, rec.crc);
        writeLe32(out, rec.compSize);
        writeLe32(out, rec.uncompSize);
        writeLe16(out, static_cast<uint16_t>(rec.name.size()));
        writeLe16(out, 0);                // extra
        writeLe16(out, 0);                // comment
        writeLe16(out, 0);                // disk
        writeLe16(out, 0);                // internal attr
        writeLe32(out, 0);                // external attr
        writeLe32(out, rec.offset);
        out.insert(out.end(), rec.name.begin(), rec.name.end());
    }

    uint32_t cdSize = static_cast<uint32_t>(out.size()) - cdOffset;

    // End of central directory
    writeLe32(out, 0x06054b50);
    writeLe16(out, 0);                    // disk
    writeLe16(out, 0);                    // disk with CD
    writeLe16(out, static_cast<uint16_t>(central.size()));
    writeLe16(out, static_cast<uint16_t>(central.size()));
    writeLe32(out, cdSize);
    writeLe32(out, cdOffset);
    writeLe16(out, 0);                    // comment len

    return out;
}

// Collect files under a directory into ZipEntry list with relative arcnames.
std::vector<ZipEntry> collectDir(const fs::path& dir) {
    std::vector<ZipEntry> entries;
    if (!fs::is_directory(dir)) return entries;
    for (auto& p : fs::recursive_directory_iterator(dir)) {
        if (!p.is_regular_file()) continue;
        ZipEntry e;
        e.name = fs::relative(p.path(), dir).generic_string();
        e.data = readFileBytes(p.path());
        entries.push_back(std::move(e));
    }
    // Sort for deterministic output (matches Python's sorted traversal).
    std::sort(entries.begin(), entries.end(),
              [](const ZipEntry& a, const ZipEntry& b) { return a.name < b.name; });
    return entries;
}

} // anonymous namespace

// ---------------------------------------------------------------------------
// Built-in GUI API methods (mirrors Python service_base.py)
// ---------------------------------------------------------------------------

json ServiceBase::svc_api_get_gui_files(const json& /*args*/) {
    if (!m_info.gui_support) return nullptr;

    fs::path guisPath = fs::path(m_config.service_dir) / "GUIs";
    if (!fs::is_directory(guisPath)) {
        log("[WARN] GUIs directory not found at " + guisPath.string());
        return nullptr;
    }

    auto entries = collectDir(guisPath);
    if (entries.empty()) return nullptr;

    auto zipData = createZip(entries);
    return base64Encode(zipData);
}

json ServiceBase::svc_api_get_gui_checksum(const json& /*args*/) {
    if (!m_info.gui_support) return nullptr;

    fs::path guisPath = fs::path(m_config.service_dir) / "GUIs";
    if (!fs::is_directory(guisPath)) return nullptr;

    // Build the same hash as Python: hash(relative_path + file_contents)
    // with sorted file traversal.
    std::vector<uint8_t> hashInput;
    std::vector<std::pair<std::string, fs::path>> files;
    for (auto& p : fs::recursive_directory_iterator(guisPath)) {
        if (!p.is_regular_file()) continue;
        std::string rel = fs::relative(p.path(), guisPath).generic_string();
        files.emplace_back(rel, p.path());
    }
    std::sort(files.begin(), files.end());

    for (auto& [rel, path] : files) {
        hashInput.insert(hashInput.end(), rel.begin(), rel.end());
        auto content = readFileBytes(path);
        hashInput.insert(hashInput.end(), content.begin(), content.end());
    }

    return md5Hex(hashInput);
}

json ServiceBase::svc_api_get_service_files(const json& /*args*/) {
    if (!m_info.downloadable) return nullptr;

    fs::path serviceDir = fs::path(m_config.service_dir);
    if (!fs::is_directory(serviceDir)) return nullptr;

    std::string folderName = serviceDir.filename().string();
    auto rawEntries = collectDir(serviceDir);

    // Prepend folder name to arcnames (matches Python pattern).
    for (auto& e : rawEntries) {
        e.name = folderName + "/" + e.name;
    }

    // Use DEFLATE when zlib available (matches Python ZIP_DEFLATED),
    // falls back to STORE otherwise.
    uint16_t method = ZIP_STORE;
#ifdef HAS_ZLIB
    method = ZIP_DEFLATE;
#endif
    auto zipData = createZip(rawEntries, method);
    return base64Encode(zipData);
}

// ---------------------------------------------------------------------------
// Register / Unregister
// ---------------------------------------------------------------------------

void ServiceBase::registerService() {
    try {
        publishServiceEvent("on");
        log("[INFO] Service registered: " + m_info.name);
    } catch (const std::exception& e) {
        m_lastError = std::string("registerService failed: ") + e.what();
        throw;
    }
}

void ServiceBase::unregisterService() {
    try {
        publishServiceEvent("off");
        log("[INFO] Service unregistered: " + m_info.name);
    } catch (const std::exception& e) {
        m_lastError = std::string("unregisterService failed: ") + e.what();
        // Don't rethrow during shutdown — best-effort unregister.
    }
}

void ServiceBase::publishServiceEvent(const std::string& state) {
    // Use a separate short-lived connection (mirrors Python pattern).
    RabbitMQConnection conn;
    if (!conn.Connect(m_config.broker_host, m_config.broker_port,
                      m_config.broker_vhost, m_config.broker_user,
                      m_config.broker_pass)) {
        throw std::runtime_error(conn.GetLastError());
    }

    // Declare service_information exchange (topic).
    if (!conn.DeclareExchange("service_information", "topic")) {
        throw std::runtime_error(conn.GetLastError());
    }

    // Declare service_infor_queue (durable).
    if (conn.DeclareQueue("service_infor_queue", /*durable=*/true).empty()) {
        throw std::runtime_error(conn.GetLastError());
    }

    // Bind queue.
    if (!conn.BindQueue("service_infor_queue", "service_information",
                         "service.information")) {
        throw std::runtime_error(conn.GetLastError());
    }

    // Build registration payload.
    json payload = {
        {"info",  m_info.to_json()},
        {"state", state}
    };

    // Publish with delivery_mode=2 (persistent).
    if (!conn.Publish("service_information", "service.information",
                       payload.dump(), /*delivery_mode=*/2)) {
        throw std::runtime_error(conn.GetLastError());
    }

    conn.Disconnect();
}

// ---------------------------------------------------------------------------
// Signal handling
// ---------------------------------------------------------------------------

void ServiceBase::signalHandler(int /*sig*/) {
    if (s_activeInstance) {
        try { s_activeInstance->unregisterService(); } catch (...) {}
        s_activeInstance->shutdown();
    }
}

#ifdef _WIN32
int __stdcall ServiceBase::consoleCtrlHandler(unsigned long ctrlType) {
    if (ctrlType == 0 /*CTRL_C_EVENT*/ || ctrlType == 1 /*CTRL_BREAK_EVENT*/) {
        signalHandler(0);
        return 1; // handled
    }
    return 0;
}
#endif

// ---------------------------------------------------------------------------
// Serve (blocking consume loop)
// ---------------------------------------------------------------------------

void ServiceBase::serve() {
    if (m_serving.load()) {
        m_lastError = "Already serving";
        return;
    }

    // Install signal handlers for graceful shutdown.
    s_activeInstance = this;
    auto prevSigint  = std::signal(SIGINT,  signalHandler);
    auto prevSigterm = std::signal(SIGTERM, signalHandler);
#ifdef _WIN32
    SetConsoleCtrlHandler(consoleCtrlHandler, TRUE);
#endif

    m_serving.store(true);
    RabbitMQConnection conn;

    // Connect.
    if (!conn.Connect(m_config.broker_host, m_config.broker_port,
                      m_config.broker_vhost, m_config.broker_user,
                      m_config.broker_pass)) {
        log("[ERROR] Connect failed: " + conn.GetLastError());
        m_serving.store(false);
        return;
    }

    // Declare services_request exchange (direct).
    if (!conn.DeclareExchange("services_request", "direct")) {
        log("[ERROR] DeclareExchange failed: " + conn.GetLastError());
        conn.Disconnect();
        m_serving.store(false);
        return;
    }

    // Declare queue = service name.
    std::string queueName = conn.DeclareQueue(m_info.name);
    if (queueName.empty()) {
        log("[ERROR] DeclareQueue failed: " + conn.GetLastError());
        conn.Disconnect();
        m_serving.store(false);
        return;
    }

    // Purge old messages.
    conn.PurgeQueue(m_info.name);

    // Bind with routing_key.
    if (!conn.BindQueue(m_info.name, "services_request", m_info.routing_key)) {
        log("[ERROR] BindQueue failed: " + conn.GetLastError());
        conn.Disconnect();
        m_serving.store(false);
        return;
    }

    // Set prefetch = 1.
    conn.SetPrefetch(1);

    // Start consumer.
    if (!conn.StartConsume(m_info.name)) {
        log("[ERROR] StartConsume failed: " + conn.GetLastError());
        conn.Disconnect();
        m_serving.store(false);
        return;
    }

    log("[INFO] Awaiting RPC requests on queue '" + m_info.name + "'...");

    // Poll loop with 1s timeout (mirrors Python process_data_events(time_limit=1)).
    while (m_serving.load()) {
        ConsumedMessage envelope = conn.ConsumeOne(/*timeout_sec=*/1);
        if (!envelope.received) continue;

        try {
            ServiceRequest req = ServiceRequest::from_message(
                envelope.body, envelope.reply_to, envelope.correlation_id,
                envelope.delivery_tag);

            log("[REQ] " + req.method +
                " args=" + (req.args.is_null() ? "null" : req.args.dump()));

            // Dispatch and get response.
            ServiceResponse resp = dispatchRequest(req);

            // Publish response to default exchange, routing_key = reply_to.
            conn.Publish(/*exchange=*/"", req.reply_to,
                         resp.serialize(), /*delivery_mode=*/0,
                         req.correlation_id);

            // Ack.
            conn.Ack(req.delivery_tag);

            m_requestCount.fetch_add(1);

            log("[RESP] " + resp.result + ": " +
                (resp.result_data.is_string()
                     ? resp.result_data.get<std::string>()
                     : resp.result_data.dump()));

            onRequestProcessed(req, resp);
        }
        catch (const std::exception& e) {
            log("[ERROR] Failed to process message: " + std::string(e.what()));
            // Ack even on error to avoid redelivery loop.
            conn.Ack(envelope.delivery_tag);
        }
    }

    log("[INFO] Consume loop stopped.");
    conn.Disconnect();

    // Restore previous signal handlers.
    std::signal(SIGINT,  prevSigint);
    std::signal(SIGTERM, prevSigterm);
#ifdef _WIN32
    SetConsoleCtrlHandler(consoleCtrlHandler, FALSE);
#endif
    s_activeInstance = nullptr;
}

void ServiceBase::shutdown() {
    m_serving.store(false);
}

// ---------------------------------------------------------------------------
// Dispatch
// ---------------------------------------------------------------------------

ServiceResponse ServiceBase::dispatchRequest(const ServiceRequest& req) {
    auto it = m_apiMethods.find(req.method);
    if (it != m_apiMethods.end()) {
        try {
            json result = it->second(req.args);
            return ServiceResponse::pass(req.method, result);
        }
        catch (const std::exception& e) {
            return ServiceResponse::exception(req.method, e.what());
        }
    }

    // Fallback: subclass dynamic dispatch (mirrors Python two-stage dispatch).
    if (isSpecificRequest(req.method)) {
        try {
            return onSpecificRequest(req);
        }
        catch (const std::exception& e) {
            return ServiceResponse::exception(req.method, e.what());
        }
    }

    return ServiceResponse::fail(req.method, "Unknown method: " + req.method);
}

// ---------------------------------------------------------------------------
// Service-to-service RPC
// ---------------------------------------------------------------------------

json ServiceBase::requestService(const json& requestData,
                                  const std::string& exchange,
                                  const std::string& routingKey,
                                  int timeoutSec) {
    RabbitMQConnection conn;
    if (!conn.Connect(m_config.broker_host, m_config.broker_port,
                      m_config.broker_vhost, m_config.broker_user,
                      m_config.broker_pass)) {
        throw std::runtime_error("RPC connect failed: " + conn.GetLastError());
    }

    // Declare exclusive reply queue.
    std::string replyQueue = conn.DeclareQueue("", /*durable=*/false,
                                                /*exclusive=*/true,
                                                /*auto_delete=*/true);
    if (replyQueue.empty()) {
        throw std::runtime_error("RPC DeclareQueue failed: " + conn.GetLastError());
    }

    conn.StartConsume(replyQueue);

    // Generate correlation ID.
    std::string corrId = std::to_string(
        std::chrono::steady_clock::now().time_since_epoch().count());

    // Publish request.
    if (!conn.Publish(exchange, routingKey,
                       requestData.dump(), /*delivery_mode=*/0,
                       corrId, replyQueue)) {
        throw std::runtime_error("RPC Publish failed: " + conn.GetLastError());
    }

    // Wait for response.
    auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(timeoutSec);
    while (std::chrono::steady_clock::now() < deadline) {
        ConsumedMessage msg = conn.ConsumeOne(1);
        if (msg.received && msg.correlation_id == corrId) {
            conn.Ack(msg.delivery_tag);
            conn.Disconnect();
            return json::parse(msg.body);
        }
    }

    conn.Disconnect();
    throw std::runtime_error("RPC timeout after " + std::to_string(timeoutSec) + "s");
}

// ---------------------------------------------------------------------------
// Logger
// ---------------------------------------------------------------------------

void ServiceBase::log(const std::string& message) {
    std::cout << "[" << m_info.name << "] " << message << std::endl;
}
