#include "MainWindow.h"
#include "ui_MainWindow.h"

#include <grpcpp/grpcpp.h>

#include <QCheckBox>
#include <QComboBox>
#include <QDoubleSpinBox>
#include <QFormLayout>
#include <QLabel>
#include <QLineEdit>
#include <QPushButton>
#include <QSpinBox>
#include <QTimer>

#include <climits>

namespace {

// Build an input widget matching a proto scalar type.
QWidget* makeWidgetFor(const QString& type, QWidget* parent) {
    if (type == "string" || type == "bytes") {
        return new QLineEdit(parent);
    }
    if (type == "int32" || type == "int" || type == "uint32" || type == "int64" || type == "uint64") {
        auto* s = new QSpinBox(parent);
        s->setRange(INT_MIN, INT_MAX);
        return s;
    }
    if (type == "float" || type == "double") {
        auto* s = new QDoubleSpinBox(parent);
        s->setRange(-1e12, 1e12);
        s->setDecimals(6);
        return s;
    }
    if (type == "bool") {
        return new QCheckBox(parent);
    }
    return new QLineEdit(parent);  // fallback
}

}  // namespace

MainWindow::MainWindow(QWidget *parent)
    : QWidget(parent), ui(new Ui::MainWindow) {
    ui->setupUi(this);

    m_form = new QFormLayout(ui->formContainer);
    m_form->setContentsMargins(6, 6, 6, 6);

    buildMethodBindings();
    for (const auto& m : m_methods) {
        ui->methodCombo->addItem(m.name);
    }

    connect(ui->methodCombo,
            QOverload<int>::of(&QComboBox::currentIndexChanged),
            this, &MainWindow::onMethodChanged);
    connect(ui->sendButton, &QPushButton::clicked,
            this, &MainWindow::onSend);

    if (!m_methods.empty()) {
        rebuildForm(0);
    }

    // Defer the Consul lookup until after the event loop starts so the
    // window paints immediately even if Consul is slow/unreachable.
    QTimer::singleShot(0, this, [this]() {
        ui->outputTextEdit->append("Resolving test_service via Consul...");
        try {
            m_client = std::make_unique<
                microservice_base::ServiceClient<test_service::v1::TestServiceService>>("test_service");
            const QString tgt = QString::fromStdString(m_client->target());
            ui->outputTextEdit->append(tgt.isEmpty()
                ? QString("[warn] Consul returned no healthy instance.")
                : QString("Connected to %1").arg(tgt));
        } catch (const std::exception& e) {
            ui->outputTextEdit->append(
                QString("Connection failed: %1").arg(e.what()));
        }
    });
}

MainWindow::~MainWindow() {
    delete ui;
}

void MainWindow::onMethodChanged(int idx) {
    rebuildForm(idx);
}

void MainWindow::rebuildForm(int idx) {
    while (m_form->rowCount() > 0) {
        m_form->removeRow(0);
    }
    m_currentWidgets.clear();

    if (idx < 0 || idx >= static_cast<int>(m_methods.size())) return;

    const auto& b = m_methods[idx];
    for (const auto& p : b.params) {
        QWidget* w = makeWidgetFor(p.type, ui->formContainer);
        m_form->addRow(p.name + " (" + p.type + "):", w);
        m_currentWidgets.push_back(w);
    }
    if (b.params.empty()) {
        m_form->addRow(new QLabel("(no parameters)", ui->formContainer));
    }
}

void MainWindow::onSend() {
    int idx = ui->methodCombo->currentIndex();
    if (idx < 0 || idx >= static_cast<int>(m_methods.size())) return;
    if (!m_client) {
        ui->outputTextEdit->append("[not connected]");
        return;
    }
    const auto& b = m_methods[idx];
    ui->outputTextEdit->append(QString(">> %1").arg(b.name));
    QString out = b.invoke(m_currentWidgets);
    ui->outputTextEdit->append(out);
}

void MainWindow::buildMethodBindings() {
    // --- Echo(message: string) -> string ---
    {
        MethodBinding b;
        b.name = "Echo";
        b.params = { {"message", "string"} };
        b.invoke = [this](const std::vector<QWidget*>& ws) -> QString {
            grpc::ClientContext ctx;
            test_service::v1::EchoRequest req;
            req.set_message(qobject_cast<QLineEdit*>(ws[0])->text().toStdString());
            test_service::v1::EchoResponse resp;
            auto st = m_client->stub().Echo(&ctx, req, &resp);
            if (!st.ok()) {
                return QString("[error] ") + QString::fromStdString(st.error_message());
            }
            return QString::fromStdString(resp.result());
        };
        m_methods.push_back(std::move(b));
    }

    // --- Add(a: int32, b: int32) -> int32 ---
    {
        MethodBinding b;
        b.name = "Add";
        b.params = { {"a", "int32"}, {"b", "int32"} };
        b.invoke = [this](const std::vector<QWidget*>& ws) -> QString {
            grpc::ClientContext ctx;
            test_service::v1::AddRequest req;
            req.set_a(qobject_cast<QSpinBox*>(ws[0])->value());
            req.set_b(qobject_cast<QSpinBox*>(ws[1])->value());
            test_service::v1::AddResponse resp;
            auto st = m_client->stub().Add(&ctx, req, &resp);
            if (!st.ok()) {
                return QString("[error] ") + QString::fromStdString(st.error_message());
            }
            return QString::number(resp.result());
        };
        m_methods.push_back(std::move(b));
    }
}
