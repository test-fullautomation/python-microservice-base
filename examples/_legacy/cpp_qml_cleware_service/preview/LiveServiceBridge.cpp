#include "LiveServiceBridge.h"

#include <QJsonDocument>
#include <QJsonObject>
#include <QDebug>
#include <chrono>

// ---- RpcWorker (runs on background thread) ----

void RpcWorker::configure(const std::string &host, int port,
                           const std::string &vhost,
                           const std::string &user,
                           const std::string &pass)
{
    m_host  = host;
    m_port  = port;
    m_vhost = vhost;
    m_user  = user;
    m_pass  = pass;
}

void RpcWorker::doRequest(const QString &serviceName,
                           const QString &method,
                           const QString &argsJson)
{
    // Each RPC call gets its own connection + exclusive reply queue,
    // matching the pattern in ServiceBase::requestService().
    RabbitMQConnection conn;

    if (!conn.Connect(m_host, m_port, m_vhost, m_user, m_pass)) {
        emit errorOccurred(method,
            QString("Cannot connect to RabbitMQ at %1:%2 — %3")
                .arg(QString::fromStdString(m_host))
                .arg(m_port)
                .arg(QString::fromStdString(conn.GetLastError())));
        return;
    }

    // Declare the services_request exchange (direct).
    conn.DeclareExchange("services_request", "direct");

    // Create an exclusive, auto-delete reply queue.
    std::string replyQueue = conn.DeclareQueue(
        /*name=*/"", /*durable=*/false, /*exclusive=*/true, /*auto_delete=*/true);

    if (replyQueue.empty()) {
        emit errorOccurred(method, "Failed to declare reply queue");
        return;
    }

    // Start consuming from the reply queue.
    if (!conn.StartConsume(replyQueue)) {
        emit errorOccurred(method, "Failed to start consuming reply queue");
        return;
    }

    // Build request: { "method": "svc_api_hello", "args": ["world"] }
    QJsonObject reqObj;
    reqObj["method"] = method;
    reqObj["args"]   = QJsonDocument::fromJson(argsJson.toUtf8()).array();

    std::string body = QJsonDocument(reqObj).toJson(QJsonDocument::Compact).toStdString();

    // Correlation ID (nanosecond timestamp, matching ServiceBase pattern).
    std::string corrId = std::to_string(
        std::chrono::steady_clock::now().time_since_epoch().count());

    // Publish to services_request exchange, routing_key = service name.
    if (!conn.Publish("services_request",
                      serviceName.toStdString(),
                      body,
                      /*delivery_mode=*/2,
                      corrId,
                      replyQueue))
    {
        emit errorOccurred(method,
            QString("Failed to publish request: %1")
                .arg(QString::fromStdString(conn.GetLastError())));
        return;
    }

    qDebug() << "[LiveBridge] Sent RPC:" << method
             << "to" << serviceName << "corrId=" << QString::fromStdString(corrId);

    // Wait for the response (up to 30 seconds).
    const int timeoutSec = 30;
    auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(timeoutSec);

    while (std::chrono::steady_clock::now() < deadline) {
        ConsumedMessage msg = conn.ConsumeOne(/*timeout_sec=*/1);

        if (!msg.received)
            continue;

        // Always ACK.
        conn.Ack(msg.delivery_tag);

        // Check correlation ID.
        if (msg.correlation_id != corrId) {
            qDebug() << "[LiveBridge] Ignoring message with wrong corrId";
            continue;
        }

        // Parse response: { "request": "...", "result": "pass|fail|exception",
        //                    "result_data": ... }
        QJsonObject resp = QJsonDocument::fromJson(
            QByteArray::fromStdString(msg.body)).object();

        QString result     = resp.value("result").toString("exception");
        QJsonValue resData = resp.value("result_data");

        QString resultStr;
        if (resData.isString())
            resultStr = resData.toString();
        else if (resData.isDouble())
            resultStr = QString::number(resData.toDouble());
        else
            resultStr = QJsonDocument(resData.toObject()).toJson(QJsonDocument::Compact);

        if (result == "pass") {
            emit responseReady(method, resultStr);
        } else {
            emit errorOccurred(method, resultStr);
        }

        conn.Disconnect();
        return;
    }

    emit errorOccurred(method, "Request timed out (30s)");
    conn.Disconnect();
}


// ---- LiveServiceBridge (lives on GUI thread) ----

LiveServiceBridge::LiveServiceBridge(QObject *parent)
    : QObject(parent)
{
    m_worker = new RpcWorker;
    m_worker->moveToThread(&m_workerThread);

    // Wire signals across threads.
    connect(this,     &LiveServiceBridge::requestNeeded,
            m_worker, &RpcWorker::doRequest);
    connect(m_worker, &RpcWorker::responseReady,
            this,     &LiveServiceBridge::responseReceived);
    connect(m_worker, &RpcWorker::errorOccurred,
            this,     &LiveServiceBridge::errorOccurred);

    // Clean up worker when thread finishes.
    connect(&m_workerThread, &QThread::finished,
            m_worker, &QObject::deleteLater);

    m_workerThread.start();
}

LiveServiceBridge::~LiveServiceBridge()
{
    m_workerThread.quit();
    m_workerThread.wait();
}

void LiveServiceBridge::configure(const std::string &host, int port,
                                   const std::string &vhost,
                                   const std::string &user,
                                   const std::string &pass)
{
    m_worker->configure(host, port, vhost, user, pass);
}

void LiveServiceBridge::setServiceName(const QString &name)
{
    if (m_serviceName != name) {
        m_serviceName = name;
        emit serviceNameChanged();
    }
}

void LiveServiceBridge::callService(const QString &serviceName,
                                     const QString &method,
                                     const QJsonArray &args)
{
    // Serialize args to JSON string for cross-thread transfer.
    QString argsJson = QJsonDocument(args).toJson(QJsonDocument::Compact);

    qDebug() << "[LiveBridge] callService:" << serviceName << method << argsJson;

    emit requestNeeded(serviceName, method, argsJson);
}
