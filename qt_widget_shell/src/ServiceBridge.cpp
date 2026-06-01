/**
 * @file ServiceBridge.cpp
 * @brief Implementation of the ServiceBridge for the Widget Shell.
 *
 * In WASM builds, calls window.callMicroservice() via EM_ASM and routes
 * the promise result/error back to Qt signals. Identical logic to the
 * QML Shell version but without QML-specific macros.
 */

#include "ServiceBridge.h"

#ifdef __EMSCRIPTEN__
#include <emscripten.h>
#include <emscripten/val.h>
#include <QJsonDocument>
#endif

ServiceBridge *ServiceBridge::s_instance = nullptr;

ServiceBridge::ServiceBridge(QObject *parent)
    : QObject(parent)
{
    s_instance = this;
}

ServiceBridge *ServiceBridge::instance()
{
    return s_instance;
}

QString ServiceBridge::serviceName() const
{
    return m_serviceName;
}

void ServiceBridge::setServiceName(const QString &name)
{
    if (m_serviceName != name) {
        m_serviceName = name;
        emit serviceNameChanged();
    }
}

void ServiceBridge::callService(const QString &serviceName,
                                 const QString &method,
                                 const QJsonArray &args)
{
#ifdef __EMSCRIPTEN__
    using emscripten::val;

    val window = val::global("window");
    if (!window.hasOwnProperty("callMicroservice")) {
        emit errorOccurred(method, "JS bridge (callMicroservice) not available");
        return;
    }

    // Convert QJsonArray to JS array via JSON round-trip
    QJsonDocument doc(args);
    std::string argsJson = doc.toJson(QJsonDocument::Compact).toStdString();

    val JSON = val::global("JSON");
    val jsArgs = JSON.call<val>("parse", argsJson);

    std::string svcName = serviceName.isEmpty()
        ? m_serviceName.toStdString()
        : serviceName.toStdString();
    std::string methodStr = method.toStdString();

    // Fire the request via JS bridge. Response handling is done entirely
    // in WidgetShellManager.js which calls _widgetshell_onResponse/_widgetshell_onError
    // back into C++ using the working _allocUTF8 helpers.
    EM_ASM({
        var svcName = UTF8ToString($0);
        var method  = UTF8ToString($1);
        var argsStr = UTF8ToString($2);
        var args    = JSON.parse(argsStr);

        window.callMicroservice(svcName, method, args);
    }, svcName.c_str(), methodStr.c_str(), argsJson.c_str());

#else
    // Desktop fallback — not connected to any service
    Q_UNUSED(serviceName)
    Q_UNUSED(args)
    emit errorOccurred(method, "ServiceBridge only works in WASM builds");
#endif
}

void ServiceBridge::handleResponse(const QString &method, const QString &result)
{
    emit responseReceived(method, result);
}

void ServiceBridge::handleError(const QString &method, const QString &error)
{
    emit errorOccurred(method, error);
}
