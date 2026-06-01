/**
 * @file ServiceBridge.h
 * @brief QML singleton for calling microservices via the JS bridge.
 *
 * Registered as "MicroserviceBase.ServiceBridge" in the QML engine.
 * QML service UIs call ServiceBridge.callService() to invoke backend methods.
 * Results are delivered via responseReceived / errorOccurred signals.
 *
 * Enhanced from qt_wasm_service_template/src/ServiceBridge.h with:
 * - serviceName property (set by ShellController when switching services)
 * - Proper async promise handling via EM_ASM
 */

#pragma once

#include <QObject>
#include <QString>
#include <QJsonArray>

class ServiceBridge : public QObject
{
    Q_OBJECT

    Q_PROPERTY(QString serviceName READ serviceName WRITE setServiceName
               NOTIFY serviceNameChanged)

public:
    explicit ServiceBridge(QObject *parent = nullptr);

    static ServiceBridge *instance();

    QString serviceName() const;
    void setServiceName(const QString &name);

    /**
     * Call a microservice method via the JS bridge.
     *
     * @param serviceName  The service name (overrides the property if non-empty).
     * @param method       The method to invoke (e.g., "svc_api_hello").
     * @param args         JSON array of arguments.
     */
    Q_INVOKABLE void callService(const QString &serviceName,
                                  const QString &method,
                                  const QJsonArray &args);

    // Called from JS when a promise resolves/rejects.
    void handleResponse(const QString &method, const QString &result);
    void handleError(const QString &method, const QString &error);

signals:
    void serviceNameChanged();
    void responseReceived(const QString &method, const QString &result);
    void errorOccurred(const QString &method, const QString &error);

private:
    static ServiceBridge *s_instance;
    QString m_serviceName;
};
