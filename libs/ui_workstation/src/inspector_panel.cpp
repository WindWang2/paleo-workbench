#include "pwb/ui_workstation/inspector_panel.hpp"

#include <QLineEdit>
#include <QVBoxLayout>

namespace pwb::ui_workstation {

namespace {

QWidget* form_page(QFormLayout** form_out, QWidget* parent) {
    auto* page = new QWidget(parent);
    auto* form = new QFormLayout(page);
    form->setContentsMargins(8, 8, 8, 8);
    form->setHorizontalSpacing(8);
    form->setVerticalSpacing(5);
    form->setFieldGrowthPolicy(
        QFormLayout::FieldGrowthPolicy::AllNonFixedFieldsGrow);
    *form_out = form;
    return page;
}

// Python _readonly: missing → "—" text + missing property for styling.
QLineEdit* readonly_edit(const std::string& value, QWidget* parent) {
    const bool missing = inspector_value_missing(value);
    auto* edit = new QLineEdit(
        QString::fromStdString(missing ? "—" : value), parent);
    edit->setReadOnly(true);
    edit->setObjectName("WorkstationInspectorValue");
    edit->setProperty("missing", missing);
    return edit;
}

}  // namespace

WorkstationInspector::WorkstationInspector(QWidget* parent)
    : QFrame(parent) {
    setObjectName("WorkstationInspector");
    // V9: 280 → 220 constraint convergence; narrower shrinks the dock.
    setMinimumWidth(220);

    auto* outer = new QVBoxLayout(this);
    outer->setContentsMargins(0, 0, 0, 0);
    outer->setSpacing(0);

    header_ = new QLabel("检查器", this);
    header_->setObjectName("WorkstationInspectorHeader");
    outer->addWidget(header_);

    tabs_ = new QTabWidget(this);
    tabs_->setObjectName("WorkstationInspectorTabs");
    outer->addWidget(tabs_, 1);

    QWidget* props = form_page(&properties_form_, this);
    QWidget* interp = form_page(&interpretation_form_, this);
    tabs_->addTab(props, "属性");
    tabs_->addTab(interp, "解释");

    auto* style_page = new QWidget(this);
    auto* style_layout = new QVBoxLayout(style_page);
    style_layout->setContentsMargins(8, 8, 8, 8);
    style_layout->setSpacing(6);
    style_summary_ = new QLabel(style_page);
    style_summary_->setObjectName("WorkstationAgentConsent");
    style_summary_->setWordWrap(true);
    style_layout->addWidget(style_summary_);
    style_layout->addStretch(1);
    style_edit_button_ =
        new QPushButton("在图层属性中编辑样式…", style_page);
    style_edit_button_->setObjectName("SecondaryButton");
    style_edit_button_->setVisible(false);
    connect(style_edit_button_, &QPushButton::clicked, this, [this] {
        if (!style_layer_id_.empty()) {
            emit edit_style_requested(
                QString::fromStdString(style_layer_id_));
        }
    });
    style_layout->addWidget(style_edit_button_, 0,
                            Qt::AlignmentFlag::AlignLeft);
    tabs_->addTab(style_page, "样式");

    auto* history_page = new QWidget(this);
    auto* history_layout = new QVBoxLayout(history_page);
    history_layout->setContentsMargins(8, 8, 8, 8);
    history_list_ = new QListWidget(history_page);
    history_layout->addWidget(history_list_);
    tabs_->addTab(history_page, "历史");

    show_empty();
}

void WorkstationInspector::set_target_horizon(
    const std::string& horizon) {
    target_horizon_ = horizon;
}

void WorkstationInspector::set_seam_rows(
    std::vector<std::pair<std::string, std::string>> rows) {
    seam_rows_ = std::move(rows);
}

void WorkstationInspector::clear_form(QFormLayout* form) {
    while (form->rowCount() > 0) {
        form->removeRow(0);
    }
    assign_button_ = nullptr;  // deleted with the row's widget
}

void WorkstationInspector::fill_form(
    QFormLayout* form,
    const std::vector<std::pair<std::string, std::string>>& rows) {
    for (const auto& [label, value] : rows) {
        form->addRow(QString::fromStdString(label),
                     readonly_edit(value, this));
    }
}

void WorkstationInspector::show_payload(
    const InspectorPayload& payload) {
    current_payload_ = payload;
    // V6 §6 seam rows ride on the payload for layer kinds.
    InspectorPayload effective = payload;
    if (effective.seam_rows.empty()) effective.seam_rows = seam_rows_;
    render(build_inspector_document(effective, target_horizon_));
}

void WorkstationInspector::show_empty() {
    current_payload_ = InspectorPayload{};
    render(empty_inspector_document());
}

void WorkstationInspector::render(const InspectorDocument& doc) {
    header_->setText(QString::fromStdString(doc.header));
    clear_form(properties_form_);
    clear_form(interpretation_form_);
    fill_form(properties_form_, doc.properties_rows);
    fill_form(interpretation_form_, doc.interpretation_rows);

    if (doc.feature_assign_button) {
        assign_button_ = new QPushButton("指定相带…", this);
        assign_button_->setObjectName("SecondaryButton");
        connect(assign_button_, &QPushButton::clicked, this, [this] {
            QVariantMap payload;
            payload.insert("kind",
                           QString::fromStdString(current_payload_.kind));
            for (const auto& [k, v] : current_payload_.fields) {
                payload.insert(QString::fromStdString(k),
                               QString::fromStdString(v));
            }
            payload.insert("object",
                           QVariant::fromValue(reinterpret_cast<quintptr>(
                               current_payload_.object)));
            emit assign_facies_requested(payload);
        });
        interpretation_form_->addRow("相带", assign_button_);
    }

    style_summary_->setText(QString::fromStdString(doc.style_summary));
    style_edit_button_->setVisible(doc.style_edit_visible);
    style_layer_id_ = doc.style_edit_layer_id;

    history_list_->clear();
    for (const auto& row : doc.history_rows) {
        history_list_->addItem(QString::fromStdString(row));
    }
}

}  // namespace pwb::ui_workstation
