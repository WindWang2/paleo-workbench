#include <pwb/ui_seqviz/qt/dialogs.hpp>

#include <pwb/ui_seqviz/page_tokens.hpp>

#include <QComboBox>
#include <QDialogButtonBox>
#include <QDoubleSpinBox>
#include <QLabel>
#include <QLineEdit>
#include <QPushButton>
#include <QTextBrowser>
#include <QVBoxLayout>

namespace pwb::ui_seqviz::qt {

// ---------------------------------------------------------------------------
// LithologyCrossplotDialog
// ---------------------------------------------------------------------------

LithologyCrossplotDialog::LithologyCrossplotDialog(
    const LithologyAnalysisSlice& analysis_result,
    const LithologyPalette& palette, QWidget* parent)
    : ui_widgets::PwbDialog("岩相/波阻抗-伽马交会图分析 (Lithology Crossplot)",
                          parent) {
    resize(560, 520);

    auto* header =
        new QLabel("井数据波阻抗 (AI) vs 自然伽马 (GR) 岩相交会图分析", this);
    header->setObjectName("PwbSectionHeader");
    add_content(header);

    browser_ = new QTextBrowser(this);
    add_content(browser_, 1);
    browser_->setHtml(QString::fromStdString(
        lithology_report_html(analysis_result, palette)));

    auto* btn_close = new QPushButton("关闭", this);
    btn_close->setObjectName("PrimaryButton");
    connect(btn_close, &QPushButton::clicked, this,
            &LithologyCrossplotDialog::accept);
    add_content_spacing(tokens::SPACE_2);  // tokens.SPACE_M parity
    add_content(btn_close);
}

// ---------------------------------------------------------------------------
// CurveOperationDialog
// ---------------------------------------------------------------------------

CurveOperationDialog::CurveOperationDialog(std::string version_id,
                                           QWidget* parent)
    : QDialog(parent), version_id_(std::move(version_id)) {
    setWindowTitle("曲线处理工具箱 → 派生版本");

    auto* root = new QVBoxLayout(this);
    auto* form = new QFormLayout();
    root->addLayout(form);

    operation_combo_ = new QComboBox(this);
    for (const auto& [op_id, label] : operation_combo_entries()) {
        operation_combo_->addItem(QString::fromStdString(label),
                                  QString::fromStdString(op_id));
    }
    connect(operation_combo_, &QComboBox::currentIndexChanged, this,
            [this](int) { rebuild_parameter_rows(); });
    form->addRow("操作", operation_combo_);

    curve_edit_ = new QLineEdit("GR", this);
    curve_edit_->setToolTip(
        "曲线助记符（如 GR / RT / DEN）；文件级操作忽略此项");
    form->addRow("曲线", curve_edit_);

    param_host_ = new QWidget(this);
    param_form_ = new QFormLayout(param_host_);
    param_form_->setContentsMargins(0, 0, 0, 0);
    form->addRow(param_host_);

    auto* diag_button =
        new QPushButton("缺失区间诊断（只读，不产生版本）", this);
    connect(diag_button, &QPushButton::clicked, this,
            [this] { run_diagnostics(); });
    form->addRow("", diag_button);

    auto* buttons = new QDialogButtonBox(
        QDialogButtonBox::Ok | QDialogButtonBox::Cancel, this);
    connect(buttons, &QDialogButtonBox::accepted, this,
            &CurveOperationDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, this,
            &CurveOperationDialog::reject);
    root->addWidget(buttons);

    rebuild_parameter_rows();
}

void CurveOperationDialog::set_curve_reader(CurveReadFn read_fn) {
    read_fn_ = std::move(read_fn);
}

void CurveOperationDialog::set_apply_fn(ApplyFn apply_fn) {
    apply_fn_ = std::move(apply_fn);
}

std::string CurveOperationDialog::operation() const {
    return operation_combo_->currentData().toString().toStdString();
}

std::string CurveOperationDialog::curve() const {
    const QString text = curve_edit_->text().trimmed();
    return text.isEmpty() ? "GR" : text.toStdString();
}

QWidget* CurveOperationDialog::make_editor(const ParamRowDesc& desc) {
    switch (desc.kind) {
    case ParamEditorKind::Spin: {
        auto* box = new QDoubleSpinBox(param_host_);
        box->setDecimals(desc.decimals);
        box->setRange(desc.minimum, desc.maximum);
        box->setValue(desc.value);
        if (!desc.suffix.empty()) {
            box->setSuffix(QString::fromStdString(desc.suffix));
        }
        if (desc.name == "percentile") {
            box->setToolTip(
                "对称百分位带 [p, 100-p]；留空界限则用百分位");
        }
        return box;
    }
    case ParamEditorKind::Combo: {
        auto* combo = new QComboBox(param_host_);
        for (const auto& [label, data] : desc.choices) {
            combo->addItem(QString::fromStdString(label),
                           QString::fromStdString(data));
        }
        return combo;
    }
    case ParamEditorKind::Hint: {
        auto* hint = new QLabel(QString::fromStdString(desc.text),
                                param_host_);
        hint->setObjectName("SecondaryLabel");
        return hint;
    }
    case ParamEditorKind::Line:
    default: {
        auto* edit =
            new QLineEdit(QString::fromStdString(desc.text), param_host_);
        if (desc.name == "expression") {
            edit->setToolTip(
                "受控表达式：曲线名 + 四则运算 + "
                "min/max/log/sqrt/where/clip 等白名单函数");
        }
        return edit;
    }
    }
}

void CurveOperationDialog::rebuild_parameter_rows() {
    while (param_form_->count()) {
        QLayoutItem* item = param_form_->takeAt(0);
        if (QWidget* widget = item->widget()) {
            widget->deleteLater();
        }
        delete item;
    }
    rows_.clear();

    const std::string op = operation();
    const CurveFieldState state = curve_field_state(op);
    curve_edit_->setEnabled(state.enabled);
    curve_edit_->setToolTip(QString::fromStdString(state.tooltip));

    for (const auto& desc : parameter_rows(op)) {
        QWidget* editor = make_editor(desc);
        rows_.emplace_back(desc, editor);
        param_form_->addRow(QString::fromStdString(desc.label), editor);
    }
}

ParamValue CurveOperationDialog::editor_value(const QString& name,
                                            QWidget* editor) const {
    if (auto* spin = qobject_cast<QDoubleSpinBox*>(editor)) {
        return spin->value();
    }
    if (auto* combo = qobject_cast<QComboBox*>(editor)) {
        return combo->currentData().toString().toStdString();
    }
    if (auto* edit = qobject_cast<QLineEdit*>(editor)) {
        return edit->text().trimmed().toStdString();
    }
    return std::string{};
}

domain::Json CurveOperationDialog::collect_parameters() const {
    std::vector<ParamRowDesc> descs;
    std::map<std::string, ParamValue> values;
    descs.reserve(rows_.size());
    for (const auto& [desc, editor] : rows_) {
        descs.push_back(desc);
        values[desc.name] =
            editor_value(QString::fromStdString(desc.name), editor);
    }
    return ui_seqviz::collect_parameters(descs, values);
}

DiagnosticsOutcome CurveOperationDialog::run_diagnostics() {
    const DiagnosticsOutcome outcome =
        ui_seqviz::run_diagnostics(read_fn_, version_id_, curve());
    if (outcome.is_error) {
        emit warning_requested(QString::fromStdString(outcome.title),
                               QString::fromStdString(outcome.body));
    } else {
        emit info_requested(QString::fromStdString(outcome.title),
                            QString::fromStdString(outcome.body));
    }
    return outcome;
}

bool CurveOperationDialog::apply_and_collect() {
    if (!apply_fn_) {
        emit warning_requested(
            "曲线处理", QString::fromStdString(derived_version_failure_text(
                            "apply seam 未配置")));
        return false;
    }
    try {
        const domain::Json result =
            apply_fn_(version_id_, operation(), curve(),
                      collect_parameters());
        const std::string op =
            result.value("operation", operation());
        const auto inputs = result.value("input_version_ids",
                                         std::vector<std::string>{});
        const std::string input_id =
            inputs.empty() ? version_id_ : inputs.front();
        output_version_id =
            result.value("output_version_id", std::string{});
        const std::string run_id =
            result.value("run_id", std::string{});
        emit info_requested(
            "曲线处理",
            QString::fromStdString(derived_version_success_text(
                op, input_id, output_version_id, run_id)));
        return true;
    } catch (const std::exception& exc) {
        emit warning_requested(
            "曲线处理", QString::fromStdString(
                            derived_version_failure_text(exc.what())));
        return false;
    }
}

}  // namespace pwb::ui_seqviz::qt
