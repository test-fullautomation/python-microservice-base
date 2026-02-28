/**
 * @file MainWidget.h
 * @brief Main UI widget for the Qt WASM service template.
 *
 * Demonstrates a simple form that calls a microservice method
 * and displays the result.
 */

#pragma once

#include <QWidget>

class QLineEdit;
class QLabel;
class QPushButton;
class ServiceBridge;

class MainWidget : public QWidget
{
    Q_OBJECT

public:
    explicit MainWidget(QWidget *parent = nullptr);

private slots:
    void onHelloClicked();
    void onVersionClicked();
    void onResponse(const QString &method, const QString &result);
    void onError(const QString &method, const QString &error);

private:
    QLineEdit   *m_nameEdit;
    QLabel      *m_resultLabel;
    QPushButton *m_helloBtn;
    QPushButton *m_versionBtn;
    ServiceBridge *m_bridge;
};
