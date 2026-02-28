// preview/main.cpp — Widget viewer for designing and testing ServiceUI.ui.
//
// Modes:
//   MyWidgetServicePreview.exe                Stub mode — mock responses (design)
//   MyWidgetServicePreview.exe --live         Live mode — direct RabbitMQ RPC
//   MyWidgetServicePreview.exe --live --broker host:port
//   MyWidgetServicePreview.exe path/to/Other.ui
//
// Prerequisites for live mode:
//   1. RabbitMQ running
//   2. MyWidgetService.exe (backend) running and registered

#include <QApplication>
#include <QUiLoader>
#include <QFile>
#include <QDir>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonArray>
#include <QPushButton>
#include <QLabel>
#include <QLineEdit>
#include <QSpinBox>
#include <QDoubleSpinBox>
#include <QComboBox>
#include <QCheckBox>
#include <QTextStream>
#include <QDateTime>
#include <QDebug>

#ifdef HAS_LIVE_BRIDGE
#include "LiveServiceBridge.h"
#endif

// ---------------------------------------------------------------------------
// Log Qt messages to a file next to the exe for diagnostics.
// ---------------------------------------------------------------------------
static QFile *g_logFile = nullptr;

void messageHandler(QtMsgType type, const QMessageLogContext &, const QString &msg)
{
    if (!g_logFile) return;
    const char *level = "DEBUG";
    switch (type) {
    case QtWarningMsg:  level = "WARN "; break;
    case QtCriticalMsg: level = "ERROR"; break;
    case QtFatalMsg:    level = "FATAL"; break;
    default: break;
    }
    QTextStream out(g_logFile);
    out << QDateTime::currentDateTime().toString(Qt::ISODate)
        << " [" << level << "] " << msg << "\n";
    out.flush();
}

// ---------------------------------------------------------------------------
// Extract text/value from a widget by type (same cascade as WidgetController).
// ---------------------------------------------------------------------------
static QString extractWidgetValue(QWidget *widget)
{
    if (auto *le = qobject_cast<QLineEdit *>(widget))
        return le->text();
    if (auto *sb = qobject_cast<QSpinBox *>(widget))
        return QString::number(sb->value());
    if (auto *dsb = qobject_cast<QDoubleSpinBox *>(widget))
        return QString::number(dsb->value());
    if (auto *cb = qobject_cast<QComboBox *>(widget))
        return cb->currentText();
    if (auto *chk = qobject_cast<QCheckBox *>(widget))
        return chk->isChecked() ? "true" : "false";
    QVariant v = widget->property("text");
    return v.isValid() ? v.toString() : QString();
}

// ---------------------------------------------------------------------------
// Auto-wire buttons: read serviceMethod/serviceArgs dynamic properties
// and connect clicked() to either stub or live handler.
// ---------------------------------------------------------------------------
static void wireButtons(QWidget *root, QLabel *resultLabel, bool liveMode
#ifdef HAS_LIVE_BRIDGE
    , LiveServiceBridge *liveBridge
#endif
)
{
    auto buttons = root->findChildren<QPushButton *>();
    for (QPushButton *btn : buttons) {
        QString method = btn->property("serviceMethod").toString();
        if (method.isEmpty()) continue;

        QStringList argNames;
        QString argsStr = btn->property("serviceArgs").toString();
        if (!argsStr.isEmpty()) {
            argNames = argsStr.split(',', Qt::SkipEmptyParts);
            for (QString &n : argNames) n = n.trimmed();
        }

        QObject::connect(btn, &QPushButton::clicked, [=]() {
            // Collect argument values from input widgets.
            QStringList values;
            QJsonArray jsonArgs;
            for (const QString &name : argNames) {
                QWidget *input = root->findChild<QWidget *>(name);
                QString val = input ? extractWidgetValue(input) : QString();
                values << val;
                jsonArgs.append(val);
            }

#ifdef HAS_LIVE_BRIDGE
            if (liveMode && liveBridge) {
                liveBridge->callService(liveBridge->serviceName(), method, jsonArgs);
                return;
            }
#endif
            // Stub mode: display a mock response.
            if (resultLabel) {
                resultLabel->setText(
                    QString("[Stub] %1(%2)").arg(method, values.join(", ")));
                resultLabel->setStyleSheet("color: blue;");
            }
        });

        qDebug() << "Wired:" << btn->objectName() << "→" << method
                 << "args:" << argNames;
    }
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------
int main(int argc, char *argv[])
{
    QApplication app(argc, argv);

    const QString appDir = app.applicationDirPath();

    // Set up file logging.
    g_logFile = new QFile(appDir + "/preview.log");
    g_logFile->open(QIODevice::WriteOnly | QIODevice::Truncate);
    qInstallMessageHandler(messageHandler);

    qDebug() << "App dir:" << appDir;

    // ---- Parse arguments ----
    bool liveMode = false;
    QString brokerOverride;
    QString uiArg;

    const QStringList args = app.arguments();
    for (int i = 1; i < args.size(); ++i) {
        const QString &arg = args[i];
        if (arg == "--live" || arg == "-live" || arg == "/live") {
            liveMode = true;
        } else if ((arg == "--broker" || arg == "-broker") && i + 1 < args.size()) {
            brokerOverride = args[++i];
        } else if (!arg.startsWith("-") && !arg.startsWith("/")) {
            uiArg = arg;
        }
    }

    qDebug() << "Mode:" << (liveMode ? "LIVE" : "STUB") << "uiArg:" << uiArg;

    // ---- Live mode: create LiveServiceBridge ----
#ifdef HAS_LIVE_BRIDGE
    LiveServiceBridge *liveBridge = nullptr;
    if (liveMode) {
        std::string host  = "localhost";
        int         port  = 5672;
        std::string vhost = "/";
        std::string user  = "guest";
        std::string pass  = "guest";
        QString routingKey;

        // Load broker config from service_config.json.
        QString configPath = appDir + "/service_config.json";
        if (!QFile::exists(configPath)) {
#ifdef UI_DIR
            configPath = QDir::cleanPath(
                QStringLiteral(UI_DIR) + "/../service_config.json");
#endif
        }

        if (QFile::exists(configPath)) {
            QFile f(configPath);
            if (f.open(QIODevice::ReadOnly)) {
                QJsonObject cfg = QJsonDocument::fromJson(f.readAll()).object();
                if (cfg.contains("broker_host"))
                    host = cfg["broker_host"].toString().toStdString();
                if (cfg.contains("broker_port"))
                    port = cfg["broker_port"].toInt();
                if (cfg.contains("broker_vhost"))
                    vhost = cfg["broker_vhost"].toString().toStdString();
                if (cfg.contains("broker_user"))
                    user = cfg["broker_user"].toString().toStdString();
                if (cfg.contains("broker_pass"))
                    pass = cfg["broker_pass"].toString().toStdString();

                // Read routing_key — this is the RabbitMQ routing key the
                // backend binds to on the "services_request" exchange.
                if (cfg.contains("routing_key"))
                    routingKey = cfg["routing_key"].toString();
                else if (cfg.contains("name"))
                    routingKey = cfg["name"].toString();

                qDebug() << "Loaded broker config from:" << configPath;
            }
        }

        if (!brokerOverride.isEmpty()) {
            QStringList parts = brokerOverride.split(':');
            host = parts[0].toStdString();
            if (parts.size() > 1)
                port = parts[1].toInt();
        }

        qDebug() << "Broker:" << QString::fromStdString(host) << ":" << port;

        liveBridge = new LiveServiceBridge(&app);
        liveBridge->configure(host, port, vhost, user, pass);
        liveBridge->setServiceName(routingKey);
        qDebug() << "Live ServiceBridge ready (direct RabbitMQ)"
                 << "routingKey:" << routingKey;
    }
#else
    if (liveMode) {
        qWarning() << "--live mode not available (built without CppServiceBase)."
                    << "Running in stub mode.";
        liveMode = false;
    }
#endif

    // ---- Find ServiceUI.ui ----
    QString uiPath;
    if (!uiArg.isEmpty()) {
        uiPath = QDir::cleanPath(uiArg);
    } else {
        const QString deployUi = appDir + "/ui/ServiceUI.ui";
        if (QFile::exists(deployUi)) {
            uiPath = deployUi;
        } else {
#ifdef UI_DIR
            uiPath = QDir::cleanPath(
                QStringLiteral(UI_DIR) + "/ServiceUI.ui");
#else
            uiPath = "ui/ServiceUI.ui";
#endif
        }
    }

    qDebug() << "Loading UI:" << uiPath;

    // ---- Load .ui file ----
    QUiLoader loader;
    QFile file(uiPath);
    if (!file.open(QIODevice::ReadOnly)) {
        qWarning() << "Cannot open .ui file:" << uiPath;
        delete g_logFile;
        return 1;
    }

    QWidget *widget = loader.load(&file);
    file.close();

    if (!widget) {
        qWarning() << "QUiLoader failed:" << loader.errorString();
        delete g_logFile;
        return 1;
    }

    // ---- Set window title ----
    const QString modeTitle = liveMode
        ? QStringLiteral("MyWidgetService Preview [LIVE]")
        : QStringLiteral("MyWidgetService Preview [STUB]");
    widget->setWindowTitle(modeTitle);

    // ---- Auto-wire buttons ----
    QLabel *resultLabel = widget->findChild<QLabel *>("resultLabel");

    wireButtons(widget, resultLabel, liveMode
#ifdef HAS_LIVE_BRIDGE
        , liveBridge
#endif
    );

#ifdef HAS_LIVE_BRIDGE
    // Route live bridge responses to resultLabel.
    if (liveMode && liveBridge && resultLabel) {
        QObject::connect(liveBridge, &LiveServiceBridge::responseReceived,
            [resultLabel](const QString &method, const QString &result) {
                resultLabel->setText(method + ": " + result);
                resultLabel->setStyleSheet("color: green;");
            });
        QObject::connect(liveBridge, &LiveServiceBridge::errorOccurred,
            [resultLabel](const QString &method, const QString &error) {
                resultLabel->setText(method + " error: " + error);
                resultLabel->setStyleSheet("color: red;");
            });
    }
#endif

    widget->show();
    qDebug() << "Preview window created successfully";

    int rc = app.exec();
    delete g_logFile;
    return rc;
}
