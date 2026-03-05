/**
 * @file MainWidget.h
 * @brief Main UI widget for the Qt WASM service template.
 *
 * Uses a .ui file (ServiceUI.ui) designed in Qt Designer.
 * Connects buttons to ServiceBridge calls for microservice interaction.
 */

#pragma once

#include <QWidget>

namespace Ui { class ServiceForm; }

class ServiceBridge;

class MainWidget : public QWidget
{
    Q_OBJECT

public:
    explicit MainWidget(QWidget *parent = nullptr);
    ~MainWidget();

private slots:
    void onHelloClicked();
    void onEchoClicked();
    void onComputeClicked();
    void onResponse(const QString &method, const QString &result);
    void onError(const QString &method, const QString &error);

private:
    Ui::ServiceForm *ui;
    ServiceBridge   *m_bridge;
};
