#pragma once

#include <QHash>
#include <QStringList>
#include <QUrl>
#include <QWidget>

#include <functional>
#include <memory>

#include <QtGrpc/QGrpcCallReply>
#include <QtGrpc/QGrpcStatus>
#include <QtProtobuf/QProtobufJsonSerializer>

QT_BEGIN_NAMESPACE
namespace Ui { class MainWindow; }
class QNetworkAccessManager;
QT_END_NAMESPACE

class QGrpcHttp2Channel;

class MainWindow : public QWidget {
    Q_OBJECT
public:
    using DoneFn   = std::function<void(bool ok, const QString& body)>;
    using InvokeFn = std::function<void(const QByteArray& jsonReq, DoneFn done)>;

    explicit MainWindow(QWidget* parent = nullptr);
    ~MainWindow() override;

private slots:
    void onConnectClicked();
    void onSendClicked();
    void onServiceChanged(int);
    void onUseConsulToggled(bool checked);

private:
    /// Build the gRPC channel for `url` and re-attach every typed Client.
    void applyChannelUrl(const QUrl& url);
    /// Resolve the service name via Consul HTTP API → host:port → applyChannelUrl.
    void resolveViaConsul();
    void setupDispatch();

    /// JSON in -> typed Request -> typed RPC -> typed Response -> JSON out.
    /// Called from each (service, method) lambda in setupDispatch().  All
    /// JSON / status / error boilerplate lives here, so adding an RPC is
    /// one new line.
    template <class Req, class Resp, class CallFn>
    void invokeRpc(const QByteArray& jsonReq, DoneFn done, CallFn&& callRpc) {
        QProtobufJsonSerializer json;
        Req req;
        const QByteArray body = jsonReq.trimmed().isEmpty()
                                ? QByteArray("{}") : jsonReq;
        if (!req.deserialize(&json, body)) {
            done(false, QStringLiteral("Failed to parse request JSON"));
            return;
        }
        // Qt 6.8+: client RPCs return std::unique_ptr<QGrpcCallReply>.
        // Capture the raw pointer for connect() and *move* the unique_ptr
        // into the slot lambda so the reply lives until the signal fires.
        auto reply = callRpc(req);
        auto* raw  = reply.get();
        connect(raw, &QGrpcCallReply::finished, this,
            [r = std::move(reply), done](const QGrpcStatus& st) {
                if (!st.isOk()) {
                    done(false, QStringLiteral("RPC failed: ") + st.message());
                    return;
                }
                // Qt 6.8+: read<T>() returns std::optional<T>.  `template`
                // disambiguator required because Resp is a dependent type.
                auto resp = r->template read<Resp>();
                if (!resp) {
                    done(false, QStringLiteral("Failed to read response"));
                    return;
                }
                QProtobufJsonSerializer s;
                done(true, QString::fromUtf8(resp->serialize(&s)));
            });
    }

    Ui::MainWindow* ui;
    QNetworkAccessManager* m_net = nullptr;
    std::shared_ptr<QGrpcHttp2Channel> m_channel;

    /// "Service.Method" -> typed dispatcher.
    QHash<QString, InvokeFn> m_dispatch;
    /// "Service" -> ordered method names.
    QHash<QString, QStringList> m_methodsByService;
    QStringList m_serviceList;
};
