pragma Singleton
import QtQuick 2.15

// Design-time stub for the ServiceBridge singleton.
// Provides mock responses simulating 2 Cleware switch box devices.

QtObject {
    property string serviceName: "MockService"

    signal responseReceived(string method, string result)
    signal errorOccurred(string method, string error)

    // Mock device state:
    //   651082 — Switch Box mode (multiple switches can be on)
    //   710741 — Multiplexer mode (only one switch on = in1×out3 = index 2)
    property var mockState: {
        "651082": {"0": 1, "1": 0, "2": 0, "3": 1, "4": 0, "5": 0, "6": 0, "7": 0},
        "710741": {"0": 0, "1": 0, "2": 1, "3": 0, "4": 0, "5": 0, "6": 0, "7": 0}
    }

    function callService(serviceName, method, args) {
        console.log("[Stub] callService:", serviceName, method, JSON.stringify(args));

        if (method === "svc_api_get_all_devices_state") {
            Qt.callLater(function() {
                responseReceived(method, JSON.stringify(mockState));
            });
        } else if (method === "svc_api_set_switch") {
            // Toggle mock state
            if (args.length >= 3) {
                var device = String(args[0]);
                var swId = Number(args[1]) - 0x10;
                var on = (args[2] === "on") ? 1 : 0;
                if (mockState[device]) {
                    mockState[device][String(swId)] = on;
                }
            }
            Qt.callLater(function() {
                responseReceived(method, "1");
            });
        } else {
            Qt.callLater(function() {
                responseReceived(method, "(stub response for " + method + ")");
            });
        }
    }
}
