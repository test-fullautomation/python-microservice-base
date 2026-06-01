/**
 * @file MainWidget.h
 * @brief Main UI widget for the Cleware USB Switch Box controller (WASM).
 *
 * Provides Switch Box (8 toggle LEDs) and Multiplexer (2×4 matrix) views.
 */

#pragma once

#include <QWidget>
#include <QJsonObject>
#include <QPushButton>
#include <vector>

namespace Ui { class ServiceForm; }

class ServiceBridge;

class MainWidget : public QWidget
{
    Q_OBJECT

public:
    explicit MainWidget(QWidget *parent = nullptr);
    ~MainWidget();

private slots:
    void onInitClicked();
    void onTypeChanged(int index);

    // Switch Box
    void onSwitchToggled(int index);
    void onAllOn();
    void onAllOff();
    void onRefresh();

    // Multiplexer
    void onMuxInClicked(int index);
    void onMuxOutClicked(int index);
    void onMuxRefresh();

    // Bridge responses
    void onResponse(const QString &method, const QString &result);
    void onError(const QString &method, const QString &error);

private:
    void updateSwitchUI();
    void updateMuxUI();
    void setSwitch(int switchIndex, const QString &state);

    Ui::ServiceForm *ui;
    ServiceBridge   *m_bridge;

    // Current state
    QString                          m_currentDevice;
    QJsonObject                      m_devicesState;  // { "serial": { "0": 0, ... } }
    std::vector<QPushButton*>        m_switchButtons; // sw0..sw7
    std::vector<QPushButton*>        m_inButtons;     // in1, in2
    std::vector<QPushButton*>        m_outButtons;    // out1..out4
};
