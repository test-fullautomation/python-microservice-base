// Hello panel in QML: a "qml" tile of component.json, run by the GUI's
// QML shell. ServiceBridge.callService("", method, args) calls the bound
// gRPC service (binds.grpc): an empty service name keeps the call with
// this tile. args are the request fields in order, or one object.
import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import MicroserviceBase 1.0

Rectangle {
    id: root
    color: "#f7f8f7"

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 10

        Label {
            text: "Hello, from QML"
            font.pixelSize: 17
            font.bold: true
            color: "#1d2a22"
        }

        RowLayout {
            spacing: 8
            TextField {
                id: nameInput
                Layout.fillWidth: true
                placeholderText: "Name"
                text: "bench"
                onAccepted: greetButton.clicked()
            }
            Button {
                id: greetButton
                text: "Greet"
                highlighted: true
                // Positional: "name" is the first field of GreetRequest.
                onClicked: ServiceBridge.callService("", "Greet", [nameInput.text])
            }
        }

        RowLayout {
            spacing: 8
            TextField {
                id: echoInput
                Layout.fillWidth: true
                placeholderText: "Payload to echo"
                onAccepted: echoButton.clicked()
            }
            Button {
                id: echoButton
                text: "Echo"
                // One object: the request message itself.
                onClicked: ServiceBridge.callService("", "Echo", [{ "payload": echoInput.text }])
            }
        }

        Label {
            id: resultLabel
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            text: "Click a button to call the service."
            color: "#5a665f"
            font.pixelSize: 14
        }

        Item { Layout.fillHeight: true }
    }

    Connections {
        target: ServiceBridge

        function onResponseReceived(method, data) {
            resultLabel.color = "#1e8449"
            resultLabel.text = method + " → " + data
        }

        function onErrorOccurred(method, error) {
            resultLabel.color = "#b83227"
            resultLabel.text = method + " → " + error
        }
    }
}
