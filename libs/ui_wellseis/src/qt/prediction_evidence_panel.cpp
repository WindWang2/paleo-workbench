#include <pwb/ui_wellseis/qt/prediction_evidence_panel.hpp>

#include <QApplication>
#include <QClipboard>
#include <QComboBox>
#include <QLabel>
#include <QListWidget>
#include <QPlainTextEdit>
#include <QProgressBar>
#include <QPushButton>
#include <QVBoxLayout>

#include <pwb/ui_wellseis/output_labels.hpp>

namespace pwb::ui_wellseis::qt {

namespace {

QString qs(const std::string& text) {
    return QString::fromUtf8(text.data(), static_cast<int>(text.size()));
}

}  // namespace

PredictionEvidencePanel::PredictionEvidencePanel(QWidget* parent)
    : QFrame(parent) {
    setObjectName(QStringLiteral("PredictionEvidencePanel"));
    setMinimumWidth(220);
    setMaximumWidth(static_cast<int>(220 * 1.6));

    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(12, 12, 12, 12);
    layout->setSpacing(8);

    auto* title = new QLabel(QStringLiteral("预测证据"), this);
    title->setObjectName(QStringLiteral("MapDockTitle"));
    layout->addWidget(title);

    mock_value_ = add_value(layout, QStringLiteral("输出性质"),
                            QStringLiteral("—"));
    source_value_ = add_value(layout, QStringLiteral("数据来源"),
                              QStringLiteral("—"));
    horizon_value_ = add_value(layout, QStringLiteral("目标层位"),
                               QStringLiteral("—"));
    facies_count_value_ = add_value(layout, QStringLiteral("相带段数"),
                                    QStringLiteral("—"));
    class_distribution_value_ =
        add_value(layout, QStringLiteral("预测相带"), QStringLiteral("—"));
    // Async run outcome landing spot (#897): completions/failures arrive
    // on queued signals and must not open modal dialogs.
    status_value_ =
        add_value(layout, QStringLiteral("状态"), QStringLiteral("—"));
    waiting_label_ =
        new QLabel(QStringLiteral("正在提交并等待线上推理结果…"), this);
    waiting_label_->setObjectName(QStringLiteral("WorkFieldLabel"));
    waiting_label_->setAccessibleName(
        QStringLiteral("线上测井预测等待状态"));
    waiting_label_->hide();
    layout->addWidget(waiting_label_);
    // A 0..0 QProgressBar is Qt's native indeterminate animation.
    waiting_indicator_ = new QProgressBar(this);
    waiting_indicator_->setObjectName(
        QStringLiteral("PredictionWaitIndicator"));
    waiting_indicator_->setRange(0, 0);
    waiting_indicator_->setTextVisible(false);
    waiting_indicator_->setFixedHeight(6);
    waiting_indicator_->setAccessibleName(
        QStringLiteral("线上测井预测进行中"));
    waiting_indicator_->hide();
    layout->addWidget(waiting_indicator_);

    auto* evidence_label =
        new QLabel(QStringLiteral("证据贡献"), this);
    evidence_label->setObjectName(QStringLiteral("WorkFieldLabel"));
    layout->addWidget(evidence_label);
    evidence_list_ = new QListWidget(this);
    evidence_list_->setObjectName(QStringLiteral("WorkListWidget"));
    layout->addWidget(evidence_list_, 1);

    auto* diagnostic_label =
        new QLabel(QStringLiteral("运行日志"), this);
    diagnostic_label->setObjectName(QStringLiteral("WorkFieldLabel"));
    layout->addWidget(diagnostic_label);
    diagnostic_log_ = new QPlainTextEdit(this);
    diagnostic_log_->setObjectName(
        QStringLiteral("PredictionDiagnosticLog"));
    diagnostic_log_->setReadOnly(true);
    diagnostic_log_->setPlaceholderText(QStringLiteral("尚无运行日志"));
    diagnostic_log_->setMinimumHeight(100);
    diagnostic_log_->setMaximumHeight(140);
    diagnostic_log_->setMaximumBlockCount(200);
    layout->addWidget(diagnostic_log_);
    copy_diagnostic_btn_ =
        new QPushButton(QStringLiteral("复制运行日志"), this);
    copy_diagnostic_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    copy_diagnostic_btn_->setEnabled(false);
    connect(copy_diagnostic_btn_, &QPushButton::clicked, this, [this] {
        if (QClipboard* clipboard = QApplication::clipboard()) {
            clipboard->setText(diagnostic_log_->toPlainText());
        }
    });
    layout->addWidget(copy_diagnostic_btn_);

    auto* export_label = new QLabel(QStringLiteral("导出格式"), this);
    export_label->setObjectName(QStringLiteral("WorkFieldLabel"));
    layout->addWidget(export_label);
    export_format_combo_ = new QComboBox(this);
    export_format_combo_->addItems({QStringLiteral("PNG"),
                                    QStringLiteral("SVG"),
                                    QStringLiteral("PDF")});
    layout->addWidget(export_format_combo_);

    export_btn_ =
        new QPushButton(QStringLiteral("导出单井剖面"), this);
    export_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    connect(export_btn_, &QPushButton::clicked, this, [this] {
        emit export_requested(export_format_combo_->currentText());
    });
    layout->addWidget(export_btn_);

    run_btn_ =
        new QPushButton(QStringLiteral("运行线上测井预测"), this);
    run_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    run_btn_->setToolTip(QStringLiteral(
        "将所选井的模型要求曲线记录发送到认证线上单井预测服务；"
        "结果将保存到数据管理"));
    connect(run_btn_, &QPushButton::clicked, this,
            &PredictionEvidencePanel::run_requested);
    layout->addWidget(run_btn_);
    demo_btn_ =
        new QPushButton(QStringLiteral("运行演示预测"), this);
    demo_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    demo_btn_->setToolTip(QStringLiteral(
        "显式演示模式：运行 DemoModelProvider（合成数据，非科学预测）"));
    connect(demo_btn_, &QPushButton::clicked, this,
            &PredictionEvidencePanel::demo_requested);
    layout->addWidget(demo_btn_);
    send_btn_ = new QPushButton(QStringLiteral("发送制备"), this);
    send_btn_->setObjectName(QStringLiteral("PrimaryButton"));
    connect(send_btn_, &QPushButton::clicked, this,
            &PredictionEvidencePanel::send_requested);
    layout->addWidget(send_btn_);
}

QLabel* PredictionEvidencePanel::add_value(QVBoxLayout* layout,
                                           const QString& label_text,
                                           const QString& value_text) {
    auto* label = new QLabel(label_text, this);
    label->setObjectName(QStringLiteral("WorkFieldLabel"));
    layout->addWidget(label);
    auto* value = new QLabel(value_text, this);
    value->setObjectName(QStringLiteral("WorkFieldValue"));
    layout->addWidget(value);
    return value;
}

void PredictionEvidencePanel::set_actions_enabled(bool can_export,
                                                  bool can_send) {
    export_btn_->setEnabled(can_export);
    send_btn_->setEnabled(can_send);
    // #850-7: while an inference runs the run/demo actions stay disabled
    // instead of silently swallowing a second click.
    run_btn_->setEnabled(!inferring_);
    demo_btn_->setEnabled(!inferring_);
}

void PredictionEvidencePanel::set_inferring(bool busy) {
    inferring_ = busy;
    run_btn_->setEnabled(!inferring_);
    demo_btn_->setEnabled(!inferring_);
    waiting_label_->setVisible(inferring_);
    waiting_indicator_->setVisible(inferring_);
    if (busy) {
        status_value_->setText(QStringLiteral("推断中…"));
    }
}

void PredictionEvidencePanel::set_status(const QString& text) {
    status_value_->setText(text);
}

QString PredictionEvidencePanel::status_text() const {
    return status_value_->text();
}

void PredictionEvidencePanel::set_diagnostic_log(const QString& text) {
    const QString value = text.trimmed();
    diagnostic_log_->setPlainText(value);
    copy_diagnostic_btn_->setEnabled(!value.isEmpty());
}

void PredictionEvidencePanel::update_state(
    const PredictionTaskSlice* task, bool bound_las,
    bool selected_source) {
    if (task == nullptr) {
        mock_value_->setText(QStringLiteral("—"));
        source_value_->setText(selected_source
                                   ? QStringLiteral("数据管理井数据")
                                   : QStringLiteral("—"));
        horizon_value_->setText(QStringLiteral("—"));
        facies_count_value_->setText(QStringLiteral("—"));
        class_distribution_value_->setText(QStringLiteral("—"));
        class_distribution_value_->setToolTip(QString());
        evidence_list_->clear();
        set_actions_enabled(/*can_export=*/selected_source && bound_las,
                            /*can_send=*/false);
        return;
    }
    // Honest output labeling (P2) — all label math lives in the core.
    mock_value_->setText(qs(well_log_output_nature(task->result_summary)));
    source_value_->setText(
        qs(prediction_source_label(task->result_summary, bound_las)));
    const std::string horizon =
        target_horizon_of(task->model_metadata, task->result_summary);
    horizon_value_->setText(horizon.empty() ? QStringLiteral("—")
                                            : qs(horizon));
    facies_count_value_->setText(
        QString::number(predicted_region_count(task->result_summary)));
    const ClassDistribution dist =
        class_distribution_of(task->result_summary);
    if (!dist.text.empty()) {
        class_distribution_value_->setText(qs(dist.text));
        class_distribution_value_->setToolTip(qs(dist.tooltip));
    } else {
        class_distribution_value_->setText(QStringLiteral("—"));
        class_distribution_value_->setToolTip(QString());
    }
    evidence_list_->clear();
    for (const auto& row : evidence_rows(task->evidence_contribution)) {
        evidence_list_->addItem(qs(row));
    }
    set_actions_enabled(/*can_export=*/true, /*can_send=*/true);
}

}  // namespace pwb::ui_wellseis::qt
