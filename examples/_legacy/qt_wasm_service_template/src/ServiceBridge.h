/**
 * @file ServiceBridge.h
 * @brief C++ wrapper around the JS bridge (window.callMicroservice).
 *
 * Provides a Qt-friendly API with signals for calling microservice methods
 * from within a Qt WASM application.
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

    /**
     * Call a microservice method via the JS bridge.
     *
     * @param serviceName  The service name registered with the broker.
     * @param method       The method to invoke (e.g., "svc_api_hello").
     * @param args         JSON array of arguments.
     */
    Q_INVOKABLE void callService(const QString &serviceName,
                                  const QString &method,
                                  const QJsonArray &args);

signals:
    void responseReceived(const QString &method, const QString &result);
    void errorOccurred(const QString &method, const QString &error);

private slots:
    void pollResults();
};
