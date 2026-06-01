/**
 * @file MainWidget.cpp
 * @brief Implementation of the MainWidget for the Qt WASM service template.
 *
 * Loads UI from ServiceUI.ui (via uic-generated header) and connects
 * button clicks to ServiceBridge calls.
 */

#include "MainWidget.h"
#include "ui_ServiceUI.h"
#include "ServiceBridge.h"

MainWidget::MainWidget(QWidget *parent)
    : QWidget(parent)
    , ui(new Ui::ServiceForm)
{
    ui->setupUi(this);

    m_bridge = new ServiceBridge(this);

    connect(m_bridge, &ServiceBridge::responseReceived,
            this, &MainWidget::onResponse);
    connect(m_bridge, &ServiceBridge::errorOccurred,
            this, &MainWidget::onError);

    // Connect buttons to slots
    connect(ui->helloButton, &QPushButton::clicked,
            this, &MainWidget::onHelloClicked);
    connect(ui->echoButton, &QPushButton::clicked,
            this, &MainWidget::onEchoClicked);
    connect(ui->computeButton, &QPushButton::clicked,
            this, &MainWidget::onComputeClicked);
}

MainWidget::~MainWidget()
{
    delete ui;
}

void MainWidget::onHelloClicked()
{
    QJsonArray args;
    args.append(ui->nameInput->text());
    m_bridge->callService("MyQtWasmService", "svc_api_hello", args);
    ui->helloResult->setText("Calling svc_api_hello...");
}

void MainWidget::onEchoClicked()
{
    QJsonArray args;
    args.append(ui->echoInput->text());
    m_bridge->callService("MyQtWasmService", "svc_api_echo", args);
    ui->echoResult->setText("Calling svc_api_echo...");
}

void MainWidget::onComputeClicked()
{
    QJsonArray args;
    args.append(ui->numbersInput->text());
    m_bridge->callService("MyQtWasmService", "svc_api_compute", args);
    ui->computeResult->setText("Calling svc_api_compute...");
}

void MainWidget::onResponse(const QString &method, const QString &result)
{
    QString text = QString("<b>%1</b>: %2").arg(method, result);

    if (method == "svc_api_hello") {
        ui->helloResult->setTextFormat(Qt::RichText);
        ui->helloResult->setText(text);
    } else if (method == "svc_api_echo") {
        ui->echoResult->setTextFormat(Qt::RichText);
        ui->echoResult->setText(text);
    } else if (method == "svc_api_compute") {
        ui->computeResult->setTextFormat(Qt::RichText);
        ui->computeResult->setText(text);
    }
}

void MainWidget::onError(const QString &method, const QString &error)
{
    QString text = QString("<b style='color:red;'>Error in %1</b>: %2").arg(method, error);

    if (method == "svc_api_hello") {
        ui->helloResult->setTextFormat(Qt::RichText);
        ui->helloResult->setText(text);
    } else if (method == "svc_api_echo") {
        ui->echoResult->setTextFormat(Qt::RichText);
        ui->echoResult->setText(text);
    } else if (method == "svc_api_compute") {
        ui->computeResult->setTextFormat(Qt::RichText);
        ui->computeResult->setText(text);
    }
}
