/**
 * @file MainWidget.cpp
 * @brief Implementation of the Cleware WASM widget.
 */

#include "MainWidget.h"
#include "ui_ServiceUI.h"
#include "ServiceBridge.h"

#include <QJsonDocument>
#include <QJsonArray>

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

    // Collect switch buttons
    m_switchButtons = {
        ui->sw0, ui->sw1, ui->sw2, ui->sw3,
        ui->sw4, ui->sw5, ui->sw6, ui->sw7
    };

    // Collect multiplexer buttons
    m_inButtons  = { ui->in1, ui->in2 };
    m_outButtons = { ui->out1, ui->out2, ui->out3, ui->out4 };

    // Connect device config
    connect(ui->initButton, &QPushButton::clicked,
            this, &MainWidget::onInitClicked);
    connect(ui->typeCombo, QOverload<int>::of(&QComboBox::currentIndexChanged),
            this, &MainWidget::onTypeChanged);

    // Connect switch buttons — use lambda to pass index
    for (int i = 0; i < 8; ++i) {
        connect(m_switchButtons[i], &QPushButton::clicked, this,
                [this, i]() { onSwitchToggled(i); });
    }

    connect(ui->allOnButton,  &QPushButton::clicked, this, &MainWidget::onAllOn);
    connect(ui->allOffButton, &QPushButton::clicked, this, &MainWidget::onAllOff);
    connect(ui->refreshButton, &QPushButton::clicked, this, &MainWidget::onRefresh);

    // Connect multiplexer buttons
    for (int i = 0; i < 2; ++i) {
        connect(m_inButtons[i], &QPushButton::clicked, this,
                [this, i]() { onMuxInClicked(i); });
    }
    for (int i = 0; i < 4; ++i) {
        connect(m_outButtons[i], &QPushButton::clicked, this,
                [this, i]() { onMuxOutClicked(i); });
    }

    connect(ui->muxRefreshButton, &QPushButton::clicked,
            this, &MainWidget::onMuxRefresh);

    // Default to Switch Box view (page 0)
    ui->viewStack->setCurrentIndex(0);
}

MainWidget::~MainWidget()
{
    delete ui;
}

// ---------------------------------------------------------------------------
// Device configuration
// ---------------------------------------------------------------------------

void MainWidget::onInitClicked()
{
    QJsonArray args;
    m_bridge->callService("ServiceCleware", "svc_api_get_all_devices_state", args);
    ui->statusLabel->setText("Scanning for devices...");
}

void MainWidget::onTypeChanged(int index)
{
    ui->viewStack->setCurrentIndex(index);
}

// ---------------------------------------------------------------------------
// Switch Box
// ---------------------------------------------------------------------------

void MainWidget::onSwitchToggled(int index)
{
    if (m_currentDevice.isEmpty()) {
        ui->statusLabel->setText("<b style='color:red;'>No device selected. Click Initialize.</b>");
        ui->statusLabel->setTextFormat(Qt::RichText);
        return;
    }

    // Read current state and toggle
    QJsonObject devState = m_devicesState.value(m_currentDevice).toObject();
    int current = devState.value(QString::number(index)).toInt(0);
    QString newState = (current == 1) ? "off" : "on";
    setSwitch(0x10 + index, newState);
}

void MainWidget::onAllOn()
{
    if (m_currentDevice.isEmpty()) return;
    for (int i = 0; i < 8; ++i)
        setSwitch(0x10 + i, "on");
}

void MainWidget::onAllOff()
{
    if (m_currentDevice.isEmpty()) return;
    for (int i = 0; i < 8; ++i)
        setSwitch(0x10 + i, "off");
}

void MainWidget::onRefresh()
{
    onInitClicked();
}

// ---------------------------------------------------------------------------
// Multiplexer
// ---------------------------------------------------------------------------

void MainWidget::onMuxInClicked(int inPort)
{
    if (m_currentDevice.isEmpty()) return;

    // Find current OUT port
    QJsonObject devState = m_devicesState.value(m_currentDevice).toObject();
    int activeIdx = -1;
    for (int i = 0; i < 8; ++i) {
        if (devState.value(QString::number(i)).toInt(0) == 1) {
            activeIdx = i;
            break;
        }
    }
    int outPort = (activeIdx >= 0) ? (activeIdx % 4) : 0;
    int swIndex = inPort * 4 + outPort;
    setSwitch(0x10 + swIndex, "on");
}

void MainWidget::onMuxOutClicked(int outPort)
{
    if (m_currentDevice.isEmpty()) return;

    // Find current IN port
    QJsonObject devState = m_devicesState.value(m_currentDevice).toObject();
    int activeIdx = -1;
    for (int i = 0; i < 8; ++i) {
        if (devState.value(QString::number(i)).toInt(0) == 1) {
            activeIdx = i;
            break;
        }
    }
    int inPort = (activeIdx >= 0) ? (activeIdx / 4) : 0;
    int swIndex = inPort * 4 + outPort;
    setSwitch(0x10 + swIndex, "on");
}

void MainWidget::onMuxRefresh()
{
    onInitClicked();
}

// ---------------------------------------------------------------------------
// Bridge responses
// ---------------------------------------------------------------------------

void MainWidget::onResponse(const QString &method, const QString &result)
{
    ui->statusLabel->setTextFormat(Qt::RichText);

    if (method == "svc_api_get_all_devices_state") {
        QJsonDocument doc = QJsonDocument::fromJson(result.toUtf8());
        if (!doc.isObject()) {
            ui->statusLabel->setText("Unexpected response: " + result);
            return;
        }

        m_devicesState = doc.object();
        QStringList serials = m_devicesState.keys();

        // Populate device combo
        ui->deviceCombo->blockSignals(true);
        ui->deviceCombo->clear();
        for (const QString &s : serials)
            ui->deviceCombo->addItem(s);
        ui->deviceCombo->blockSignals(false);

        if (!serials.isEmpty()) {
            if (m_currentDevice.isEmpty() || !serials.contains(m_currentDevice)) {
                m_currentDevice = serials.first();
                ui->deviceCombo->setCurrentIndex(0);
            }
            ui->statusLabel->setText(
                QString("Found <b>%1</b> device(s): %2")
                    .arg(serials.size())
                    .arg(serials.join(", ")));
            updateSwitchUI();
            updateMuxUI();
        } else {
            ui->statusLabel->setText("No Cleware devices found.");
        }

    } else if (method == "svc_api_set_switch") {
        ui->statusLabel->setText("Switch set: " + result);
        // Refresh state
        onInitClicked();

    } else {
        ui->statusLabel->setText(QString("<b>%1</b>: %2").arg(method, result));
    }
}

void MainWidget::onError(const QString &method, const QString &error)
{
    ui->statusLabel->setTextFormat(Qt::RichText);
    ui->statusLabel->setText(
        QString("<b style='color:red;'>Error in %1</b>: %2").arg(method, error));
}

// ---------------------------------------------------------------------------
// UI updates
// ---------------------------------------------------------------------------

void MainWidget::updateSwitchUI()
{
    if (m_currentDevice.isEmpty()) return;
    QJsonObject devState = m_devicesState.value(m_currentDevice).toObject();

    for (int i = 0; i < 8; ++i) {
        bool on = devState.value(QString::number(i)).toInt(0) == 1;
        m_switchButtons[i]->blockSignals(true);
        m_switchButtons[i]->setChecked(on);
        m_switchButtons[i]->setStyleSheet(
            on ? "background-color: #4CAF50; color: white; border-radius: 4px;"
               : "background-color: #9E9E9E; color: white; border-radius: 4px;");
        m_switchButtons[i]->blockSignals(false);
    }
}

void MainWidget::updateMuxUI()
{
    if (m_currentDevice.isEmpty()) return;
    QJsonObject devState = m_devicesState.value(m_currentDevice).toObject();

    // Find active switch index (only one ON for multiplexer)
    int activeIdx = -1;
    for (int i = 0; i < 8; ++i) {
        if (devState.value(QString::number(i)).toInt(0) == 1) {
            activeIdx = i;
            break;
        }
    }

    int activeIn  = (activeIdx >= 0) ? (activeIdx / 4) : -1;
    int activeOut = (activeIdx >= 0) ? (activeIdx % 4) : -1;

    // Update IN buttons
    for (int i = 0; i < 2; ++i) {
        bool on = (i == activeIn);
        m_inButtons[i]->blockSignals(true);
        m_inButtons[i]->setChecked(on);
        m_inButtons[i]->setStyleSheet(
            on ? "background-color: #1976D2; color: white; border-radius: 4px;"
               : "");
        m_inButtons[i]->blockSignals(false);
    }

    // Update OUT buttons
    for (int i = 0; i < 4; ++i) {
        bool on = (i == activeOut);
        m_outButtons[i]->blockSignals(true);
        m_outButtons[i]->setChecked(on);
        m_outButtons[i]->setStyleSheet(
            on ? "background-color: #FF9800; color: white; border-radius: 4px;"
               : "");
        m_outButtons[i]->blockSignals(false);
    }

    // Route label
    if (activeIn >= 0 && activeOut >= 0) {
        ui->routeLabel->setText(
            QString("Route: IN %1  →  OUT %2").arg(activeIn + 1).arg(activeOut + 1));
    } else {
        ui->routeLabel->setText("No active route");
    }
}

void MainWidget::setSwitch(int switchId, const QString &state)
{
    QJsonArray args;
    args.append(m_currentDevice);
    args.append(switchId);
    args.append(state);
    m_bridge->callService("ServiceCleware", "svc_api_set_switch", args);
}
