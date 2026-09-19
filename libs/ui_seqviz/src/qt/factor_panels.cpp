#include <pwb/ui_seqviz/qt/factor_panels.hpp>

#include <QCheckBox>
#include <QComboBox>
#include <QFormLayout>
#include <QGridLayout>
#include <QGroupBox>
#include <QHBoxLayout>
#include <QMouseEvent>
#include <QProgressBar>
#include <QPushButton>
#include <QScrollArea>
#include <QSpinBox>
#include <QVBoxLayout>

#include <pwb/job_runtime/job_scheduler.hpp>
#include <pwb/ui_seqviz/page_tokens.hpp>
#include <pwb/ui_widgets/badges.hpp>

namespace pwb::ui_seqviz::qt {

namespace {

QLabel* secondary_label(const QString& text, QWidget* parent) {
    auto* label = new QLabel(text, parent);
    label->setObjectName("SecondaryLabel");
    return label;
}

}  // namespace

// ---------------------------------------------------------------------------
// FactorTaskPanel::Row
// ---------------------------------------------------------------------------

FactorTaskPanel::Row::Row(const FactorTaskRecord& task, QWidget* parent)
    : QWidget(parent) {
    setObjectName("FactorTaskRow");
    auto* layout = new QHBoxLayout(this);
    layout->setContentsMargins(tokens::SPACE_1, tokens::SPACE_2,
                             tokens::SPACE_1, tokens::SPACE_2);
    layout->setSpacing(tokens::SPACE_2);

    auto* text_box = new QVBoxLayout();
    text_box->setSpacing(tokens::SPACE_1);
    text_box->setContentsMargins(0, 0, 0, 0);
    name_label_ = new QLabel(QString::fromStdString(task.name), this);
    name_label_->setObjectName("FactorTaskName");
    sub_label_ = new QLabel(
        QString::fromStdString(factor_task_sub_label(task)), this);
    sub_label_->setObjectName("FactorTaskSub");
    text_box->addWidget(name_label_);
    text_box->addWidget(sub_label_);
    auto* wrap = new QWidget(this);
    wrap->setLayout(text_box);
    layout->addWidget(wrap, 1);

    const StateToken token = factor_task_badge_token(task.status);
    layout->addWidget(new ui_widgets::PwbBadge(
        QString::fromStdString(token.label),
        QString::fromStdString(tone_to_badge(token.tone)), this));
}

// ---------------------------------------------------------------------------
// FactorTaskPanel
// ---------------------------------------------------------------------------

FactorTaskPanel::FactorTaskPanel(QWidget* parent) : QFrame(parent) {
    setObjectName("FactorTaskPanel");
    auto* outer = new QVBoxLayout(this);
    const int pad = tokens::PANEL_PADDING;
    outer->setContentsMargins(pad, pad, pad, pad);
    outer->setSpacing(tokens::SPACE_2);

    auto* header = new QHBoxLayout();
    header->setSpacing(tokens::SPACE_2);
    horizon_label_ = new QLabel("层位: —", this);
    horizon_label_->setObjectName("MapDockTitle");
    header->addWidget(horizon_label_);
    header->addStretch();

    method_combo_ = new QComboBox(this);
    for (const auto& label : tokens::interpolation_methods()) {
        method_combo_->addItem(QString::fromStdString(label));
    }
    const auto& tooltips = tokens::interpolation_method_tooltips();
    const auto& methods = tokens::interpolation_methods();
    for (int i = 0; i < method_combo_->count(); ++i) {
        const auto it =
            tooltips.find(methods.at(static_cast<std::size_t>(i)));
        if (it != tooltips.end()) {
            method_combo_->setItemData(
                i, QString::fromStdString(it->second),
                Qt::ToolTipRole);
        }
    }
    sync_method_tooltip(method_combo_->currentText());
    connect(method_combo_, &QComboBox::currentTextChanged, this,
            &FactorTaskPanel::sync_method_tooltip);
    connect(method_combo_, &QComboBox::activated, this,
            [this](int) { method_user_selected_ = true; });
    header->addWidget(method_combo_);
    outer->addLayout(header);

    generate_btn_ = new QPushButton("批量生成单因素图", this);
    generate_btn_->setObjectName("PrimaryButton");
    connect(generate_btn_, &QPushButton::clicked, this, [this] {
        emit generate_requested(selected_method());
    });
    outer->addWidget(generate_btn_);

    contour_draft_btn_ = new QPushButton("生成等值线初稿", this);
    contour_draft_btn_->setObjectName("SecondaryButton");
    contour_draft_btn_->setToolTip(
        "从已完成的单因素网格提取等值线 ContourDraft，并推送到编图 line "
        "图层");
    connect(contour_draft_btn_, &QPushButton::clicked, this,
            &FactorTaskPanel::contour_draft_requested);
    outer->addWidget(contour_draft_btn_);

    scroll_ = new QScrollArea(this);
    scroll_->setWidgetResizable(true);
    scroll_->setFrameShape(QScrollArea::NoFrame);
    task_container_ = new QWidget(scroll_);
    task_layout_ = new QVBoxLayout(task_container_);
    task_layout_->setContentsMargins(0, 0, 0, 0);
    task_layout_->setSpacing(0);
    task_layout_->addStretch();
    scroll_->setWidget(task_container_);
    outer->addWidget(scroll_, 1);

    summary_label_ =
        secondary_label("已制备 0 / 0 个单因素图", this);
    outer->addWidget(summary_label_);
}

void FactorTaskPanel::sync_method_tooltip(const QString& text) {
    const auto& tooltips = tokens::interpolation_method_tooltips();
    const auto it = tooltips.find(text.toStdString());
    method_combo_->setToolTip(
        it != tooltips.end()
            ? QString::fromStdString(it->second)
            : QStringLiteral(
                  "插值方法（克里金为真实变差函数普通克里金，含克里金方差）"));
}

QString FactorTaskPanel::selected_method() const {
    const QString text = method_combo_->currentText();
    return QString::fromStdString(factor_selected_method(text.toStdString()));
}

void FactorTaskPanel::clear_rows() {
    while (task_layout_->count() > 1) {
        QLayoutItem* item = task_layout_->takeAt(0);
        if (QWidget* widget = item->widget()) {
            widget->hide();
            widget->setParent(nullptr);
            widget->deleteLater();
        }
        delete item;
    }
    row_count_ = 0;
}

void FactorTaskPanel::update_state(
    const std::vector<FactorTaskRecord>& tasks) {
    if (!tasks.empty()) {
        horizon_label_->setText(QString::fromStdString(
            factor_panel_horizon_text(tasks)));
        if (!method_user_selected_) {
            const auto common = factor_common_method(tasks);
            if (common.has_value()) {
                const int idx = method_combo_->findText(
                    QString::fromStdString(*common));
                method_combo_->setCurrentIndex(idx >= 0 ? idx : 0);
            } else {
                method_combo_->setCurrentIndex(0);
            }
        }
    } else {
        horizon_label_->setText("层位: —");
        if (!method_user_selected_) {
            method_combo_->setCurrentIndex(0);
        }
    }

    clear_rows();
    int insert_at = task_layout_->count() - 1;  // before the stretch
    for (const auto& task : tasks) {
        task_layout_->insertWidget(insert_at, new Row(task));
        ++insert_at;
        ++row_count_;
    }
    summary_label_->setText(
        QString::fromStdString(factor_prepared_summary(tasks)));
}

// ---------------------------------------------------------------------------
// FactorPreviewCard
// ---------------------------------------------------------------------------

FactorPreviewCard::FactorPreviewCard(
    std::shared_ptr<const FactorTaskRecord> task, QWidget* parent)
    : QFrame(parent), task_(std::move(task)) {
    setObjectName("FactorPreviewCard");
    setMinimumSize(160, 100);

    const FactorCardView view = factor_card_view(*task_);
    auto* layout = new QVBoxLayout(this);
    const int pad = tokens::PANEL_PADDING;
    layout->setContentsMargins(pad, pad, pad, pad);
    layout->setSpacing(tokens::SPACE_2);

    auto* name = new QLabel(QString::fromStdString(view.title), this);
    name->setObjectName("FactorCardTitle");
    layout->addWidget(name);
    auto* range = new QLabel(QString::fromStdString(view.range_text), this);
    layout->addWidget(range);
    auto* rsquared =
        secondary_label(QString::fromStdString(view.rsquared_text), this);
    rsquared->setVisible(view.rsquared_visible);
    layout->addWidget(rsquared);
    auto* dup = new QLabel(QString::fromStdString(view.dup_text), this);
    dup->setObjectName("FactorCardDupWarning");
    dup->setVisible(view.dup_visible);
    layout->addWidget(dup);
    layout->addStretch();
}

void FactorPreviewCard::mouseReleaseEvent(
    QMouseEvent* event) {
    if (event->button() == Qt::LeftButton) {
        emit clicked(task_);
        event->accept();
        return;
    }
    QFrame::mouseReleaseEvent(event);
}

// ---------------------------------------------------------------------------
// FactorPreviewGrid
// ---------------------------------------------------------------------------

FactorPreviewGrid::FactorPreviewGrid(QWidget* parent) : QWidget(parent) {
    setObjectName("FactorPreviewGrid");
    auto* outer = new QVBoxLayout(this);
    const int pad = tokens::PANEL_PADDING;
    outer->setContentsMargins(pad, pad, pad, pad);
    outer->setSpacing(tokens::SPACE_2);

    header_label_ = new QLabel("单因素图集", this);
    header_label_->setObjectName("MapDockTitle");
    outer->addWidget(header_label_);

    scroll_ = new QScrollArea(this);
    scroll_->setWidgetResizable(true);
    scroll_->setFrameShape(QScrollArea::NoFrame);
    grid_container_ = new QWidget(scroll_);
    grid_layout_ = new QGridLayout(grid_container_);
    grid_layout_->setContentsMargins(0, 0, 0, 0);
    grid_layout_->setSpacing(tokens::SPACE_3);
    grid_layout_->setColumnStretch(0, 1);
    grid_layout_->setColumnStretch(1, 1);
    scroll_->setWidget(grid_container_);
    outer->addWidget(scroll_, 1);
}

void FactorPreviewGrid::clear_grid() {
    while (grid_layout_->count()) {
        QLayoutItem* item = grid_layout_->takeAt(0);
        if (QWidget* widget = item->widget()) {
            widget->hide();
            widget->setParent(nullptr);
            widget->deleteLater();
        }
        delete item;
    }
    empty_label_ = nullptr;
    card_count_ = 0;
}

void FactorPreviewGrid::update_state(
    const std::vector<FactorTaskRecord>& tasks) {
    const auto completed = factor_completed_tasks(tasks);
    clear_grid();

    if (completed.empty()) {
        header_label_->setText("单因素图集");
        empty_label_ = new QLabel(QString::fromUtf8(kFactorPreviewEmptyText),
                                  grid_container_);
        empty_label_->setObjectName("EmptyStateLabel");
        grid_layout_->addWidget(empty_label_, 0, 0, 1, 2);
        return;
    }

    header_label_->setText(
        QString::fromStdString(factor_preview_header(completed)));
    constexpr int cols = 2;
    int index = 0;
    for (const auto& task : completed) {
        auto holder = std::make_shared<const FactorTaskRecord>(task);
        auto* card = new FactorPreviewCard(holder, grid_container_);
        connect(card, &FactorPreviewCard::clicked, this,
                [this](std::shared_ptr<const FactorTaskRecord> t) {
                    emit card_clicked(std::move(t));
                });
        grid_layout_->addWidget(card, index / cols, index % cols);
        ++index;
        ++card_count_;
    }
}

// ---------------------------------------------------------------------------
// CreateFactorMapDialog
// ---------------------------------------------------------------------------

CreateFactorMapDialog::CreateFactorMapDialog(QWidget* parent)
    : QDialog(parent), job_owner_(this) {
    setWindowTitle("创建地质单因素图件 (Geological Factor Map)");
    setMinimumWidth(480);
    setModal(true);

    auto* layout = new QVBoxLayout(this);
    layout->setSpacing(tokens::SPACE_3);

    auto* form_group = new QGroupBox("参数配置", this);
    auto* form_layout = new QFormLayout(form_group);

    factor_combo_ = new QComboBox(form_group);
    for (const auto& item : factor_map_factor_items()) {
        factor_combo_->addItem(QString::fromStdString(item));
    }
    form_layout->addRow("地质因素:", factor_combo_);

    horizon_combo_ = new QComboBox(form_group);
    for (const auto& item : factor_map_horizon_items("")) {
        horizon_combo_->addItem(QString::fromStdString(item));
    }
    form_layout->addRow("目的层段:", horizon_combo_);

    method_combo_ = new QComboBox(form_group);
    for (const auto& [label, data] : factor_map_method_items()) {
        method_combo_->addItem(QString::fromStdString(label),
                               QString::fromStdString(data));
    }
    form_layout->addRow("插值算法:", method_combo_);

    grid_size_spin_ = new QSpinBox(form_group);
    grid_size_spin_->setRange(20, 300);
    grid_size_spin_->setValue(50);
    grid_size_spin_->setSingleStep(10);
    form_layout->addRow("网格精度 (N×N):", grid_size_spin_);

    ramp_combo_ = new QComboBox(form_group);
    for (const auto& item : factor_map_ramp_items()) {
        ramp_combo_->addItem(QString::fromStdString(item));
    }
    form_layout->addRow("配色色带:", ramp_combo_);
    layout->addWidget(form_group);

    auto* layers_group = new QGroupBox("生成图层", this);
    auto* layers_layout = new QVBoxLayout(layers_group);
    chk_grid_ = new QCheckBox("连续属性栅格图层 (Grid Layer)", layers_group);
    chk_grid_->setChecked(true);
    chk_contour_ = new QCheckBox(
        "等值线矢量图层 (Contour Layer - Marching Squares)", layers_group);
    chk_contour_->setChecked(true);
    chk_wells_ =
        new QCheckBox("井位及属性标注图层 (Well Point Layer)", layers_group);
    chk_wells_->setChecked(true);
    chk_polygons_ = new QCheckBox("相带划分多边形图层 (Facies Polygon Layer)",
                                layers_group);
    chk_polygons_->setChecked(false);
    layers_layout->addWidget(chk_grid_);
    layers_layout->addWidget(chk_contour_);
    layers_layout->addWidget(chk_wells_);
    layers_layout->addWidget(chk_polygons_);
    layout->addWidget(layers_group);

    progress_bar_ = new QProgressBar(this);
    progress_bar_->setRange(0, 0);
    progress_bar_->setVisible(false);
    layout->addWidget(progress_bar_);

    auto* btn_layout = new QHBoxLayout();
    btn_layout->addStretch();
    btn_cancel_ = new QPushButton("取消", this);
    connect(btn_cancel_, &QPushButton::clicked, this,
            &CreateFactorMapDialog::reject);
    btn_layout->addWidget(btn_cancel_);
    btn_create_ = new QPushButton("开始生成图件", this);
    btn_create_->setObjectName("PrimaryButton");
    connect(btn_create_, &QPushButton::clicked, this, [this] {
        start_job();
    });
    btn_layout->addWidget(btn_create_);
    layout->addLayout(btn_layout);
}

void CreateFactorMapDialog::set_service(FactorMapServiceFn service) {
    service_ = std::move(service);
}

void CreateFactorMapDialog::set_stratigraphy_target(
    const QString& target_horizon) {
    horizon_combo_->clear();
    for (const auto& item :
         factor_map_horizon_items(target_horizon.toStdString())) {
        horizon_combo_->addItem(QString::fromStdString(item));
    }
}

FactorMapParams CreateFactorMapDialog::create_params() const {
    FactorMapParams params;
    params.factor_name = factor_combo_->currentText().toStdString();
    params.target_horizon = horizon_combo_->currentText().toStdString();
    const QString method = method_combo_->currentData().toString();
    params.method = method.isEmpty() ? "kriging" : method.toStdString();
    params.grid_n = grid_size_spin_->value();
    params.color_ramp = ramp_combo_->currentText().toStdString();
    params.include_grid = chk_grid_->isChecked();
    params.include_contours = chk_contour_->isChecked();
    params.include_wells = chk_wells_->isChecked();
    params.include_polygons = chk_polygons_->isChecked();
    return params;
}

bool CreateFactorMapDialog::start_job() {
    if (job_owner_.is_running() || !service_) {
        return false;
    }
    btn_create_->setEnabled(false);
    btn_cancel_->setEnabled(true);
    progress_bar_->setVisible(true);

    job::JobSpec spec =
        make_factor_map_job_spec(create_params(), service_);
    job_owner_.start(
        job::global_scheduler(), std::move(spec),
        [this](const job::qtbridge::JobOutcome& outcome) { on_job_finished(outcome); });
    return true;
}

void CreateFactorMapDialog::on_job_finished(
    const job::qtbridge::JobOutcome& outcome) {
    progress_bar_->setVisible(false);
    switch (outcome.state) {
    case job::JobState::done:
    case job::JobState::degraded: {
        const auto* result =
            std::any_cast<FactorMapOutcome>(&outcome.result);
        if (result == nullptr) {
            btn_create_->setEnabled(true);
            emit error_requested(
                "生成失败",
                QString::fromStdString(factor_map_failure_text(
                    outcome.error.empty() ? "empty result"
                                          : outcome.error)));
            return;
        }
        created_map_doc_ = result->map_document;
        emit map_created(*result);
        emit info_requested(
            "生成完成",
            QString::fromStdString(factor_map_success_text(
                result->map_title, result->layer_count)));
        accept();
        return;
    }
    case job::JobState::failed:
        btn_create_->setEnabled(true);
        btn_cancel_->setEnabled(true);
        emit error_requested(
            "生成失败",
            QString::fromStdString(
                factor_map_failure_text(outcome.error)));
        return;
    default:
        // cancelled / queued / running / cancelling — the Python worker's
        // silent return path; restore the idle controls.
        btn_create_->setEnabled(true);
        btn_cancel_->setEnabled(true);
        return;
    }
}

void CreateFactorMapDialog::closeEvent(QCloseEvent* event) {
    if (job_owner_.is_running()) {
        job_owner_.shutdown(1000);
    }
    QDialog::closeEvent(event);
}

void CreateFactorMapDialog::reject() {
    if (job_owner_.is_running()) {
        job_owner_.shutdown(1000);
    }
    QDialog::reject();
}

}  // namespace pwb::ui_seqviz::qt
