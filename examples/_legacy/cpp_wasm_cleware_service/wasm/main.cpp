// main.cpp — WASM entry point for the Cleware switch box GUI.
//
// Creates a QApplication and shows the MainWidget.
// When compiled to WASM, the Qt runtime renders into the container
// element provided by the MicroserviceManager.

#include <QApplication>
#include "MainWidget.h"

int main(int argc, char *argv[])
{
    QApplication app(argc, argv);

    MainWidget widget;
    widget.show();

    return app.exec();
}
