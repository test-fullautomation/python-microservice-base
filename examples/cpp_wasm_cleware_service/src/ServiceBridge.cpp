/**
 * @file ServiceBridge.cpp
 * @brief Implementation of the ServiceBridge — calls microservices via Emscripten JS interop.
 *
 * Approach: JS stores results in window._qtBridgeResults[], and a QTimer polls
 * for completed results. This avoids complex JS→C++ async callbacks which can
 * fail silently in single-threaded WASM mode.
 */

#include "ServiceBridge.h"

#ifdef __EMSCRIPTEN__
#include <emscripten.h>
#include <QTimer>
#include <QJsonDocument>
#include <QJsonObject>

// ---------------------------------------------------------------------------
// EM_JS: Fire-and-forget — calls window.callMicroservice and stores result
// in window._qtBridgeResults for later polling by the C++ QTimer.
// ---------------------------------------------------------------------------
EM_JS(void, js_call_service, (const char *serviceName, const char *method,
                               const char *argsJson), {

    // Ensure results array exists
    if (!window._qtBridgeResults) window._qtBridgeResults = [];

    var svc     = UTF8ToString(serviceName);
    var meth    = UTF8ToString(method);
    var argsStr = UTF8ToString(argsJson);

    /* ---- Resolve the callMicroservice function ---- */
    var callFn = window.callMicroservice
              || (window.MicroserviceManager && window.MicroserviceManager.requestService
                  ? function(s, m, a) { return window.MicroserviceManager.requestService(s, m, a); }
                  : null);

    if (!callFn) {
        window._qtBridgeResults.push({
            method: meth,
            error: 'callMicroservice() not available. Use serve.bat to start the dev server.'
        });
        return;
    }

    /* ---- Parse args and call ---- */
    var args;
    try { args = JSON.parse(argsStr); } catch(e) { args = []; }

    try {
        var result = callFn(svc, meth, args);

        if (result && typeof result.then === 'function') {
            result.then(function(data) {
                /* Check service response status: "pass" = success, else error */
                if (typeof data === 'object' && data !== null && data.result && data.result !== 'pass') {
                    var errMsg = (data.result_data !== undefined) ? String(data.result_data) : data.result;
                    window._qtBridgeResults.push({ method: meth, error: errMsg });
                    return;
                }
                var s;
                if (typeof data === 'object' && data !== null) {
                    s = (data.result_data !== undefined)
                        ? (typeof data.result_data === 'string'
                            ? data.result_data
                            : JSON.stringify(data.result_data))
                        : JSON.stringify(data);
                } else {
                    s = String(data);
                }
                window._qtBridgeResults.push({ method: meth, data: s });
            }).catch(function(err) {
                window._qtBridgeResults.push({ method: meth, error: String(err) });
            });
        } else {
            var s = (typeof result === 'object' && result !== null)
                ? JSON.stringify(result) : String(result);
            window._qtBridgeResults.push({ method: meth, data: s });
        }
    } catch (ex) {
        window._qtBridgeResults.push({ method: meth, error: 'JS: ' + String(ex) });
    }
});

// ---------------------------------------------------------------------------
// EM_JS: Check if any results are queued and return the count.
// ---------------------------------------------------------------------------
EM_JS(int, js_bridge_result_count, (), {
    return (window._qtBridgeResults && window._qtBridgeResults.length) ? window._qtBridgeResults.length : 0;
});

// ---------------------------------------------------------------------------
// EM_JS: Pop one result from the queue. Returns JSON string (caller must free).
// ---------------------------------------------------------------------------
EM_JS(char*, js_bridge_pop_result, (), {
    if (!window._qtBridgeResults || window._qtBridgeResults.length === 0)
        return 0;
    var item = window._qtBridgeResults.shift();
    var json = JSON.stringify(item);
    var len = lengthBytesUTF8(json) + 1;
    var ptr = _malloc(len);
    stringToUTF8(json, ptr, len);
    return ptr;
});

#endif // __EMSCRIPTEN__


ServiceBridge::ServiceBridge(QObject *parent)
    : QObject(parent)
{
#ifdef __EMSCRIPTEN__
    // Poll for JS results every 100ms
    auto *timer = new QTimer(this);
    connect(timer, &QTimer::timeout, this, &ServiceBridge::pollResults);
    timer->start(100);
#endif
}

void ServiceBridge::callService(const QString &serviceName,
                                 const QString &method,
                                 const QJsonArray &args)
{
#ifdef __EMSCRIPTEN__
    QJsonDocument doc(args);
    std::string argsJson = doc.toJson(QJsonDocument::Compact).toStdString();

    js_call_service(serviceName.toUtf8().constData(),
                    method.toUtf8().constData(),
                    argsJson.c_str());
#else
    emit errorOccurred(method, "ServiceBridge only works in WASM builds");
#endif
}

void ServiceBridge::pollResults()
{
#ifdef __EMSCRIPTEN__
    while (js_bridge_result_count() > 0) {
        char *jsonPtr = js_bridge_pop_result();
        if (!jsonPtr)
            break;

        QString jsonStr = QString::fromUtf8(jsonPtr);
        free(jsonPtr);

        QJsonDocument doc = QJsonDocument::fromJson(jsonStr.toUtf8());
        if (!doc.isObject())
            continue;

        QJsonObject obj = doc.object();
        QString method = obj.value("method").toString();

        if (obj.contains("error")) {
            emit errorOccurred(method, obj.value("error").toString());
        } else {
            emit responseReceived(method, obj.value("data").toString());
        }
    }
#endif
}
