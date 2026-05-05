// ClewareAccess.h — Platform-specific wrapper for the Cleware USB DLL/SO.
//
// Loads USBaccessX64.dll (Windows) or USBAccessLinux.so (Linux) at runtime
// and exposes a clean C++ interface for switch operations.

#pragma once

#include <string>
#include <vector>
#include <map>
#include <nlohmann/json.hpp>

using json = nlohmann::json;

class ClewareAccess {
public:
    // Switch IDs (match CUSBaccess::SWITCH_IDs in USBaccess.h)
    static constexpr int SWITCH_0  = 0x10;
    static constexpr int SWITCH_7  = 0x17;
    static constexpr int NUM_SWITCHES = 8;

    ClewareAccess();
    ~ClewareAccess();

    // Initialize and open all connected Cleware devices.
    // Returns the number of devices found.
    int open();

    // Close all devices.
    void close();

    // Get the number of connected devices (from last open() call).
    int deviceCount() const { return m_deviceCount; }

    // Get serial number of a device.
    int getSerialNumber(int deviceNo);

    // Get USB type of a device.
    int getUSBType(int deviceNo);

    // Set a switch on a device.  on=true → 1, on=false → 0.
    // Returns 1 on success, 0 on failure.
    int setSwitch(int deviceNo, int switchId, bool on);

    // Get the state of a switch.  Returns 0 (off), 1 (on), or -1 (error).
    int getSwitch(int deviceNo, int switchId);

    // Get the state of all switches on all devices.
    // Returns: { "serial": { "0": 0, "1": 1, ... }, ... }
    json getAllDevicesState();

    // Check if the DLL/SO was loaded successfully.
    bool isLoaded() const { return m_lib != nullptr; }

private:
    void* m_lib = nullptr;     // DLL/SO handle
    void* m_usbObj = nullptr;  // CUSBaccess* from FCWInitObject()
    int   m_deviceCount = 0;

    // Function pointers (loaded at runtime via GetProcAddress / dlsym)
    using FnInitObject    = void* (__stdcall *)();
    using FnUnInitObject  = void  (__stdcall *)(void*);
    using FnOpenCleware   = int   (__stdcall *)(void*);
    using FnCloseCleware  = int   (__stdcall *)(void*);
    using FnSetSwitch     = int   (__stdcall *)(void*, int, int, int);
    using FnGetSwitch     = int   (__stdcall *)(void*, int, int);
    using FnGetSerialNo   = int   (__stdcall *)(void*, int);
    using FnGetUSBType    = int   (__stdcall *)(void*, int);

    FnInitObject    m_fnInit        = nullptr;
    FnUnInitObject  m_fnUnInit      = nullptr;
    FnOpenCleware   m_fnOpen        = nullptr;
    FnCloseCleware  m_fnClose       = nullptr;
    FnSetSwitch     m_fnSetSwitch   = nullptr;
    FnGetSwitch     m_fnGetSwitch   = nullptr;
    FnGetSerialNo   m_fnGetSerial   = nullptr;
    FnGetUSBType    m_fnGetUSBType  = nullptr;

    // Resolve a function pointer from the loaded library.
    void* resolve(const char* name);
};
