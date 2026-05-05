// ClewareAccess.cpp — Runtime loading of the Cleware USB DLL/SO.

#include "ClewareAccess.h"

#include <iostream>
#include <filesystem>

#ifdef _WIN32
#include <windows.h>
#else
#include <dlfcn.h>
#endif

// ---------------------------------------------------------------------------
// Platform helpers
// ---------------------------------------------------------------------------

static void* loadLibrary(const std::string& path) {
#ifdef _WIN32
    return reinterpret_cast<void*>(::LoadLibraryA(path.c_str()));
#else
    return dlopen(path.c_str(), RTLD_LAZY);
#endif
}

static void freeLibrary(void* lib) {
#ifdef _WIN32
    ::FreeLibrary(reinterpret_cast<HMODULE>(lib));
#else
    dlclose(lib);
#endif
}

void* ClewareAccess::resolve(const char* name) {
    if (!m_lib) return nullptr;
#ifdef _WIN32
    return reinterpret_cast<void*>(
        ::GetProcAddress(reinterpret_cast<HMODULE>(m_lib), name));
#else
    return dlsym(m_lib, name);
#endif
}

// ---------------------------------------------------------------------------
// Constructor / Destructor
// ---------------------------------------------------------------------------

ClewareAccess::ClewareAccess() {
    // Find the library relative to the executable.
    namespace fs = std::filesystem;

#ifdef _WIN32
    // Try libs/Windows/USBaccessX64.dll next to the exe, then in source tree.
    const char* libName = "libs/Windows/USBaccessX64.dll";
#else
    const char* libName = "libs/Linux/USBAccessLinux.so";
#endif

    // Try several candidate paths.
    std::vector<std::string> candidates = {
        libName,                                   // relative to CWD
        std::string("../") + libName,              // one level up
    };

    for (const auto& path : candidates) {
        if (fs::exists(path)) {
            m_lib = loadLibrary(fs::absolute(path).string());
            if (m_lib) break;
        }
    }

    if (!m_lib) {
        std::cerr << "[ClewareAccess] WARNING: Could not load Cleware USB library ("
                  << libName << "). Hardware access disabled." << std::endl;
        return;
    }

    // Resolve function pointers.
    m_fnInit       = reinterpret_cast<FnInitObject>(resolve("FCWInitObject"));
    m_fnUnInit     = reinterpret_cast<FnUnInitObject>(resolve("FCWUnInitObject"));
    m_fnOpen       = reinterpret_cast<FnOpenCleware>(resolve("FCWOpenCleware"));
    m_fnClose      = reinterpret_cast<FnCloseCleware>(resolve("FCWCloseCleware"));
    m_fnSetSwitch  = reinterpret_cast<FnSetSwitch>(resolve("FCWSetSwitch"));
    m_fnGetSwitch  = reinterpret_cast<FnGetSwitch>(resolve("FCWGetSwitch"));
    m_fnGetSerial  = reinterpret_cast<FnGetSerialNo>(resolve("FCWGetSerialNumber"));
    m_fnGetUSBType = reinterpret_cast<FnGetUSBType>(resolve("FCWGetUSBType"));

    if (!m_fnInit || !m_fnOpen) {
        std::cerr << "[ClewareAccess] WARNING: Failed to resolve required functions." << std::endl;
        freeLibrary(m_lib);
        m_lib = nullptr;
        return;
    }

    // Initialize the USB access object.
    m_usbObj = m_fnInit();
    if (m_usbObj) {
        m_deviceCount = open();
        std::cout << "[ClewareAccess] Initialized. Devices found: "
                  << m_deviceCount << std::endl;
    }
}

ClewareAccess::~ClewareAccess() {
    if (m_usbObj) {
        close();
        if (m_fnUnInit) m_fnUnInit(m_usbObj);
        m_usbObj = nullptr;
    }
    if (m_lib) {
        freeLibrary(m_lib);
        m_lib = nullptr;
    }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

int ClewareAccess::open() {
    if (!m_usbObj || !m_fnOpen) return 0;
    m_deviceCount = m_fnOpen(m_usbObj);
    return m_deviceCount;
}

void ClewareAccess::close() {
    if (m_usbObj && m_fnClose) {
        m_fnClose(m_usbObj);
    }
}

int ClewareAccess::getSerialNumber(int deviceNo) {
    if (!m_usbObj || !m_fnGetSerial) return -1;
    return m_fnGetSerial(m_usbObj, deviceNo);
}

int ClewareAccess::getUSBType(int deviceNo) {
    if (!m_usbObj || !m_fnGetUSBType) return -1;
    return m_fnGetUSBType(m_usbObj, deviceNo);
}

int ClewareAccess::setSwitch(int deviceNo, int switchId, bool on) {
    if (!m_usbObj || !m_fnSetSwitch) return 0;
    return m_fnSetSwitch(m_usbObj, deviceNo, switchId, on ? 1 : 0);
}

int ClewareAccess::getSwitch(int deviceNo, int switchId) {
    if (!m_usbObj || !m_fnGetSwitch) return -1;
    return m_fnGetSwitch(m_usbObj, deviceNo, switchId);
}

json ClewareAccess::getAllDevicesState() {
    json result = json::object();

    // Re-open to refresh device list.
    m_deviceCount = open();

    for (int d = 0; d < m_deviceCount; ++d) {
        int serial = getSerialNumber(d);
        std::string key = std::to_string(serial);

        json switches = json::object();
        for (int p = 0; p < NUM_SWITCHES; ++p) {
            int state = getSwitch(serial, SWITCH_0 + p);
            switches[std::to_string(p)] = state;
        }
        result[key] = switches;
    }

    return result;
}
