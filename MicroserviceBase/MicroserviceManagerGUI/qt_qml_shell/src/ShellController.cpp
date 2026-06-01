/**
 * @file ShellController.cpp
 * @brief Implementation of dynamic QML loading/unloading for the shell.
 */

#include "ShellController.h"

#include <QQmlContext>
#include <QDebug>

ShellController *ShellController::s_instance = nullptr;

ShellController::ShellController(QQmlEngine *engine, QQuickItem *rootContainer,
                                  QObject *parent)
    : QObject(parent)
    , m_engine(engine)
    , m_rootContainer(rootContainer)
{
    s_instance = this;
}

ShellController *ShellController::instance()
{
    return s_instance;
}

bool ShellController::isLoading() const
{
    return m_loading;
}

QString ShellController::errorString() const
{
    return m_errorString;
}

void ShellController::loadQml(const QUrl &url)
{
    // Clear any existing content.
    clearQml();

    m_loading = true;
    emit loadingChanged();

    m_errorString.clear();
    emit errorStringChanged();

    // Create a new component to load the URL asynchronously.
    m_component = new QQmlComponent(m_engine, this);

    connect(m_component, &QQmlComponent::statusChanged,
            this, &ShellController::onComponentStatusChanged);

    // Load asynchronously — this allows fetching .qml over HTTP in WASM.
    m_component->loadUrl(url, QQmlComponent::Asynchronous);
}

void ShellController::loadQmlSource(const QByteArray &source, const QUrl &baseUrl)
{
    clearQml();

    m_loading = true;
    emit loadingChanged();

    m_errorString.clear();
    emit errorStringChanged();

    m_component = new QQmlComponent(m_engine, this);

    connect(m_component, &QQmlComponent::statusChanged,
            this, &ShellController::onComponentStatusChanged);

    m_component->setData(source, baseUrl);
}

void ShellController::clearQml()
{
    if (m_currentItem) {
        m_currentItem->setParentItem(nullptr);
        m_currentItem->deleteLater();
        m_currentItem = nullptr;
    }

    if (m_component) {
        m_component->deleteLater();
        m_component = nullptr;
    }

    m_loading = false;
    emit loadingChanged();
}

void ShellController::onComponentStatusChanged(QQmlComponent::Status status)
{
    if (status == QQmlComponent::Loading) {
        return; // Still loading, wait.
    }

    m_loading = false;
    emit loadingChanged();

    if (status == QQmlComponent::Error) {
        QStringList errors;
        for (const auto &err : m_component->errors()) {
            errors.append(err.toString());
        }
        m_errorString = errors.join("\n");
        emit errorStringChanged();
        emit qmlError(m_errorString);

        qWarning() << "ShellController: QML load error:" << m_errorString;
        return;
    }

    if (status == QQmlComponent::Ready) {
        // Create the object from the loaded component.
        QObject *obj = m_component->create(m_engine->rootContext());
        if (!obj) {
            m_errorString = "Failed to create QML object from component";
            emit errorStringChanged();
            emit qmlError(m_errorString);
            return;
        }

        // Try to parent as a QQuickItem into the root container.
        QQuickItem *item = qobject_cast<QQuickItem *>(obj);
        if (item && m_rootContainer) {
            item->setParentItem(m_rootContainer);

            // Fill the container.
            item->setWidth(m_rootContainer->width());
            item->setHeight(m_rootContainer->height());

            // Bind size to container.
            connect(m_rootContainer, &QQuickItem::widthChanged, item, [this, item]() {
                if (m_rootContainer) item->setWidth(m_rootContainer->width());
            });
            connect(m_rootContainer, &QQuickItem::heightChanged, item, [this, item]() {
                if (m_rootContainer) item->setHeight(m_rootContainer->height());
            });

            m_currentItem = item;
        } else {
            // Object is not a visual item — still keep it alive.
            obj->setParent(this);
        }

        emit qmlReady();
    }
}
