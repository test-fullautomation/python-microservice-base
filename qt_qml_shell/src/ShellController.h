/**
 * @file ShellController.h
 * @brief Manages dynamic QML loading/unloading lifecycle for the shell.
 *
 * ShellController uses QQmlComponent to load .qml files at runtime from URLs.
 * This enables a shared QML Shell WASM binary to host service-specific UIs
 * without recompilation.
 */

#pragma once

#include <QObject>
#include <QQmlEngine>
#include <QQmlComponent>
#include <QQuickItem>
#include <QUrl>
#include <QPointer>

class ShellController : public QObject
{
    Q_OBJECT
    Q_PROPERTY(bool loading READ isLoading NOTIFY loadingChanged)
    Q_PROPERTY(QString errorString READ errorString NOTIFY errorStringChanged)

public:
    explicit ShellController(QQmlEngine *engine, QQuickItem *rootContainer,
                              QObject *parent = nullptr);

    static ShellController *instance();

    bool isLoading() const;
    QString errorString() const;

    /**
     * Load a QML file from a URL into the shell's root container.
     * Any previously loaded QML is cleared first.
     *
     * @param url  The URL of the .qml file to load (HTTP or local).
     */
    Q_INVOKABLE void loadQml(const QUrl &url);

    /**
     * Load QML from source string (for file:// environments like Electron
     * where the WASM Fetch API can't access local files).
     *
     * @param source   The QML source code.
     * @param baseUrl  Base URL for resolving relative imports.
     */
    Q_INVOKABLE void loadQmlSource(const QByteArray &source, const QUrl &baseUrl);

    /**
     * Clear the currently loaded QML component and destroy its item tree.
     */
    Q_INVOKABLE void clearQml();

signals:
    void qmlReady();
    void qmlError(const QString &errorString);
    void loadingChanged();
    void errorStringChanged();

private slots:
    void onComponentStatusChanged(QQmlComponent::Status status);

private:
    static ShellController *s_instance;

    QQmlEngine     *m_engine = nullptr;
    QQuickItem     *m_rootContainer = nullptr;
    QQmlComponent  *m_component = nullptr;
    QPointer<QQuickItem> m_currentItem;
    bool            m_loading = false;
    QString         m_errorString;
};
