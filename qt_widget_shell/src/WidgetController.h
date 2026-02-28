/**
 * @file WidgetController.h
 * @brief Manages dynamic .ui loading/unloading and auto-wiring for the Widget Shell.
 *
 * WidgetController uses QUiLoader to load .ui files at runtime from XML source.
 * Buttons are auto-wired to ServiceBridge calls using dynamic properties set
 * in Qt Designer:
 *
 *   - serviceMethod: Method name to call (e.g., "svc_api_hello")
 *   - serviceArgs:   Comma-separated objectNames of input widgets
 *
 * Response text is routed to a QLabel with objectName "resultLabel".
 */

#pragma once

#include <QObject>
#include <QWidget>
#include <QPointer>

class ServiceBridge;

class WidgetController : public QObject
{
    Q_OBJECT

public:
    explicit WidgetController(QWidget *rootContainer, ServiceBridge *bridge,
                               QObject *parent = nullptr);

    static WidgetController *instance();

    /**
     * Load a .ui form from XML source into the root container.
     * Clears any previously loaded UI first, then auto-wires buttons.
     *
     * @param uiXml  The .ui XML source (from Qt Designer).
     */
    void loadUiSource(const QByteArray &uiXml);

    /**
     * Remove the currently loaded widget and destroy it.
     */
    void clearUi();

signals:
    void uiReady();
    void uiError(const QString &errorString);

private:
    /**
     * Find all QPushButton children with serviceMethod/serviceArgs
     * dynamic properties and connect their clicked() signal to
     * ServiceBridge::callService().
     */
    void wireButtons();

    /**
     * Extract the current text/value from a widget by objectName,
     * using a qobject_cast cascade (QLineEdit, QSpinBox, QDoubleSpinBox,
     * QComboBox, QCheckBox).
     */
    QString extractWidgetValue(QWidget *widget) const;

    static WidgetController *s_instance;

    QWidget        *m_rootContainer = nullptr;
    ServiceBridge  *m_bridge = nullptr;
    QPointer<QWidget> m_currentWidget;
};
