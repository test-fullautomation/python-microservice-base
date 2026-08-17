#include "MainWindow.h"
#include "ui_MainWindow.h"

#include <QtConcurrent/QtConcurrentRun>
#include <QFutureWatcher>
#include <QCheckBox>
#include <QComboBox>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLineEdit>
#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QStringList>
#include <QTextEdit>
#include <QUrl>

#include <grpcpp/grpcpp.h>
#include <google/protobuf/util/json_util.h>

#include <chrono>
#include <utility>

namespace {

QString messageToJson(const google::protobuf::Message& msg) {
    std::string out;
    google::protobuf::util::JsonPrintOptions opts;
    opts.add_whitespace = true;
    opts.preserve_proto_field_names = true;
    auto status = google::protobuf::util::MessageToJsonString(msg, &out, opts);
    if (!status.ok())
        return QStringLiteral("{ \"error\": \"%1\" }").arg(QString::fromStdString(std::string(status.message())));
    return QString::fromStdString(out);
}

bool jsonToMessage(const QByteArray& json, google::protobuf::Message* msg, QString* err) {
    auto status = google::protobuf::util::JsonStringToMessage(
        std::string(json.constData(), json.size()), msg);
    if (!status.ok()) {
        if (err) *err = QString::fromStdString(std::string(status.message()));
        return false;
    }
    return true;
}

// invokeRpc: parse JSON -> typed Req, run sync RPC on worker, marshal
// typed Resp back to JSON.  CallFn signature:
//     grpc::Status (*)(grpc::ClientContext*, const Req&, Resp*)
template <class Req, class Resp, class CallFn>
void invokeRpcImpl(QObject* parent,
                   const QByteArray& body,
                   std::function<void(bool, const QString&)> done,
                   CallFn call) {
    Req req;
    QString perr;
    if (!body.trimmed().isEmpty() && !jsonToMessage(body, &req, &perr)) {
        done(false, QStringLiteral("JSON parse error: %1").arg(perr));
        return;
    }
    auto* watcher = new QFutureWatcher<QString>(parent);
    QObject::connect(watcher, &QFutureWatcher<QString>::finished, parent,
        [watcher, done]() {
            done(true, watcher->result());
            watcher->deleteLater();
        });
    watcher->setFuture(QtConcurrent::run([req, call]() -> QString {
        Resp resp;
        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(10));
        auto status = call(&ctx, req, &resp);
        if (!status.ok())
            return QStringLiteral("RPC failed [%1] %2")
                .arg(status.error_code())
                .arg(QString::fromStdString(status.error_message()));
        return messageToJson(resp);
    }));
}

}  // namespace

// Member helper redirects to the namespace-scoped template (template
// methods can't be defined out-of-class without the class declaration
// being a template, so we forward via a lambda capture).
template <class Req, class Resp, class CallFn>
static void invokeRpc(QObject* parent, const QByteArray& body,
                      std::function<void(bool, const QString&)> done, CallFn call) {
    invokeRpcImpl<Req, Resp>(parent, body, done, call);
}

MainWindow::MainWindow(QWidget* parent)
    : QWidget(parent), ui(new Ui::MainWindow), m_net(new QNetworkAccessManager(this)) {
    ui->setupUi(this);

    setupDispatch();

    for (const auto& s : m_serviceList) ui->serviceCombo->addItem(s);
    onServiceChanged(0);

    if (!m_serviceList.isEmpty())
        ui->serviceNameEdit->setText(m_serviceList.first().toLower().replace(' ', '_'));

    connect(ui->connectButton, &QPushButton::clicked, this, &MainWindow::onConnectClicked);
    connect(ui->sendButton,    &QPushButton::clicked, this, &MainWindow::onSendClicked);
    connect(ui->serviceCombo,  QOverload<int>::of(&QComboBox::currentIndexChanged),
            this, &MainWindow::onServiceChanged);
    connect(ui->useConsul,     &QCheckBox::toggled, this, &MainWindow::onUseConsulToggled);
    onUseConsulToggled(ui->useConsul->isChecked());
}

MainWindow::~MainWindow() = default;

void MainWindow::onServiceChanged(int) {
    ui->methodCombo->clear();
    for (const auto& m : m_methodsByService.value(ui->serviceCombo->currentText()))
        ui->methodCombo->addItem(m);
}

void MainWindow::onUseConsulToggled(bool checked) {
    ui->consulUrlEdit->setEnabled(checked);
    ui->serviceNameEdit->setEnabled(checked);
    ui->hostEdit->setEnabled(!checked);
}

void MainWindow::onConnectClicked() {
    if (ui->useConsul->isChecked()) {
        resolveViaConsul();
    } else {
        // Strip http:// prefix if present - grpc::CreateChannel wants host:port.
        QString hp = ui->hostEdit->text().trimmed();
        if (hp.startsWith("http://"))  hp = hp.mid(7);
        if (hp.startsWith("https://")) hp = hp.mid(8);
        applyChannelHostPort(hp);
    }
}

void MainWindow::resolveViaConsul() {
    const QString consul = ui->consulUrlEdit->text().trimmed();
    const QString svc    = ui->serviceNameEdit->text().trimmed();
    if (consul.isEmpty() || svc.isEmpty()) {
        ui->statusLabel->setText("Consul URL and service name are required.");
        return;
    }
    QUrl url(consul + "/v1/health/service/" + svc + "?passing=true");
    ui->statusLabel->setText(QStringLiteral("Resolving %1 via Consul...").arg(svc));

    auto* reply = m_net->get(QNetworkRequest(url));
    connect(reply, &QNetworkReply::finished, this, [this, reply, svc]() {
        reply->deleteLater();
        if (reply->error() != QNetworkReply::NoError) {
            ui->statusLabel->setText(QStringLiteral("Consul error: %1").arg(reply->errorString()));
            return;
        }
        const auto doc = QJsonDocument::fromJson(reply->readAll());
        if (!doc.isArray() || doc.array().isEmpty()) {
            ui->statusLabel->setText(QStringLiteral("No healthy '%1'").arg(svc));
            return;
        }
        const auto entry   = doc.array().first().toObject();
        const auto service = entry.value("Service").toObject();
        QString addr = service.value("Address").toString();
        if (addr.isEmpty())
            addr = entry.value("Node").toObject().value("Address").toString();
        const int port = service.value("Port").toInt();
        if (addr.isEmpty() || port <= 0) {
            ui->statusLabel->setText("Consul entry missing Address/Port.");
            return;
        }
        const QString hp = QStringLiteral("%1:%2").arg(addr).arg(port);
        ui->hostEdit->setText(hp);
        applyChannelHostPort(hp);
    });
}

void MainWindow::applyChannelHostPort(const QString& hostport) {
    m_channel = grpc::CreateChannel(hostport.toStdString(),
                                    grpc::InsecureChannelCredentials());
    ui->statusLabel->setText(QStringLiteral("channel ready: %1 (lazy connect)").arg(hostport));
}

void MainWindow::onSendClicked() {
    if (!m_channel) {
        ui->statusLabel->setText("Click Connect first.");
        return;
    }
    const QString svc = ui->serviceCombo->currentText();
    const QString rpc = ui->methodCombo->currentText();
    const QString key = svc + QChar('.') + rpc;
    const QByteArray body = ui->requestEdit->toPlainText().toUtf8();

    auto it = m_dispatch.find(key);
    if (it == m_dispatch.end()) {
        ui->statusLabel->setText(QStringLiteral("No dispatcher for %1").arg(key));
        return;
    }

    ui->statusLabel->setText(QStringLiteral("Calling %1 ...").arg(key));
    ui->responseEdit->clear();
    it.value()(body, [this](bool ok, const QString& result) {
        ui->responseEdit->setPlainText(result);
        ui->statusLabel->setText(ok ? "OK" : "FAILED");
    });
}

void MainWindow::setupDispatch() {
    m_serviceList << "ComSetupDeviceService";
    m_methodsByService["ComSetupDeviceService"] = { "SetInterfaceType", "GetInterfaceType", "SetInterfaceConfig", "GetInterfaceConfig", "LoadInterfaceConfig", "Connect", "DisConnect", "GetConnectState" };

    m_dispatch.insert("ComSetupDeviceService.SetInterfaceType",
        [this](const QByteArray& j, DoneFn d) {
            invokeRpc<::Com_Setup_Device::InterfaceTypeRequest, ::Com_Setup_Device::CommandResponse>(this, j, d,
                [this](grpc::ClientContext* ctx, const ::Com_Setup_Device::InterfaceTypeRequest& r, ::Com_Setup_Device::CommandResponse* resp) {
                    auto stub = Com_Setup_Device::ComSetupDeviceService::NewStub(m_channel);
                    return stub->SetInterfaceType(ctx, r, resp);
                });
        });

    m_dispatch.insert("ComSetupDeviceService.GetInterfaceType",
        [this](const QByteArray& j, DoneFn d) {
            invokeRpc<::Com_Setup_Device::Empty, ::Com_Setup_Device::GetInterfaceTypeResponse>(this, j, d,
                [this](grpc::ClientContext* ctx, const ::Com_Setup_Device::Empty& r, ::Com_Setup_Device::GetInterfaceTypeResponse* resp) {
                    auto stub = Com_Setup_Device::ComSetupDeviceService::NewStub(m_channel);
                    return stub->GetInterfaceType(ctx, r, resp);
                });
        });

    m_dispatch.insert("ComSetupDeviceService.SetInterfaceConfig",
        [this](const QByteArray& j, DoneFn d) {
            invokeRpc<::Com_Setup_Device::SetInterfaceConfigRequest, ::Com_Setup_Device::CommandResponse>(this, j, d,
                [this](grpc::ClientContext* ctx, const ::Com_Setup_Device::SetInterfaceConfigRequest& r, ::Com_Setup_Device::CommandResponse* resp) {
                    auto stub = Com_Setup_Device::ComSetupDeviceService::NewStub(m_channel);
                    return stub->SetInterfaceConfig(ctx, r, resp);
                });
        });

    m_dispatch.insert("ComSetupDeviceService.GetInterfaceConfig",
        [this](const QByteArray& j, DoneFn d) {
            invokeRpc<::Com_Setup_Device::SetInterfaceConfigRequest, ::Com_Setup_Device::GetInterfaceConfigResponse>(this, j, d,
                [this](grpc::ClientContext* ctx, const ::Com_Setup_Device::SetInterfaceConfigRequest& r, ::Com_Setup_Device::GetInterfaceConfigResponse* resp) {
                    auto stub = Com_Setup_Device::ComSetupDeviceService::NewStub(m_channel);
                    return stub->GetInterfaceConfig(ctx, r, resp);
                });
        });

    m_dispatch.insert("ComSetupDeviceService.LoadInterfaceConfig",
        [this](const QByteArray& j, DoneFn d) {
            invokeRpc<::Com_Setup_Device::LoadInterfaceConfigRequest, ::Com_Setup_Device::CommandResponse>(this, j, d,
                [this](grpc::ClientContext* ctx, const ::Com_Setup_Device::LoadInterfaceConfigRequest& r, ::Com_Setup_Device::CommandResponse* resp) {
                    auto stub = Com_Setup_Device::ComSetupDeviceService::NewStub(m_channel);
                    return stub->LoadInterfaceConfig(ctx, r, resp);
                });
        });

    m_dispatch.insert("ComSetupDeviceService.Connect",
        [this](const QByteArray& j, DoneFn d) {
            invokeRpc<::Com_Setup_Device::Empty, ::Com_Setup_Device::CommandResponse>(this, j, d,
                [this](grpc::ClientContext* ctx, const ::Com_Setup_Device::Empty& r, ::Com_Setup_Device::CommandResponse* resp) {
                    auto stub = Com_Setup_Device::ComSetupDeviceService::NewStub(m_channel);
                    return stub->Connect(ctx, r, resp);
                });
        });

    m_dispatch.insert("ComSetupDeviceService.DisConnect",
        [this](const QByteArray& j, DoneFn d) {
            invokeRpc<::Com_Setup_Device::Empty, ::Com_Setup_Device::CommandResponse>(this, j, d,
                [this](grpc::ClientContext* ctx, const ::Com_Setup_Device::Empty& r, ::Com_Setup_Device::CommandResponse* resp) {
                    auto stub = Com_Setup_Device::ComSetupDeviceService::NewStub(m_channel);
                    return stub->DisConnect(ctx, r, resp);
                });
        });

    m_dispatch.insert("ComSetupDeviceService.GetConnectState",
        [this](const QByteArray& j, DoneFn d) {
            invokeRpc<::Com_Setup_Device::Empty, ::Com_Setup_Device::GetConnectStateResponse>(this, j, d,
                [this](grpc::ClientContext* ctx, const ::Com_Setup_Device::Empty& r, ::Com_Setup_Device::GetConnectStateResponse* resp) {
                    auto stub = Com_Setup_Device::ComSetupDeviceService::NewStub(m_channel);
                    return stub->GetConnectState(ctx, r, resp);
                });
        });

    m_serviceList << "PowerSupplyService";
    m_methodsByService["PowerSupplyService"] = { "SetSubDeviceType", "GetSubDeviceType", "GetSubDeviceTypeChannelCount", "GetSubDeviceType_ListCount", "GetSubDeviceType_ID", "GetSubDeviceType_Name", "InitDevice", "SetVoltage", "SetCurrentLimit", "SetOutputEnabled", "ReadCurrent", "ReadVoltage" };

    m_dispatch.insert("PowerSupplyService.SetSubDeviceType",
        [this](const QByteArray& j, DoneFn d) {
            invokeRpc<::power_device::SubDeviceTypeRequest, ::power_device::CommandResponse>(this, j, d,
                [this](grpc::ClientContext* ctx, const ::power_device::SubDeviceTypeRequest& r, ::power_device::CommandResponse* resp) {
                    auto stub = power_device::PowerSupplyService::NewStub(m_channel);
                    return stub->SetSubDeviceType(ctx, r, resp);
                });
        });

    m_dispatch.insert("PowerSupplyService.GetSubDeviceType",
        [this](const QByteArray& j, DoneFn d) {
            invokeRpc<::power_device::Empty, ::power_device::GetSubDeviceTypeResponse>(this, j, d,
                [this](grpc::ClientContext* ctx, const ::power_device::Empty& r, ::power_device::GetSubDeviceTypeResponse* resp) {
                    auto stub = power_device::PowerSupplyService::NewStub(m_channel);
                    return stub->GetSubDeviceType(ctx, r, resp);
                });
        });

    m_dispatch.insert("PowerSupplyService.GetSubDeviceTypeChannelCount",
        [this](const QByteArray& j, DoneFn d) {
            invokeRpc<::power_device::Empty, ::power_device::ChannelCountResponse>(this, j, d,
                [this](grpc::ClientContext* ctx, const ::power_device::Empty& r, ::power_device::ChannelCountResponse* resp) {
                    auto stub = power_device::PowerSupplyService::NewStub(m_channel);
                    return stub->GetSubDeviceTypeChannelCount(ctx, r, resp);
                });
        });

    m_dispatch.insert("PowerSupplyService.GetSubDeviceType_ListCount",
        [this](const QByteArray& j, DoneFn d) {
            invokeRpc<::power_device::Empty, ::power_device::GetSubDeviceTypeListCountResponse>(this, j, d,
                [this](grpc::ClientContext* ctx, const ::power_device::Empty& r, ::power_device::GetSubDeviceTypeListCountResponse* resp) {
                    auto stub = power_device::PowerSupplyService::NewStub(m_channel);
                    return stub->GetSubDeviceType_ListCount(ctx, r, resp);
                });
        });

    m_dispatch.insert("PowerSupplyService.GetSubDeviceType_ID",
        [this](const QByteArray& j, DoneFn d) {
            invokeRpc<::power_device::SubDeviceTypeRequest, ::power_device::GetSubDeviceTypeIDResponse>(this, j, d,
                [this](grpc::ClientContext* ctx, const ::power_device::SubDeviceTypeRequest& r, ::power_device::GetSubDeviceTypeIDResponse* resp) {
                    auto stub = power_device::PowerSupplyService::NewStub(m_channel);
                    return stub->GetSubDeviceType_ID(ctx, r, resp);
                });
        });

    m_dispatch.insert("PowerSupplyService.GetSubDeviceType_Name",
        [this](const QByteArray& j, DoneFn d) {
            invokeRpc<::power_device::SubDeviceTypeRequest, ::power_device::GetSubDeviceTypeNameResponse>(this, j, d,
                [this](grpc::ClientContext* ctx, const ::power_device::SubDeviceTypeRequest& r, ::power_device::GetSubDeviceTypeNameResponse* resp) {
                    auto stub = power_device::PowerSupplyService::NewStub(m_channel);
                    return stub->GetSubDeviceType_Name(ctx, r, resp);
                });
        });

    m_dispatch.insert("PowerSupplyService.InitDevice",
        [this](const QByteArray& j, DoneFn d) {
            invokeRpc<::power_device::Empty, ::power_device::CommandResponse>(this, j, d,
                [this](grpc::ClientContext* ctx, const ::power_device::Empty& r, ::power_device::CommandResponse* resp) {
                    auto stub = power_device::PowerSupplyService::NewStub(m_channel);
                    return stub->InitDevice(ctx, r, resp);
                });
        });

    m_dispatch.insert("PowerSupplyService.SetVoltage",
        [this](const QByteArray& j, DoneFn d) {
            invokeRpc<::power_device::SetVoltageRequest, ::power_device::CommandResponse>(this, j, d,
                [this](grpc::ClientContext* ctx, const ::power_device::SetVoltageRequest& r, ::power_device::CommandResponse* resp) {
                    auto stub = power_device::PowerSupplyService::NewStub(m_channel);
                    return stub->SetVoltage(ctx, r, resp);
                });
        });

    m_dispatch.insert("PowerSupplyService.SetCurrentLimit",
        [this](const QByteArray& j, DoneFn d) {
            invokeRpc<::power_device::SetCurrentLimitRequest, ::power_device::CommandResponse>(this, j, d,
                [this](grpc::ClientContext* ctx, const ::power_device::SetCurrentLimitRequest& r, ::power_device::CommandResponse* resp) {
                    auto stub = power_device::PowerSupplyService::NewStub(m_channel);
                    return stub->SetCurrentLimit(ctx, r, resp);
                });
        });

    m_dispatch.insert("PowerSupplyService.SetOutputEnabled",
        [this](const QByteArray& j, DoneFn d) {
            invokeRpc<::power_device::SetOutputEnabledRequest, ::power_device::CommandResponse>(this, j, d,
                [this](grpc::ClientContext* ctx, const ::power_device::SetOutputEnabledRequest& r, ::power_device::CommandResponse* resp) {
                    auto stub = power_device::PowerSupplyService::NewStub(m_channel);
                    return stub->SetOutputEnabled(ctx, r, resp);
                });
        });

    m_dispatch.insert("PowerSupplyService.ReadCurrent",
        [this](const QByteArray& j, DoneFn d) {
            invokeRpc<::power_device::ChannelRequest, ::power_device::GetMeasurementsResponse>(this, j, d,
                [this](grpc::ClientContext* ctx, const ::power_device::ChannelRequest& r, ::power_device::GetMeasurementsResponse* resp) {
                    auto stub = power_device::PowerSupplyService::NewStub(m_channel);
                    return stub->ReadCurrent(ctx, r, resp);
                });
        });

    m_dispatch.insert("PowerSupplyService.ReadVoltage",
        [this](const QByteArray& j, DoneFn d) {
            invokeRpc<::power_device::ChannelRequest, ::power_device::GetMeasurementsResponse>(this, j, d,
                [this](grpc::ClientContext* ctx, const ::power_device::ChannelRequest& r, ::power_device::GetMeasurementsResponse* resp) {
                    auto stub = power_device::PowerSupplyService::NewStub(m_channel);
                    return stub->ReadVoltage(ctx, r, resp);
                });
        });
}
