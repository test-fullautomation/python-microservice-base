// ServiceGui.h — serve the service's own Manager GUI folder over gRPC.
//
// The C++ side of MicroserviceBase/runtime/gui_server.py: the service
// answers microservicebase.gui.v1.ServiceGui so the Manager GUI fetches
// the folder from the service the first time it opens it, and again only
// when its checksum changes.  A C++ service ships files, nothing else.
//
//   rpc GetGuiInfo  (GuiInfoRequest)  returns (GuiInfo);         // folder, checksum, size, count
//   rpc GetGuiFiles (GuiFilesRequest) returns (stream GuiChunk); // the folder as a ZIP
//
// No generated code: the four messages are tiny and are encoded by hand,
// and the service is a gRPC callback generic service, so nothing extra has
// to be compiled with protoc.  ServiceRunner wires it in when the settings
// name a GUI folder (BaseServiceSettings::gui) and the files are found.
//
// Like the Python side, ServiceGui is not listed for reflection: clients
// walking the reflection list could not describe it.

#pragma once

#include <cstdint>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

#include <grpcpp/generic/callback_generic_service.h>

namespace microservice_base {

// The GUI folder of one service, as a checksum and a ZIP.  Both are built
// on first use and rebuilt only when a file's path, size or time changes.
class GuiPackage {
public:
    GuiPackage(std::string directory, std::string folder);

    // True when the folder exists and holds at least one file.
    bool exists() const;

    struct Built {
        std::string checksum;   // 32 hex chars
        std::string zip;        // the ZIP archive (stored, not compressed)
        uint32_t    file_count = 0;
    };
    // The current package, rebuilt when the folder changed since the last call.
    Built package();

    const std::string& folder() const { return m_folder; }
    const std::string& directory() const { return m_directory; }

private:
    std::string m_directory;
    std::string m_folder;
    std::mutex  m_mutex;
    bool        m_built = false;
    std::string m_signature;
    Built       m_cache;
};

// The gRPC side: a callback generic service answering only
// /microservicebase.gui.v1.ServiceGui/*; anything else is UNIMPLEMENTED.
class ServiceGuiService final : public grpc::CallbackGenericService {
public:
    explicit ServiceGuiService(std::shared_ptr<GuiPackage> package);

    grpc::ServerGenericBidiReactor* CreateReactor(grpc::GenericCallbackServerContext* ctx) override;

    static constexpr const char* kFullServiceName = "microservicebase.gui.v1.ServiceGui";
    // Chunk size of the ZIP stream (same as gui_proto.CHUNK_BYTES).
    static constexpr size_t kChunkBytes = 256 * 1024;

private:
    std::shared_ptr<GuiPackage> m_package;
};

// Where the GUI files of `gui` are: `explicitDir` when set, else the first
// existing folder of gui/<gui>, ui/<gui>, GUIs/<gui>, <gui> and
// ../interfaces/gui/<gui> next to the executable, then the same under the
// working directory.  Empty when none exists.
std::string resolveGuiDir(const std::string& gui, const std::string& explicitDir);

namespace gui_wire {
// Exposed for tests: the protobuf encodings of the ServiceGui messages.
std::string encodeGuiInfo(const std::string& folder, const std::string& checksum,
                          uint64_t sizeBytes, uint32_t fileCount, bool available);
std::string encodeGuiChunk(const std::string& data, const std::string& checksum, bool unchanged);
std::string decodeKnownChecksum(const std::string& guiFilesRequest);
std::string sha256Hex(const std::string& data);
uint32_t    crc32(const std::string& data);
}  // namespace gui_wire

}  // namespace microservice_base
