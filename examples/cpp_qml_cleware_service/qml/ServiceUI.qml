import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import MicroserviceBase 1.0

Rectangle {
    id: root
    width: 600
    height: 800
    color: "#f5f5f5"

    // Current device serial (selected from dropdown)
    property string currentDevice: ""
    // "switchbox" or "multiplexer"
    property string deviceType: "switchbox"
    // All devices state: { "serial": { "0": 0, "1": 1, ... } }
    property var devicesState: ({})
    // State revision counter — increment to force UI refresh
    property int stateRevision: 0

    // ---- Header ----
    Rectangle {
        id: header
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: 72
        color: "#2E7D32"

        Label {
            anchors.left: parent.left
            anchors.leftMargin: 20
            anchors.top: parent.top
            anchors.topMargin: 14
            text: "ServiceCleware"
            font.pixelSize: 22
            font.bold: true
            color: "#ffffff"
        }

        Label {
            anchors.left: parent.left
            anchors.leftMargin: 20
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 12
            text: "Cleware USB Switch Box Controller"
            font.pixelSize: 13
            color: "#c8e6c9"
        }
    }

    // ---- Device Selection card ----
    Rectangle {
        id: deviceCard
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: header.bottom
        anchors.leftMargin: 16
        anchors.rightMargin: 16
        anchors.topMargin: 16
        height: 150
        radius: 8
        color: "#ffffff"
        border.color: "#e0e0e0"
        border.width: 1

        Label {
            id: deviceTitle
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.leftMargin: 16
            anchors.topMargin: 14
            text: "Configuration"
            font.pixelSize: 15
            font.bold: true
            color: "#333333"
        }

        // Device Number row
        Row {
            id: deviceRow
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: deviceTitle.bottom
            anchors.leftMargin: 16
            anchors.rightMargin: 16
            anchors.topMargin: 12
            spacing: 10

            Label {
                width: 100
                text: "Device:"
                font.pixelSize: 14
                anchors.verticalCenter: parent.verticalCenter
                color: "#555555"
            }

            ComboBox {
                id: deviceCombo
                width: parent.width - 220
                model: []
                displayText: currentDevice || "No devices — click Initialize"
                font.pixelSize: 14
                onActivated: {
                    currentDevice = model[currentIndex]
                    bumpRevision()
                }
            }

            Button {
                id: initBtn
                text: "Initialize"
                font.pixelSize: 14
                highlighted: true
                onClicked: ServiceBridge.callService(
                    "ServiceCleware", "svc_api_get_all_devices_state", [])
            }
        }

        // Device Type row
        Row {
            id: typeRow
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: deviceRow.bottom
            anchors.leftMargin: 16
            anchors.rightMargin: 16
            anchors.topMargin: 10
            spacing: 10

            Label {
                width: 100
                text: "Device Type:"
                font.pixelSize: 14
                anchors.verticalCenter: parent.verticalCenter
                color: "#555555"
            }

            ComboBox {
                id: typeCombo
                width: parent.width - 110
                model: ["Switch Box", "USB Multiplexer"]
                font.pixelSize: 14
                onActivated: {
                    deviceType = (currentIndex === 0) ? "switchbox" : "multiplexer"
                }
            }
        }
    }

    // ---- Device view area (Switch Box or Multiplexer) ----
    Loader {
        id: deviceView
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: deviceCard.bottom
        anchors.leftMargin: 16
        anchors.rightMargin: 16
        anchors.topMargin: 14
        height: item ? item.implicitHeight : 300
        sourceComponent: deviceType === "multiplexer" ? multiplexerView : switchBoxView
    }

    // ---- Result / Status card ----
    Rectangle {
        id: resultCard
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: deviceView.bottom
        anchors.bottom: versionBtn.top
        anchors.leftMargin: 16
        anchors.rightMargin: 16
        anchors.topMargin: 14
        anchors.bottomMargin: 14
        radius: 8
        color: "#ffffff"
        border.color: "#e0e0e0"
        border.width: 1

        Label {
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.leftMargin: 16
            anchors.topMargin: 14
            text: "Status"
            font.pixelSize: 15
            font.bold: true
            color: "#333333"
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.leftMargin: 16
            anchors.rightMargin: 16
            anchors.topMargin: 42
            anchors.bottomMargin: 14
            color: "#fafafa"
            radius: 4
            border.color: "#eeeeee"
            border.width: 1

            Label {
                id: resultLabel
                anchors.fill: parent
                anchors.margins: 10
                text: "Click Initialize to scan for Cleware devices..."
                wrapMode: Text.Wrap
                font.pixelSize: 14
                color: "#555555"
                verticalAlignment: Text.AlignTop
            }
        }
    }

    // ---- Get Version button ----
    Button {
        id: versionBtn
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.rightMargin: 16
        anchors.bottomMargin: 16
        text: "Get Version"
        font.pixelSize: 13
        flat: true
        onClicked: ServiceBridge.callService(
            "ServiceCleware", "svc_api_get_version", [])
    }

    // ===================================================================
    // Switch Box component — 8 toggle LEDs
    // ===================================================================
    Component {
        id: switchBoxView

        Rectangle {
            implicitHeight: 260
            radius: 8
            color: "#ffffff"
            border.color: "#e0e0e0"
            border.width: 1

            Label {
                id: swTitle
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.leftMargin: 16
                anchors.topMargin: 14
                text: "Switch Box"
                font.pixelSize: 15
                font.bold: true
                color: "#333333"
            }

            Label {
                anchors.left: swTitle.right
                anchors.leftMargin: 10
                anchors.verticalCenter: swTitle.verticalCenter
                text: currentDevice ? ("Device: " + currentDevice) : ""
                font.pixelSize: 12
                color: "#888888"
            }

            // 8 LED indicators
            Row {
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.top: swTitle.bottom
                anchors.topMargin: 20
                spacing: 16

                Repeater {
                    model: 8

                    Column {
                        spacing: 8

                        Rectangle {
                            width: 48; height: 48; radius: 24
                            color: ledState(index) ? "#4CAF50" : "#424242"
                            border.color: ledState(index) ? "#2E7D32" : "#616161"
                            border.width: 2
                            property bool isOn: ledState(index)

                            Rectangle {
                                anchors.centerIn: parent
                                width: parent.width - 8; height: parent.height - 8
                                radius: width / 2
                                color: "transparent"
                                border.color: parent.isOn ? "#81C784" : "transparent"
                                border.width: 2; opacity: 0.6
                            }

                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: toggleSwitch(index)
                            }

                            Behavior on color { ColorAnimation { duration: 150 } }
                        }

                        Label {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: "SW" + index
                            font.pixelSize: 11; color: "#666666"
                        }
                    }
                }
            }

            // All On / All Off / Refresh
            Row {
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 16
                spacing: 12

                Button {
                    text: "All On"; font.pixelSize: 13
                    enabled: currentDevice !== ""
                    onClicked: {
                        for (var i = 0; i < 8; i++)
                            ServiceBridge.callService("ServiceCleware",
                                "svc_api_set_switch", [currentDevice, 0x10 + i, "on"])
                    }
                }
                Button {
                    text: "All Off"; font.pixelSize: 13
                    enabled: currentDevice !== ""
                    onClicked: {
                        for (var i = 0; i < 8; i++)
                            ServiceBridge.callService("ServiceCleware",
                                "svc_api_set_switch", [currentDevice, 0x10 + i, "off"])
                    }
                }
                Button {
                    text: "Refresh"; font.pixelSize: 13; flat: true
                    enabled: currentDevice !== ""
                    onClicked: ServiceBridge.callService(
                        "ServiceCleware", "svc_api_get_all_devices_state", [])
                }
            }
        }
    }

    // ===================================================================
    // Multiplexer component — 2 USB In × 4 USB Out matrix
    // ===================================================================
    Component {
        id: multiplexerView

        Rectangle {
            implicitHeight: 320
            radius: 8
            color: "#ffffff"
            border.color: "#e0e0e0"
            border.width: 1

            Label {
                id: muxTitle
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.leftMargin: 16
                anchors.topMargin: 14
                text: "USB Multiplexer"
                font.pixelSize: 15
                font.bold: true
                color: "#333333"
            }

            Label {
                anchors.left: muxTitle.right
                anchors.leftMargin: 10
                anchors.verticalCenter: muxTitle.verticalCenter
                text: currentDevice ? ("Device: " + currentDevice) : ""
                font.pixelSize: 12
                color: "#888888"
            }

            // Mapping: index = inPort * 4 + outPort
            // switch index 0-7 maps to: in1×out1, in1×out2, in1×out3, in1×out4,
            //                           in2×out1, in2×out2, in2×out3, in2×out4

            Column {
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.top: muxTitle.bottom
                anchors.topMargin: 16
                spacing: 12

                // USB In row
                Row {
                    spacing: 16
                    anchors.horizontalCenter: parent.horizontalCenter

                    Label {
                        width: 60
                        text: "USB In"
                        font.pixelSize: 13
                        font.bold: true
                        color: "#555555"
                        anchors.verticalCenter: parent.verticalCenter
                    }

                    Repeater {
                        model: 2

                        Rectangle {
                            width: 64; height: 48; radius: 8
                            color: muxActiveIn() === index ? "#1976D2" : "#e0e0e0"
                            border.color: muxActiveIn() === index ? "#1565C0" : "#bdbdbd"
                            border.width: 2

                            Label {
                                anchors.centerIn: parent
                                text: "IN " + (index + 1)
                                font.pixelSize: 14; font.bold: true
                                color: muxActiveIn() === index ? "#ffffff" : "#555555"
                            }

                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: selectMuxIn(index)
                            }

                            Behavior on color { ColorAnimation { duration: 150 } }
                        }
                    }
                }

                // Connection indicator
                Rectangle {
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: 2; height: 20
                    color: "#bdbdbd"
                }

                // USB Out row
                Row {
                    spacing: 12
                    anchors.horizontalCenter: parent.horizontalCenter

                    Label {
                        width: 60
                        text: "USB Out"
                        font.pixelSize: 13
                        font.bold: true
                        color: "#555555"
                        anchors.verticalCenter: parent.verticalCenter
                    }

                    Repeater {
                        model: 4

                        Rectangle {
                            width: 64; height: 48; radius: 8
                            color: muxActiveOut() === index ? "#FF9800" : "#e0e0e0"
                            border.color: muxActiveOut() === index ? "#F57C00" : "#bdbdbd"
                            border.width: 2

                            Label {
                                anchors.centerIn: parent
                                text: "OUT " + (index + 1)
                                font.pixelSize: 14; font.bold: true
                                color: muxActiveOut() === index ? "#ffffff" : "#555555"
                            }

                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: selectMuxOut(index)
                            }

                            Behavior on color { ColorAnimation { duration: 150 } }
                        }
                    }
                }

                // Current route label
                Label {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: {
                        var inP = muxActiveIn()
                        var outP = muxActiveOut()
                        if (inP >= 0 && outP >= 0)
                            return "Route: IN " + (inP + 1) + "  \u2192  OUT " + (outP + 1)
                        return "No active route"
                    }
                    font.pixelSize: 14
                    color: "#333333"
                }
            }

            // Refresh button
            Button {
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.rightMargin: 16
                anchors.bottomMargin: 14
                text: "Refresh"; font.pixelSize: 13; flat: true
                enabled: currentDevice !== ""
                onClicked: ServiceBridge.callService(
                    "ServiceCleware", "svc_api_get_all_devices_state", [])
            }
        }
    }

    // ===================================================================
    // Helper functions
    // ===================================================================

    function ledState(index) {
        // Reference stateRevision to trigger re-evaluation
        var rev = stateRevision
        if (!currentDevice || !devicesState[currentDevice]) return false
        var sw = devicesState[currentDevice]
        return sw[String(index)] === 1
    }

    function toggleSwitch(index) {
        if (!currentDevice) {
            resultLabel.color = "#c62828"
            resultLabel.text = "No device selected. Click Initialize first."
            return
        }
        var isOn = ledState(index)
        var swId = 0x10 + index
        ServiceBridge.callService("ServiceCleware", "svc_api_set_switch",
            [currentDevice, swId, isOn ? "off" : "on"])
    }

    // Multiplexer: find which switch index (0-7) is currently ON
    function muxActiveIndex() {
        var rev = stateRevision
        if (!currentDevice || !devicesState[currentDevice]) return -1
        var sw = devicesState[currentDevice]
        for (var i = 0; i < 8; i++) {
            if (sw[String(i)] === 1) return i
        }
        return -1
    }

    // Active IN port (0 or 1), derived from active switch index
    function muxActiveIn() {
        var idx = muxActiveIndex()
        return idx >= 0 ? Math.floor(idx / 4) : -1
    }

    // Active OUT port (0-3), derived from active switch index
    function muxActiveOut() {
        var idx = muxActiveIndex()
        return idx >= 0 ? (idx % 4) : -1
    }

    // Select a new IN port — keep current OUT, compute new switch index
    function selectMuxIn(inPort) {
        if (!currentDevice) return
        var outPort = muxActiveOut()
        if (outPort < 0) outPort = 0
        var swIndex = inPort * 4 + outPort
        ServiceBridge.callService("ServiceCleware", "svc_api_set_switch",
            [currentDevice, 0x10 + swIndex, "on"])
    }

    // Select a new OUT port — keep current IN, compute new switch index
    function selectMuxOut(outPort) {
        if (!currentDevice) return
        var inPort = muxActiveIn()
        if (inPort < 0) inPort = 0
        var swIndex = inPort * 4 + outPort
        ServiceBridge.callService("ServiceCleware", "svc_api_set_switch",
            [currentDevice, 0x10 + swIndex, "on"])
    }

    function bumpRevision() {
        stateRevision++
    }

    // ---- Handle responses ----
    Connections {
        target: ServiceBridge

        function onResponseReceived(method, data) {
            resultLabel.color = "#2e7d32"

            if (method === "svc_api_get_all_devices_state") {
                try {
                    var state = JSON.parse(data)
                    devicesState = state
                    var serials = Object.keys(state)
                    deviceCombo.model = serials

                    if (serials.length > 0) {
                        if (!currentDevice || serials.indexOf(currentDevice) < 0) {
                            currentDevice = serials[0]
                            deviceCombo.currentIndex = 0
                        }
                        resultLabel.text = "Found " + serials.length + " device(s): "
                            + serials.join(", ")
                        bumpRevision()
                    } else {
                        resultLabel.text = "No Cleware devices found."
                    }
                } catch (e) {
                    resultLabel.text = method + "  \u2192  " + data
                }
            } else if (method === "svc_api_set_switch") {
                resultLabel.text = "Switch set: " + data
                ServiceBridge.callService(
                    "ServiceCleware", "svc_api_get_all_devices_state", [])
            } else {
                resultLabel.text = method + "  \u2192  " + data
            }
        }

        function onErrorOccurred(method, error) {
            resultLabel.color = "#c62828"
            resultLabel.text = method + "  \u2192  Error: " + error
        }
    }
}
