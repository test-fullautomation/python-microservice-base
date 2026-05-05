import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import MicroserviceBase 1.0

Rectangle {
    id: root
    width: 600
    height: 800
    color: "#f5f5f5"

    // ---- Header ----
    Rectangle {
        id: header
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: 72
        color: "#1976D2"

        Label {
            anchors.left: parent.left
            anchors.leftMargin: 20
            anchors.top: parent.top
            anchors.topMargin: 14
            text: "MyQMLService"
            font.pixelSize: 22
            font.bold: true
            color: "#ffffff"
        }

        Label {
            anchors.left: parent.left
            anchors.leftMargin: 20
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 12
            text: "Example C++ service with QML UI"
            font.pixelSize: 13
            color: "#bbdefb"
        }
    }

    // ---- Say Hello card ----
    Rectangle {
        id: helloCard
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: header.bottom
        anchors.leftMargin: 16
        anchors.rightMargin: 16
        anchors.topMargin: 16
        height: 100
        radius: 8
        color: "#ffffff"
        border.color: "#e0e0e0"
        border.width: 1

        Label {
            id: helloTitle
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.leftMargin: 16
            anchors.topMargin: 14
            text: "Say Hello"
            font.pixelSize: 15
            font.bold: true
            color: "#333333"
        }

        TextField {
            id: nameInput
            anchors.left: parent.left
            anchors.right: helloBtn.left
            anchors.bottom: parent.bottom
            anchors.leftMargin: 16
            anchors.rightMargin: 10
            anchors.bottomMargin: 14
            placeholderText: "Enter your name"
            font.pixelSize: 14
        }

        Button {
            id: helloBtn
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.rightMargin: 16
            anchors.bottomMargin: 14
            text: "Say Hello"
            font.pixelSize: 14
            highlighted: true
            onClicked: ServiceBridge.callService(
                "MyQMLService", "svc_api_hello", [nameInput.text])
        }
    }

    // ---- Echo card ----
    Rectangle {
        id: echoCard
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: helloCard.bottom
        anchors.leftMargin: 16
        anchors.rightMargin: 16
        anchors.topMargin: 14
        height: 100
        radius: 8
        color: "#ffffff"
        border.color: "#e0e0e0"
        border.width: 1

        Label {
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.leftMargin: 16
            anchors.topMargin: 14
            text: "Echo"
            font.pixelSize: 15
            font.bold: true
            color: "#333333"
        }

        TextField {
            id: echoInput
            anchors.left: parent.left
            anchors.right: echoBtn.left
            anchors.bottom: parent.bottom
            anchors.leftMargin: 16
            anchors.rightMargin: 10
            anchors.bottomMargin: 14
            placeholderText: "Enter a message"
            font.pixelSize: 14
        }

        Button {
            id: echoBtn
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.rightMargin: 16
            anchors.bottomMargin: 14
            text: "Echo"
            font.pixelSize: 14
            highlighted: true
            onClicked: ServiceBridge.callService(
                "MyQMLService", "svc_api_echo", [echoInput.text])
        }
    }

    // ---- Compute Sum card ----
    Rectangle {
        id: computeCard
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: echoCard.bottom
        anchors.leftMargin: 16
        anchors.rightMargin: 16
        anchors.topMargin: 14
        height: 130
        radius: 8
        color: "#ffffff"
        border.color: "#e0e0e0"
        border.width: 1

        Label {
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.leftMargin: 16
            anchors.topMargin: 14
            text: "Compute Sum"
            font.pixelSize: 15
            font.bold: true
            color: "#333333"
        }

        Label {
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.leftMargin: 16
            anchors.topMargin: 38
            text: "Enter comma-separated numbers:"
            font.pixelSize: 12
            color: "#666666"
        }

        TextField {
            id: numbersInput
            anchors.left: parent.left
            anchors.right: sumBtn.left
            anchors.bottom: parent.bottom
            anchors.leftMargin: 16
            anchors.rightMargin: 10
            anchors.bottomMargin: 14
            placeholderText: "1, 2, 3, 4, 5"
            font.pixelSize: 14
        }

        Button {
            id: sumBtn
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.rightMargin: 16
            anchors.bottomMargin: 14
            text: "Sum"
            font.pixelSize: 14
            highlighted: true
            onClicked: {
                var parts = numbersInput.text.split(",");
                var nums = [];
                for (var i = 0; i < parts.length; i++) {
                    var n = parseFloat(parts[i].trim());
                    if (!isNaN(n)) nums.push(n);
                }
                ServiceBridge.callService(
                    "MyQMLService", "svc_api_compute", [nums]);
            }
        }
    }

    // ---- Result card ----
    Rectangle {
        id: resultCard
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: computeCard.bottom
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
            text: "Result"
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
                text: "Click a button above to call the service..."
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
            "MyQMLService", "svc_api_get_version", [])
    }

    // ---- Handle responses ----
    Connections {
        target: ServiceBridge

        function onResponseReceived(method, data) {
            resultLabel.color = "#2e7d32"
            resultLabel.text = method + "  →  " + data
        }

        function onErrorOccurred(method, error) {
            resultLabel.color = "#c62828"
            resultLabel.text = method + "  →  Error: " + error
        }
    }
}
