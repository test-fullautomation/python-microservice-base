// preview/main.cpp — QML viewer for designing and testing ServiceUI.qml.
//
// Modes:
//   MyQMLServicePreview.exe                Stub mode — mock responses (design)
//   MyQMLServicePreview.exe --live         Live mode — direct RabbitMQ RPC
//   MyQMLServicePreview.exe --live --broker host:port
//
// Prerequisites for live mode:
//   1. RabbitMQ running
//   2. MyQMLService.exe (backend) running and registered

#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QtQml>
#include <QDir>
#include <QFile>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTextStream>
#include <QDateTime>

#ifdef HAS_LIVE_BRIDGE
#include "LiveServiceBridge.h"
#endif

// Log Qt messages to a file next to the exe for diagnostics.
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

int main(int argc, char *argv[])
{
    QGuiApplication app(argc, argv);

    const QString appDir = app.applicationDirPath();

    // Set up file logging
    g_logFile = new QFile(appDir + "/preview.log");
    g_logFile->open(QIODevice::WriteOnly | QIODevice::Truncate);
    qInstallMessageHandler(messageHandler);

    qDebug() << "App dir:" << appDir;

    // ---- Parse arguments ----
    bool liveMode = false;
    QString brokerOverride;   // "host:port" override
    QString qmlArg;

    const QStringList args = app.arguments();
    qDebug() << "argc:" << args.size() << "args:" << args;
    for (int i = 1; i < args.size(); ++i) {
        const QString &arg = args[i];
        qDebug() << "  arg[" << i << "]:" << arg
                 << "len:" << arg.length()
                 << "startsWith(--):" << arg.startsWith("--");
        if (arg == "--live" || arg == "-live" || arg == "/live") {
            liveMode = true;
        } else if ((arg == "--broker" || arg == "-broker") && i + 1 < args.size()) {
            brokerOverride = args[++i];
        } else if (!arg.startsWith("-") && !arg.startsWith("/")) {
            qmlArg = arg;
        }
    }

    qDebug() << "Mode:" << (liveMode ? "LIVE" : "STUB")
             << "qmlArg:" << qmlArg;

    QQmlApplicationEngine engine;

    // ---- Live mode: register real C++ ServiceBridge ----
#ifdef HAS_LIVE_BRIDGE
    LiveServiceBridge *liveBridge = nullptr;
    if (liveMode) {
        // Read broker config from service_config.json
        std::string host  = "localhost";
        int         port  = 5672;
        std::string vhost = "/";
        std::string user  = "guest";
        std::string pass  = "guest";

        // Try to load service_config.json next to the exe
        QString configPath = appDir + "/service_config.json";
        if (!QFile::exists(configPath)) {
            // Fallback: source tree location
#ifdef QML_DIR
            configPath = QDir::cleanPath(
                QStringLiteral(QML_DIR) + "/../service_config.json");
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
                qDebug() << "Loaded broker config from:" << configPath;
            }
        }

        // Command-line override: --broker host:port
        if (!brokerOverride.isEmpty()) {
            QStringList parts = brokerOverride.split(':');
            host = parts[0].toStdString();
            if (parts.size() > 1)
                port = parts[1].toInt();
        }

        qDebug() << "Broker:" << QString::fromStdString(host) << ":" << port;

        liveBridge = new LiveServiceBridge(&app);
        liveBridge->configure(host, port, vhost, user, pass);

        // Register as a QML singleton — replaces the stub ServiceBridge.qml.
        // Must be called BEFORE the engine loads any QML.
        qmlRegisterSingletonInstance("MicroserviceBase", 1, 0,
                                     "ServiceBridge", liveBridge);
        qDebug() << "Live ServiceBridge registered (direct RabbitMQ)";
    }
#else
    if (liveMode) {
        qWarning() << "--live mode not available (built without CppServiceBase)."
                    << "Running in stub mode.";
        liveMode = false;
    }
#endif

    // ---- Stubs import path ----
    // Always add stubs so "import MicroserviceBase 1.0" resolves.
    // In live mode the C++ singleton (registered above) takes priority
    // over the QML stub singleton.
    const QString deployStubs = appDir + "/stubs";
    if (QDir(deployStubs).exists()) {
        engine.addImportPath(deployStubs);
        qDebug() << "Stubs path (deploy):" << deployStubs;
    } else {
#ifdef STUBS_IMPORT_PATH
        engine.addImportPath(QStringLiteral(STUBS_IMPORT_PATH));
        qDebug() << "Stubs path (compile-time):" << STUBS_IMPORT_PATH;
#endif
        engine.addImportPath(appDir + "/../stubs");
    }

    // ---- Find ServiceUI.qml ----
    QUrl qmlUrl;
    if (!qmlArg.isEmpty()) {
        qmlUrl = QUrl::fromLocalFile(QDir::cleanPath(qmlArg));
    } else {
        const QString deployQml = appDir + "/qml/ServiceUI.qml";
        if (QFile::exists(deployQml)) {
            qmlUrl = QUrl::fromLocalFile(QDir::cleanPath(deployQml));
        } else {
#ifdef QML_DIR
            qmlUrl = QUrl::fromLocalFile(
                QDir::cleanPath(QStringLiteral(QML_DIR) + "/ServiceUI.qml"));
#else
            qmlUrl = QUrl::fromLocalFile("qml/ServiceUI.qml");
#endif
        }
    }

    qDebug() << "Loading QML:" << qmlUrl;

    // ---- Load QML inside an ApplicationWindow wrapper ----
    const QString modeTitle = liveMode
        ? QStringLiteral("MyQMLService Preview [LIVE]")
        : QStringLiteral("MyQMLService Preview [STUB]");

    const QString wrapper = QStringLiteral(
        "import QtQuick 2.15\n"
        "import QtQuick.Controls 2.15\n"
        "ApplicationWindow {\n"
        "    visible: true\n"
        "    title: \"%1\"\n"
        "    width: 620\n"
        "    height: 820\n"
        "    Loader {\n"
        "        id: loader\n"
        "        anchors.fill: parent\n"
        "        source: \"%2\"\n"
        "        onLoaded: {\n"
        "            if (item && item.width > 0 && item.height > 0) {\n"
        "                loader.parent.Window.window.width = item.width + 20\n"
        "                loader.parent.Window.window.height = item.height + 20\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    ).arg(modeTitle, qmlUrl.toString());

    engine.loadData(wrapper.toUtf8(), QUrl(QStringLiteral("qrc:/preview_wrapper.qml")));

    if (engine.rootObjects().isEmpty()) {
        qWarning() << "Failed to load QML wrapper";
        delete g_logFile;
        return -1;
    }

    qDebug() << "Preview window created successfully";

    int rc = app.exec();
    delete g_logFile;
    return rc;
}
