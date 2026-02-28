/**
 * @file MainWidget.cpp
 * @brief Implementation of the MainWidget for the Qt WASM service template.
 */

#include "MainWidget.h"
#include "ServiceBridge.h"

#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QLineEdit>
#include <QLabel>
#include <QPushButton>
#include <QGroupBox>

MainWidget::MainWidget(QWidget *parent)
    : QWidget(parent)
{
    m_bridge = new ServiceBridge(this);

    connect(m_bridge, &ServiceBridge::responseReceived,
            this, &MainWidget::onResponse);
    connect(m_bridge, &ServiceBridge::errorOccurred,
            this, &MainWidget::onError);

    // --- Layout ---
    auto *mainLayout = new QVBoxLayout(this);
    mainLayout->setContentsMargins(16, 16, 16, 16);

    // Title
    auto *titleLabel = new QLabel("<h2>MyQtWasmService</h2>"
                                  "<p style='color:gray;'>Qt WASM Template Service</p>");
    titleLabel->setTextFormat(Qt::RichText);
    mainLayout->addWidget(titleLabel);

    // Hello form group
    auto *helloGroup = new QGroupBox("Say Hello");
    auto *helloLayout = new QHBoxLayout(helloGroup);

    m_nameEdit = new QLineEdit;
    m_nameEdit->setPlaceholderText("Enter a name...");
    m_nameEdit->setText("World");
    helloLayout->addWidget(m_nameEdit);

    m_helloBtn = new QPushButton("Say Hello");
    connect(m_helloBtn, &QPushButton::clicked, this, &MainWidget::onHelloClicked);
    helloLayout->addWidget(m_helloBtn);

    mainLayout->addWidget(helloGroup);

    // Version button
    auto *versionGroup = new QGroupBox("Service Info");
    auto *versionLayout = new QHBoxLayout(versionGroup);

    m_versionBtn = new QPushButton("Get Version");
    connect(m_versionBtn, &QPushButton::clicked, this, &MainWidget::onVersionClicked);
    versionLayout->addWidget(m_versionBtn);

    mainLayout->addWidget(versionGroup);

    // Result display
    m_resultLabel = new QLabel("Result will appear here.");
    m_resultLabel->setWordWrap(true);
    m_resultLabel->setStyleSheet(
        "QLabel { background-color: #f0f0f0; padding: 12px; border-radius: 6px; }");
    mainLayout->addWidget(m_resultLabel);

    mainLayout->addStretch();
}

void MainWidget::onHelloClicked()
{
    QJsonArray args;
    args.append(m_nameEdit->text());
    m_bridge->callService("MyQtWasmService", "svc_api_hello", args);
    m_resultLabel->setText("Calling svc_api_hello...");
}

void MainWidget::onVersionClicked()
{
    m_bridge->callService("MyQtWasmService", "svc_api_get_version", QJsonArray{});
    m_resultLabel->setText("Calling svc_api_get_version...");
}

void MainWidget::onResponse(const QString &method, const QString &result)
{
    m_resultLabel->setText(
        QString("<b>%1</b>: %2").arg(method, result));
    m_resultLabel->setTextFormat(Qt::RichText);
}

void MainWidget::onError(const QString &method, const QString &error)
{
    m_resultLabel->setText(
        QString("<b style='color:red;'>Error in %1</b>: %2").arg(method, error));
    m_resultLabel->setTextFormat(Qt::RichText);
}
