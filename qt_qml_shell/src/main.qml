/**
 * main.qml — Shell root window.
 *
 * This file serves two purposes:
 * 1. Preloads all commonly used QML modules so the static linker keeps them
 *    in the WASM binary (service QML files import these at runtime).
 * 2. Provides the root container item where dynamic QML is parented.
 */
import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

// The Window is transparent — the browser page provides the visible frame.
ApplicationWindow {
    id: shellWindow
    visible: true
    color: "transparent"

    // The container where dynamically loaded QML items are parented.
    Item {
        id: shellContainer
        objectName: "shellContainer"
        anchors.fill: parent

        // Placeholder shown when no service QML is loaded.
        Label {
            id: placeholder
            anchors.centerIn: parent
            text: "QML Shell Ready"
            font.pixelSize: 16
            color: "#888"
            visible: shellContainer.children.length <= 1
        }
    }
}
