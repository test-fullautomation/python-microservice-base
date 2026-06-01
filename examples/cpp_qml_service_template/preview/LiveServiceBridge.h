#pragma once
// LiveServiceBridge — connects the QML preview directly to a backend
// service via RabbitMQ (no MicroserviceManager needed).
//
// Usage:  MyQMLServicePreview.exe --live [--broker host:port]
//
// Prerequisites:
//   1. RabbitMQ running
//   2. MyQMLService.exe (backend) running and registered
//
// Reads broker settings from service_config.json next to the exe.

#include <QObject>
#include <QJsonArray>
#include <QThread>

#include "RabbitMQConnection.h"

// Worker that runs RabbitMQ RPC on a background thread so the GUI stays
// responsive while waiting for the service response.
class RpcWorker : public QObject
{
    Q_OBJECT

public:
    void configure(const std::string &host, int port,
                   const std::string &vhost,
                   const std::string &user,
                   const std::string &pass);

public slots:
    void doRequest(const QString &serviceName,
                   const QString &method,
                   const QString &argsJson);

signals:
    void responseReady(const QString &method, const QString &result);
    void errorOccurred(const QString &method, const QString &error);

private:
    std::string m_host  = "localhost";
    int         m_port  = 5672;
    std::string m_vhost = "/";
    std::string m_user  = "guest";
    std::string m_pass  = "guest";
};


class LiveServiceBridge : public QObject
{
    Q_OBJECT
    Q_PROPERTY(QString serviceName READ serviceName WRITE setServiceName
               NOTIFY serviceNameChanged)

public:
    explicit LiveServiceBridge(QObject *parent = nullptr);
    ~LiveServiceBridge() override;

    void configure(const std::string &host, int port,
                   const std::string &vhost = "/",
                   const std::string &user  = "guest",
                   const std::string &pass  = "guest");

    QString serviceName() const { return m_serviceName; }
    void setServiceName(const QString &name);

    // Called from QML:
    //   ServiceBridge.callService("MyQMLService", "svc_api_hello", ["world"])
    Q_INVOKABLE void callService(const QString &serviceName,
                                 const QString &method,
                                 const QJsonArray &args);

signals:
    void serviceNameChanged();
    void responseReceived(const QString &method, const QString &result);
    void errorOccurred(const QString &method, const QString &error);

    // Internal — triggers the worker thread
    void requestNeeded(const QString &serviceName,
                       const QString &method,
                       const QString &argsJson);

private:
    QString    m_serviceName;
    QThread    m_workerThread;
    RpcWorker *m_worker = nullptr;
};
