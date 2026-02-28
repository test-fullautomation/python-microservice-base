pragma Singleton
import QtQuick 2.15

// Design-time stub for the ServiceBridge singleton.
// At runtime, the real C++ ServiceBridge is provided by the QML Shell.
// This stub lets Qt Creator resolve the import and provides mock signals
// so the QML designer can preview the UI without errors.

QtObject {
    property string serviceName: "MockService"

    signal responseReceived(string method, string result)
    signal errorOccurred(string method, string error)

    function callService(serviceName, method, args) {
        console.log("[Stub] callService:", serviceName, method, JSON.stringify(args));
        // Simulate a response after a short delay for preview purposes.
        Qt.callLater(function() {
            responseReceived(method, "(stub response for " + method + ")");
        });
    }
}
