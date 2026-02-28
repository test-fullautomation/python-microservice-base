/**
 * @file WidgetController.cpp
 * @brief Implementation of dynamic .ui loading and auto-wiring for the Widget Shell.
 */

#include "WidgetController.h"
#include "ServiceBridge.h"

#include <QUiLoader>
#include <QBuffer>
#include <QVBoxLayout>
#include <QPushButton>
#include <QLabel>
#include <QLineEdit>
#include <QSpinBox>
#include <QDoubleSpinBox>
#include <QComboBox>
#include <QCheckBox>
#include <QJsonArray>
#include <QJsonValue>
#include <QDebug>

WidgetController *WidgetController::s_instance = nullptr;

WidgetController::WidgetController(QWidget *rootContainer, ServiceBridge *bridge,
                                    QObject *parent)
    : QObject(parent)
    , m_rootContainer(rootContainer)
    , m_bridge(bridge)
{
    s_instance = this;
}

WidgetController *WidgetController::instance()
{
    return s_instance;
}

void WidgetController::loadUiSource(const QByteArray &uiXml)
{
    // Clear any existing content.
    clearUi();

    QUiLoader loader;
    QBuffer buffer;
    buffer.setData(uiXml);
    buffer.open(QIODevice::ReadOnly);

    QWidget *widget = loader.load(&buffer, m_rootContainer);

    if (!widget) {
        QString err = "QUiLoader failed: " + loader.errorString();
        qWarning() << "WidgetController:" << err;
        emit uiError(err);
        return;
    }

    // Parent the loaded widget into the root container.
    if (!m_rootContainer->layout()) {
        new QVBoxLayout(m_rootContainer);
        m_rootContainer->layout()->setContentsMargins(0, 0, 0, 0);
    }
    m_rootContainer->layout()->addWidget(widget);
    m_currentWidget = widget;

    // Auto-wire buttons to service calls.
    wireButtons();

    emit uiReady();
}

void WidgetController::clearUi()
{
    if (m_currentWidget) {
        m_currentWidget->setParent(nullptr);
        m_currentWidget->deleteLater();
        m_currentWidget = nullptr;
    }
}

void WidgetController::wireButtons()
{
    if (!m_currentWidget || !m_bridge) return;

    // Find the result label (if present).
    QLabel *resultLabel = m_currentWidget->findChild<QLabel *>("resultLabel");

    // Connect bridge signals to the result label.
    if (resultLabel) {
        connect(m_bridge, &ServiceBridge::responseReceived, this,
                [resultLabel](const QString &method, const QString &result) {
                    resultLabel->setText(method + ": " + result);
                    resultLabel->setStyleSheet("color: green;");
                });
        connect(m_bridge, &ServiceBridge::errorOccurred, this,
                [resultLabel](const QString &method, const QString &error) {
                    resultLabel->setText(method + " error: " + error);
                    resultLabel->setStyleSheet("color: red;");
                });
    }

    // Find all QPushButtons and wire those with serviceMethod property.
    auto buttons = m_currentWidget->findChildren<QPushButton *>();
    for (QPushButton *btn : buttons) {
        QVariant methodVar = btn->property("serviceMethod");
        if (!methodVar.isValid() || methodVar.toString().isEmpty()) {
            continue;
        }

        QString method = methodVar.toString();
        QVariant argsVar = btn->property("serviceArgs");
        QStringList argNames;
        if (argsVar.isValid() && !argsVar.toString().isEmpty()) {
            argNames = argsVar.toString().split(',', Qt::SkipEmptyParts);
            for (QString &name : argNames) {
                name = name.trimmed();
            }
        }

        // Capture copies for the lambda.
        QWidget *rootWidget = m_currentWidget;
        ServiceBridge *bridge = m_bridge;

        connect(btn, &QPushButton::clicked, this,
                [this, bridge, rootWidget, method, argNames]() {
                    QJsonArray args;
                    for (const QString &argName : argNames) {
                        QWidget *inputWidget = rootWidget->findChild<QWidget *>(argName);
                        if (inputWidget) {
                            args.append(extractWidgetValue(inputWidget));
                        } else {
                            args.append(QString());
                            qWarning() << "WidgetController: input widget not found:" << argName;
                        }
                    }
                    bridge->callService(QString(), method, args);
                });

        qDebug() << "WidgetController: wired" << btn->objectName()
                 << "→" << method << "args:" << argNames;
    }
}

QString WidgetController::extractWidgetValue(QWidget *widget) const
{
    // QLineEdit
    if (auto *lineEdit = qobject_cast<QLineEdit *>(widget)) {
        return lineEdit->text();
    }
    // QSpinBox
    if (auto *spinBox = qobject_cast<QSpinBox *>(widget)) {
        return QString::number(spinBox->value());
    }
    // QDoubleSpinBox
    if (auto *dblSpinBox = qobject_cast<QDoubleSpinBox *>(widget)) {
        return QString::number(dblSpinBox->value());
    }
    // QComboBox
    if (auto *comboBox = qobject_cast<QComboBox *>(widget)) {
        return comboBox->currentText();
    }
    // QCheckBox
    if (auto *checkBox = qobject_cast<QCheckBox *>(widget)) {
        return checkBox->isChecked() ? "true" : "false";
    }
    // Fallback: try to read text property
    QVariant textProp = widget->property("text");
    if (textProp.isValid()) {
        return textProp.toString();
    }
    return QString();
}
