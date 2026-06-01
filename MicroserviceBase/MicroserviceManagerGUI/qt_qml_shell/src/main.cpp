/**
 * @file main.cpp
 * @brief QML Shell entry point — shared WASM binary that loads service .qml files at runtime.
 *
 * Sets up:
 * - QQmlApplicationEngine with ServiceBridge singleton
 * - ShellController for dynamic QML loading
 * - EMSCRIPTEN_KEEPALIVE exported C functions for JS↔C++ interop
 */

#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQuickItem>
#include <QQuickWindow>

#include "ServiceBridge.h"
#include "ShellController.h"

#ifdef __EMSCRIPTEN__
#include <emscripten.h>
#include <emscripten/val.h>
#include <cstdlib>
#include <cstring>
#endif

// Global pointers for C function exports.
static ShellController *g_shellController = nullptr;
static ServiceBridge   *g_serviceBridge   = nullptr;

// ---------------------------------------------------------------------------
// Exported C functions (called from QtShellManager.js via ccall/cwrap)
// ---------------------------------------------------------------------------

#ifdef __EMSCRIPTEN__
extern "C" {

/**
 * Heap allocation wrappers exported via EMSCRIPTEN_KEEPALIVE.
 * Qt's qt_add_executable strips Emscripten's _malloc/_free exports,
 * so we re-export them under our own names.
 */
EMSCRIPTEN_KEEPALIVE
void *qtshell_malloc(int size) { return malloc(size); }

EMSCRIPTEN_KEEPALIVE
void qtshell_free(void *ptr) { free(ptr); }


/**
 * Load a QML file from a URL.
 * @param urlStr  The URL string (e.g., "services/MyService1.0.0/ServiceUI.qml").
 */
EMSCRIPTEN_KEEPALIVE
void qtshell_loadQml(const char *urlStr)
{
    if (!g_shellController) return;

    QString url = QString::fromUtf8(urlStr);
    // If it's a relative path, resolve against the page origin.
    QUrl qmlUrl(url);
    if (qmlUrl.isRelative()) {
        // Build absolute URL from the current page origin.
        emscripten::val location = emscripten::val::global("window")["location"];
        std::string origin = location["origin"].as<std::string>();
        std::string pathname = location["pathname"].as<std::string>();
        // Strip filename from pathname to get directory.
        auto lastSlash = pathname.rfind('/');
        if (lastSlash != std::string::npos) {
            pathname = pathname.substr(0, lastSlash + 1);
        }
        qmlUrl = QUrl(QString::fromStdString(origin + pathname) + url);
    }

    QMetaObject::invokeMethod(g_shellController, "loadQml",
                              Qt::QueuedConnection,
                              Q_ARG(QUrl, qmlUrl));
}

/**
 * Load QML from source string (for file:// environments like Electron).
 *
 * @param sourceStr  The QML source code.
 * @param baseUrlStr Base URL for relative imports (e.g., "services/MyService1.0.0/").
 */
EMSCRIPTEN_KEEPALIVE
void qtshell_loadQmlSource(const char *sourceStr, const char *baseUrlStr)
{
    if (!g_shellController) return;

    // Deep-copy the source (JS frees the buffer after this call returns,
    // so fromRawData + QueuedConnection would be use-after-free).
    QByteArray source(sourceStr);

    // Use a simple URL for the base (not fromLocalFile which creates
    // file:// paths that are meaningless in WASM).
    QUrl baseUrl(QString::fromUtf8(baseUrlStr));

    g_shellController->loadQmlSource(source, baseUrl);
}

/**
 * Clear the currently loaded QML.
 */
EMSCRIPTEN_KEEPALIVE
void qtshell_clearQml()
{
    if (!g_shellController) {
        return;
    }
    QMetaObject::invokeMethod(g_shellController, "clearQml",
                              Qt::QueuedConnection);
}

/**
 * Set the active service name on the ServiceBridge.
 * @param nameStr  The service name.
 */
EMSCRIPTEN_KEEPALIVE
void qtshell_setServiceName(const char *nameStr)
{
    if (!g_serviceBridge) return;
    g_serviceBridge->setServiceName(QString::fromUtf8(nameStr));
}

/**
 * Callback from JS promise resolution (called from ServiceBridge.cpp EM_ASM).
 */
EMSCRIPTEN_KEEPALIVE
void qtshell_onResponse(const char *method, const char *result)
{
    if (!g_serviceBridge) return;
    g_serviceBridge->handleResponse(QString::fromUtf8(method),
                                    QString::fromUtf8(result));
}

/**
 * Callback from JS promise rejection (called from ServiceBridge.cpp EM_ASM).
 */
EMSCRIPTEN_KEEPALIVE
void qtshell_onError(const char *method, const char *error)
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
    QGuiApplication app(argc, argv);

    QQmlApplicationEngine engine;

    // Create the ServiceBridge singleton and expose to QML.
    g_serviceBridge = new ServiceBridge(&app);
    engine.rootContext()->setContextProperty("ServiceBridge", g_serviceBridge);

    // Load the shell's main.qml (preloads QML modules for the static linker).
    engine.load(QUrl(QStringLiteral("qrc:/MicroserviceBase/src/main.qml")));

    if (engine.rootObjects().isEmpty()) {
        qWarning() << "Failed to load main.qml";
        return -1;
    }

    // Find the root container item for dynamic QML loading.
    QQuickWindow *window = qobject_cast<QQuickWindow *>(engine.rootObjects().first());
    QQuickItem *rootItem = window ? window->contentItem() : nullptr;
    QQuickItem *container = rootItem
        ? rootItem->findChild<QQuickItem *>("shellContainer")
        : nullptr;

    if (!container && rootItem) {
        // Fallback: use the root content item itself.
        container = rootItem;
    }

    // Create ShellController with the container.
    g_shellController = new ShellController(&engine, container, &app);

    return app.exec();
}
