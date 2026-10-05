// ServiceGui.cpp — see ServiceGui.h.

#include "MicroserviceBase/ServiceGui.h"

#include <algorithm>
#include <array>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <utility>

#ifdef _WIN32
#include <windows.h>
#else
#include <climits>
#include <unistd.h>
#endif

namespace fs = std::filesystem;

namespace microservice_base {

// ---------------------------------------------------------------------------
// Wire helpers: SHA-256, CRC-32, protobuf varints
// ---------------------------------------------------------------------------

namespace gui_wire {

namespace {

constexpr std::array<uint32_t, 64> kSha256K = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2};

inline uint32_t rotr(uint32_t x, int n) { return (x >> n) | (x << (32 - n)); }

void putVarint(std::string& out, uint64_t v) {
    while (v >= 0x80) {
        out.push_back(static_cast<char>((v & 0x7f) | 0x80));
        v >>= 7;
    }
    out.push_back(static_cast<char>(v));
}

void putKey(std::string& out, uint32_t field, uint32_t wireType) { putVarint(out, (field << 3) | wireType); }

void putBytes(std::string& out, uint32_t field, const std::string& value) {
    if (value.empty()) return;               // proto3: defaults are not written
    putKey(out, field, 2);
    putVarint(out, value.size());
    out += value;
}

void putUint(std::string& out, uint32_t field, uint64_t value) {
    if (!value) return;
    putKey(out, field, 0);
    putVarint(out, value);
}

bool getVarint(const std::string& in, size_t& pos, uint64_t& v) {
    v = 0;
    for (int shift = 0; shift < 64 && pos < in.size(); shift += 7) {
        auto b = static_cast<uint8_t>(in[pos++]);
        v |= static_cast<uint64_t>(b & 0x7f) << shift;
        if (!(b & 0x80)) return true;
    }
    return false;
}

}  // namespace

std::string sha256Hex(const std::string& data) {
    uint32_t h[8] = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
                     0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
    std::string msg = data;
    const uint64_t bitLen = static_cast<uint64_t>(data.size()) * 8;
    msg.push_back(static_cast<char>(0x80));
    while (msg.size() % 64 != 56) msg.push_back('\0');
    for (int i = 7; i >= 0; --i) msg.push_back(static_cast<char>((bitLen >> (i * 8)) & 0xff));

    for (size_t chunk = 0; chunk < msg.size(); chunk += 64) {
        uint32_t w[64];
        for (int i = 0; i < 16; ++i) {
            const auto* p = reinterpret_cast<const uint8_t*>(msg.data() + chunk + i * 4);
            w[i] = (uint32_t(p[0]) << 24) | (uint32_t(p[1]) << 16) | (uint32_t(p[2]) << 8) | p[3];
        }
        for (int i = 16; i < 64; ++i) {
            uint32_t s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >> 3);
            uint32_t s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16] + s0 + w[i - 7] + s1;
        }
        uint32_t a = h[0], b = h[1], c = h[2], d = h[3], e = h[4], f = h[5], g = h[6], hh = h[7];
        for (int i = 0; i < 64; ++i) {
            uint32_t S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
            uint32_t ch = (e & f) ^ (~e & g);
            uint32_t t1 = hh + S1 + ch + kSha256K[i] + w[i];
            uint32_t S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
            uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
            uint32_t t2 = S0 + maj;
            hh = g; g = f; f = e; e = d + t1; d = c; c = b; b = a; a = t1 + t2;
        }
        h[0] += a; h[1] += b; h[2] += c; h[3] += d; h[4] += e; h[5] += f; h[6] += g; h[7] += hh;
    }
    static const char* hex = "0123456789abcdef";
    std::string out;
    for (uint32_t v : h)
        for (int i = 7; i >= 0; --i) out.push_back(hex[(v >> (i * 4)) & 0xf]);
    return out;
}

uint32_t crc32(const std::string& data) {
    static const std::array<uint32_t, 256> table = [] {   // thread-safe initialisation
        std::array<uint32_t, 256> t{};
        for (uint32_t i = 0; i < 256; ++i) {
            uint32_t c = i;
            for (int k = 0; k < 8; ++k) c = (c & 1) ? 0xEDB88320u ^ (c >> 1) : c >> 1;
            t[i] = c;
        }
        return t;
    }();
    uint32_t crc = 0xFFFFFFFFu;
    for (unsigned char ch : data) crc = table[(crc ^ ch) & 0xff] ^ (crc >> 8);
    return crc ^ 0xFFFFFFFFu;
}

std::string encodeGuiInfo(const std::string& folder, const std::string& checksum,
                          uint64_t sizeBytes, uint32_t fileCount, bool available) {
    std::string out;
    putBytes(out, 1, folder);
    putBytes(out, 2, checksum);
    putUint(out, 3, sizeBytes);
    putUint(out, 4, fileCount);
    putUint(out, 5, available ? 1 : 0);
    return out;
}

std::string encodeGuiChunk(const std::string& data, const std::string& checksum, bool unchanged) {
    std::string out;
    putBytes(out, 1, data);
    putBytes(out, 2, checksum);
    putUint(out, 3, unchanged ? 1 : 0);
    return out;
}

std::string decodeKnownChecksum(const std::string& in) {
    size_t pos = 0;
    std::string known;
    while (pos < in.size()) {
        uint64_t key = 0;
        if (!getVarint(in, pos, key)) break;
        const uint32_t field = static_cast<uint32_t>(key >> 3), wt = static_cast<uint32_t>(key & 7);
        uint64_t len = 0;
        if (wt == 0) { if (!getVarint(in, pos, len)) break; }
        else if (wt == 1) { pos += 8; }
        else if (wt == 5) { pos += 4; }
        else if (wt == 2) {
            if (!getVarint(in, pos, len) || pos + len > in.size()) break;
            if (field == 1) known = in.substr(pos, static_cast<size_t>(len));
            pos += static_cast<size_t>(len);
        } else break;
    }
    return known;
}

}  // namespace gui_wire

// ---------------------------------------------------------------------------
// GuiPackage
// ---------------------------------------------------------------------------

namespace {

// A file name as UTF-8 (ZIP names are flagged UTF-8); u8string() is
// std::u8string from C++20 on.
std::string utf8(const fs::path& p) {
    const auto s = p.u8string();
    return std::string(s.begin(), s.end());
}

bool skipDir(const std::string& name) {
    return name == "__pycache__" || name == ".git" || name == "node_modules" || name == ".idea" || name == ".vscode";
}

bool skipFile(const std::string& name) {
    for (const char* suf : {".pyc", ".pyo", ".log", ".tmp", "~"}) {
        const size_t n = std::strlen(suf);
        if (name.size() >= n && name.compare(name.size() - n, n, suf) == 0) return true;
    }
    return false;
}

// (absolute path, archive path) of every file worth shipping: the files of a
// folder in name order, then its subfolders in name order (as os.walk).
void walk(const fs::path& dir, const std::string& prefix, std::vector<std::pair<fs::path, std::string>>& out) {
    std::vector<fs::directory_entry> files, dirs;
    std::error_code ec;
    for (const auto& e : fs::directory_iterator(dir, ec)) {
        if (e.is_directory(ec)) { if (!skipDir(e.path().filename().string())) dirs.push_back(e); }
        else if (e.is_regular_file(ec)) { if (!skipFile(e.path().filename().string())) files.push_back(e); }
    }
    auto byName = [](const fs::directory_entry& a, const fs::directory_entry& b) {
        return a.path().filename().string() < b.path().filename().string();
    };
    std::sort(files.begin(), files.end(), byName);
    std::sort(dirs.begin(), dirs.end(), byName);
    for (const auto& f : files) out.emplace_back(f.path(), prefix + utf8(f.path().filename()));
    for (const auto& d : dirs) walk(d.path(), prefix + utf8(d.path().filename()) + "/", out);
}

std::string readFile(const fs::path& p) {
    std::ifstream in(p, std::ios::binary);
    std::ostringstream ss;
    ss << in.rdbuf();
    return ss.str();
}

void put16(std::string& s, uint16_t v) { s.push_back(char(v & 0xff)); s.push_back(char(v >> 8)); }
void put32(std::string& s, uint32_t v) { for (int i = 0; i < 4; ++i) s.push_back(char((v >> (8 * i)) & 0xff)); }

}  // namespace

GuiPackage::GuiPackage(std::string directory, std::string folder)
    : m_directory(std::move(directory)), m_folder(std::move(folder)) {}

bool GuiPackage::exists() const {
    std::error_code ec;
    if (!fs::is_directory(m_directory, ec)) return false;
    std::vector<std::pair<fs::path, std::string>> files;
    walk(m_directory, "", files);
    return !files.empty();
}

GuiPackage::Built GuiPackage::package() {
    std::lock_guard<std::mutex> lock(m_mutex);
    std::vector<std::pair<fs::path, std::string>> files;
    walk(m_directory, "", files);

    // Cheap change detector: path, size and time of every file.
    std::ostringstream sig;
    for (const auto& f : files) {
        std::error_code ec;
        sig << f.second << '|' << fs::file_size(f.first, ec) << '|'
            << fs::last_write_time(f.first, ec).time_since_epoch().count() << '\n';
    }
    if (m_built && sig.str() == m_signature) return m_cache;

    std::string digestInput;     // path \0 content, per file: a rename alone changes the sum
    std::string zip, central;
    uint16_t count = 0;
    for (const auto& f : files) {
        const std::string data = readFile(f.first);
        const std::string& name = f.second;
        digestInput += name;
        digestInput.push_back('\0');
        digestInput += data;

        const uint32_t crc = gui_wire::crc32(data);
        const uint32_t offset = static_cast<uint32_t>(zip.size());
        // Local file header: stored (method 0), UTF-8 name (flag bit 11).
        put32(zip, 0x04034b50); put16(zip, 20); put16(zip, 0x0800); put16(zip, 0);
        put16(zip, 0); put16(zip, 0x21);                       // time 00:00, date 1980-01-01
        put32(zip, crc); put32(zip, uint32_t(data.size())); put32(zip, uint32_t(data.size()));
        put16(zip, uint16_t(name.size())); put16(zip, 0);
        zip += name;
        zip += data;
        // Central directory entry.
        put32(central, 0x02014b50); put16(central, 20); put16(central, 20); put16(central, 0x0800); put16(central, 0);
        put16(central, 0); put16(central, 0x21);
        put32(central, crc); put32(central, uint32_t(data.size())); put32(central, uint32_t(data.size()));
        put16(central, uint16_t(name.size())); put16(central, 0); put16(central, 0);
        put16(central, 0); put16(central, 0); put32(central, 0); put32(central, offset);
        central += name;
        ++count;
    }
    const uint32_t centralOffset = static_cast<uint32_t>(zip.size());
    zip += central;
    put32(zip, 0x06054b50); put16(zip, 0); put16(zip, 0); put16(zip, count); put16(zip, count);
    put32(zip, uint32_t(central.size())); put32(zip, centralOffset); put16(zip, 0);

    m_cache.checksum = gui_wire::sha256Hex(digestInput).substr(0, 32);
    m_cache.zip = std::move(zip);
    m_cache.file_count = count;
    m_signature = sig.str();
    m_built = true;
    std::cout << "[ServiceGui] package " << m_folder << ": " << count << " file(s), "
              << m_cache.zip.size() << " bytes" << std::endl;
    return m_cache;
}

// ---------------------------------------------------------------------------
// ServiceGuiService
// ---------------------------------------------------------------------------

namespace {

grpc::ByteBuffer toBuffer(const std::string& s) {
    grpc::Slice slice(s.data(), s.size());
    return grpc::ByteBuffer(&slice, 1);
}

std::string fromBuffer(const grpc::ByteBuffer& b) {
    std::vector<grpc::Slice> slices;
    std::string out;
    if (!b.Dump(&slices).ok()) return out;
    for (const auto& s : slices) out.append(reinterpret_cast<const char*>(s.begin()), s.size());
    return out;
}

// One call: read the single request, then write one answer (GetGuiInfo) or
// the chunks (GetGuiFiles) one after the other.
class GuiReactor final : public grpc::ServerGenericBidiReactor {
public:
    GuiReactor(std::shared_ptr<GuiPackage> package, std::string method)
        : m_package(std::move(package)), m_method(std::move(method)) {
        StartRead(&m_request);
    }

    void OnReadDone(bool ok) override {
        if (!ok) { Finish(grpc::Status(grpc::StatusCode::INVALID_ARGUMENT, "no request")); return; }
        const std::string request = fromBuffer(m_request);
        try {
            if (m_method == "GetGuiInfo") {
                std::string reply;
                if (!m_package->exists()) {
                    reply = gui_wire::encodeGuiInfo(m_package->folder(), "", 0, 0, false);
                } else {
                    const auto built = m_package->package();
                    reply = gui_wire::encodeGuiInfo(m_package->folder(), built.checksum, built.zip.size(),
                                                    built.file_count, true);
                }
                m_out.push_back(std::move(reply));
            } else {   // GetGuiFiles
                if (!m_package->exists()) {
                    Finish(grpc::Status(grpc::StatusCode::NOT_FOUND,
                                        m_package->folder() + ": this service ships no GUI files"));
                    return;
                }
                const auto built = m_package->package();
                if (gui_wire::decodeKnownChecksum(request) == built.checksum) {
                    m_out.push_back(gui_wire::encodeGuiChunk("", built.checksum, true));
                } else {
                    for (size_t start = 0; start < built.zip.size(); start += ServiceGuiService::kChunkBytes) {
                        m_out.push_back(gui_wire::encodeGuiChunk(
                            built.zip.substr(start, ServiceGuiService::kChunkBytes), built.checksum, false));
                    }
                }
            }
        } catch (const std::exception& e) {
            Finish(grpc::Status(grpc::StatusCode::INTERNAL, e.what()));
            return;
        }
        next();
    }

    void OnWriteDone(bool ok) override {
        if (!ok) { Finish(grpc::Status(grpc::StatusCode::CANCELLED, "client went away")); return; }
        next();
    }

    void OnDone() override { delete this; }

private:
    void next() {
        if (m_index >= m_out.size()) { Finish(grpc::Status::OK); return; }
        m_buffer = toBuffer(m_out[m_index++]);
        StartWrite(&m_buffer);
    }

    std::shared_ptr<GuiPackage> m_package;
    std::string                 m_method;
    grpc::ByteBuffer            m_request;
    grpc::ByteBuffer            m_buffer;
    std::vector<std::string>    m_out;
    size_t                      m_index = 0;
};

class Unimplemented final : public grpc::ServerGenericBidiReactor {
public:
    explicit Unimplemented(const std::string& method) {
        Finish(grpc::Status(grpc::StatusCode::UNIMPLEMENTED, "unknown method " + method));
    }
    void OnDone() override { delete this; }
};

}  // namespace

ServiceGuiService::ServiceGuiService(std::shared_ptr<GuiPackage> package) : m_package(std::move(package)) {}

grpc::ServerGenericBidiReactor* ServiceGuiService::CreateReactor(grpc::GenericCallbackServerContext* ctx) {
    const std::string prefix = std::string("/") + kFullServiceName + "/";
    const std::string& method = ctx->method();
    if (method.compare(0, prefix.size(), prefix) == 0) {
        const std::string name = method.substr(prefix.size());
        if (name == "GetGuiInfo" || name == "GetGuiFiles") return new GuiReactor(m_package, name);
    }
    return new Unimplemented(method);
}

// ---------------------------------------------------------------------------
// Finding the folder
// ---------------------------------------------------------------------------

namespace {

fs::path executableDir() {
#ifdef _WIN32
    wchar_t buf[MAX_PATH] = {0};
    const DWORD n = GetModuleFileNameW(nullptr, buf, MAX_PATH);
    if (n > 0 && n < MAX_PATH) return fs::path(buf).parent_path();
#else
    char buf[PATH_MAX] = {0};
    const ssize_t n = readlink("/proc/self/exe", buf, sizeof(buf) - 1);
    if (n > 0) return fs::path(std::string(buf, static_cast<size_t>(n))).parent_path();
#endif
    return fs::current_path();
}

}  // namespace

std::string resolveGuiDir(const std::string& gui, const std::string& explicitDir) {
    std::error_code ec;
    if (!explicitDir.empty()) {
        if (fs::is_directory(explicitDir, ec)) return fs::absolute(explicitDir, ec).string();
        std::cerr << "[ServiceGui] GUI_DIR " << explicitDir << " is not a directory; serving no GUI files" << std::endl;
        return {};
    }
    if (gui.empty()) return {};
    for (const fs::path& base : {executableDir(), fs::current_path(ec)}) {
        for (const fs::path& candidate : {base / "gui" / gui, base / "ui" / gui, base / "GUIs" / gui, base / gui,
                                          base / ".." / "interfaces" / "gui" / gui}) {
            if (fs::is_directory(candidate, ec)) return fs::weakly_canonical(candidate, ec).string();
        }
    }
    return {};
}

}  // namespace microservice_base
