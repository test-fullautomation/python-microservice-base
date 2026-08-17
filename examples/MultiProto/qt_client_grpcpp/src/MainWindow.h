#pragma once

#include <QWidget>
#include <QHash>
#include <QString>
#include <QByteArray>

#include <functional>
#include <memory>

#include "com_config_device.pb.h"
#include "com_config_device.grpc.pb.h"
#include "power_device.pb.h"
#include "power_device.grpc.pb.h"

namespace Ui { class MainWindow; }
namespace grpc { class Channel; }
class QNetworkAccessManager;

// Inherits QWidget (not QMainWindow) because the .ui file's root is
// <widget class="QWidget">.  Mismatching root class makes setupUi
// drop most child widgets - QMainWindow uses centralWidget/dock layout,
// which conflicts with a plain QVBoxLayout from a QWidget .ui.
class MainWindow : public QWidget {
    Q_OBJECT
public:
    explicit MainWindow(QWidget* parent = nullptr);
    ~MainWindow() override;

private slots:
    void onConnectClicked();
    void onSendClicked();
    void onServiceChanged(int);
    void onUseConsulToggled(bool checked);

private:
    using DoneFn  = std::function<void(bool ok, const QString& body)>;
    using DispFn  = std::function<void(const QByteArray&, DoneFn)>;

    void setupDispatch();
    void resolveViaConsul();
    void applyChannelHostPort(const QString& hostport);

    Ui::MainWindow* ui = nullptr;
    QNetworkAccessManager* m_net = nullptr;
    std::shared_ptr<grpc::Channel> m_channel;

    QHash<QString, DispFn> m_dispatch;
    QStringList m_serviceList;
    QHash<QString, QStringList> m_methodsByService;
};
