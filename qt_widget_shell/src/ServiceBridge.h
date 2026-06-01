/**
 * @file ServiceBridge.h
 * @brief Service bridge for calling microservices via the JS bridge (Widget Shell).
 *
 * Adapted from the QML Shell's ServiceBridge — removes Q_INVOKABLE and QML macros
 * since Widget Shell uses QWidget (no QML engine). The bridge is called
 * programmatically from WidgetController's auto-wired button handlers.
 *
 * Results are delivered via responseReceived / errorOccurred signals.
 */

#pragma once

#include <QObject>
#include <QString>
#include <QJsonArray>

class ServiceBridge : public QObject
{
    Q_OBJECT

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
    void callService(const QString &serviceName,
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
