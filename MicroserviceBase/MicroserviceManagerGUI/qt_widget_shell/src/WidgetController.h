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
 *   - serviceResult: objectName of the widget to display the response in
 *                    (optional — falls back to "resultLabel" if not set)
 *
 * Response text is routed per-button to the widget named in serviceResult,
 * or to a shared QLabel with objectName "resultLabel" as the default fallback.
 */

#pragma once

#include <QObject>
#include <QWidget>
#include <QPointer>
#include <QHash>

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
     *
     * Also reads serviceResult property per button to build a
     * method → target widget map for response routing.
     */
    void wireButtons();

    /**
     * Set text and style on a target widget (QLabel, QLineEdit, etc.).
     */
    void setWidgetResult(QWidget *widget, const QString &text, const QString &style) const;

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

    /** method name → objectName of target widget for response routing */
    QHash<QString, QString> m_methodResultMap;
};
