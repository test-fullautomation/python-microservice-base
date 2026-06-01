/**
 * @file main.cpp
 * @brief Widget Shell entry point — shared WASM binary that loads service .ui files at runtime.
 *
 * Sets up:
 * - QApplication (Widgets require QApplication, not QGuiApplication)
 * - ServiceBridge for microservice calls via JS
 * - WidgetController for dynamic .ui loading and auto-wiring
 * - EMSCRIPTEN_KEEPALIVE exported C functions for JS↔C++ interop
 *
 * Key difference from QML Shell:
 * - No QML engine, no main.qml
 * - Uses QUiLoader to load .ui files (Qt Designer forms)
 * - Buttons are auto-wired to service calls via dynamic properties
 */

#include <QApplication>
#include <QWidget>
#include <QVBoxLayout>

#include "ServiceBridge.h"
#include "WidgetController.h"

#ifdef __EMSCRIPTEN__
#include <emscripten.h>
#include <emscripten/val.h>
#include <cstdlib>
#include <cstring>
#endif

// Global pointers for C function exports.
static WidgetController *g_widgetController = nullptr;
static ServiceBridge    *g_serviceBridge    = nullptr;

// ---------------------------------------------------------------------------
// Exported C functions (called from WidgetShellManager.js via direct calls)
// ---------------------------------------------------------------------------

#ifdef __EMSCRIPTEN__
extern "C" {

/**
 * Heap allocation wrappers exported via EMSCRIPTEN_KEEPALIVE.
 * Qt's qt_add_executable strips Emscripten's _malloc/_free exports,
 * so we re-export them under our own names.
 */
EMSCRIPTEN_KEEPALIVE
void *widgetshell_malloc(int size) { return malloc(size); }

EMSCRIPTEN_KEEPALIVE
void widgetshell_free(void *ptr) { free(ptr); }

/**
 * Load a .ui form from XML source string.
 *
 * @param sourceStr  The .ui XML source (from Qt Designer).
 */
EMSCRIPTEN_KEEPALIVE
void widgetshell_loadUiSource(const char *sourceStr)
{
    if (!g_widgetController) return;

    // Deep-copy the source (JS frees the buffer after this call returns).
    QByteArray source(sourceStr);

    g_widgetController->loadUiSource(source);
}

/**
 * Clear the currently loaded .ui widget.
 */
EMSCRIPTEN_KEEPALIVE
void widgetshell_clearUi()
{
    if (!g_widgetController) return;
    QMetaObject::invokeMethod(g_widgetController, "clearUi",
                              Qt::QueuedConnection);
}

/**
 * Set the active service name on the ServiceBridge.
 * @param nameStr  The service name.
 */
EMSCRIPTEN_KEEPALIVE
void widgetshell_setServiceName(const char *nameStr)
{
    if (!g_serviceBridge) return;
    g_serviceBridge->setServiceName(QString::fromUtf8(nameStr));
}

/**
 * Callback from JS promise resolution.
 */
EMSCRIPTEN_KEEPALIVE
void widgetshell_onResponse(const char *method, const char *result)
{
    if (!g_serviceBridge) return;
    g_serviceBridge->handleResponse(QString::fromUtf8(method),
                                    QString::fromUtf8(result));
}

/**
 * Callback from JS promise rejection.
 */
EMSCRIPTEN_KEEPALIVE
void widgetshell_onError(const char *method, const char *error)
{
    if (!g_serviceBridge) return;
    g_serviceBridge->handleError(QString::fromUtf8(method),
                                 QString::fromUtf8(error));
}

} // extern "C"
#endif // __EMSCRIPTEN__

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

int main(int argc, char *argv[])
{
    // QApplication (not QGuiApplication) — required for Widgets.
    QApplication app(argc, argv);

    // Root container widget — Qt creates its canvas inside this.
    QWidget root;
    root.setObjectName("widgetShellRoot");
    root.show();

    // Create the ServiceBridge.
    g_serviceBridge = new ServiceBridge(&app);

    // Create WidgetController with the root container.
    g_widgetController = new WidgetController(&root, g_serviceBridge, &app);

    return app.exec();
}
