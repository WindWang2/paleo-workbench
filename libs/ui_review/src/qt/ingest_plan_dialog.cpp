#include "pwb/ui_review/qt/ingest_plan_dialog.hpp"

#include <pwb/qgis_processing/job_compat.hpp>
#include "pwb/ui_review/ingest_columns.hpp"
#include "pwb/ui_review/tokens.hpp"
#include "pwb/ui_widgets/object_table.hpp"

#include <QAbstractItemView>
#include <QCheckBox>
#include <QCloseEvent>
#include <QComboBox>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QLabel>
#include <QMessageBox>
#include <QProgressBar>
#include <QPushButton>
#include <QTableView>
#include <QVBoxLayout>

#include <algorithm>

namespace pwb::ui_review::qt {

namespace {

data::PlannedItem row_item(const QVariant& row) {
    return row.value<data::PlannedItem>();
}

}  // namespace

// -- IngestItemDetailPanel ------------------------------------------------------

IngestItemDetailPanel::IngestItemDetailPanel(QWidget* parent)
    : QFrame(parent) {
    setObjectName(QStringLiteral("IngestItemDetail"));
    auto* layout = new QHBoxLayout(this);
    layout->setContentsMargins(tokens::kSpace2, tokens::kSpace1,
                               tokens::kSpace2, tokens::kSpace1);

    title_label_ = new QLabel(QStringLiteral("未选中"), this);
    layout->addWidget(title_label_);

    layout->addWidget(new QLabel(QStringLiteral("决策"), this));
    decision_combo_ = new QComboBox(this);
    for (const auto& [value, label] : decision_labels()) {
        decision_combo_->addItem(QString::fromStdString(label),
                                 QString::fromStdString(value));
    }
    connect(decision_combo_, &QComboBox::currentIndexChanged, this,
            [this](int) { apply(); });
    layout->addWidget(decision_combo_);

    layout->addWidget(new QLabel(QStringLiteral("角色"), this));
    role_combo_ = new QComboBox(this);
    connect(role_combo_, &QComboBox::currentIndexChanged, this,
            [this](int) { apply(); });
    layout->addWidget(role_combo_);

    layout->addWidget(new QLabel(QStringLiteral("实体"), this));
    entity_combo_ = new QComboBox(this);
    connect(entity_combo_, &QComboBox::currentIndexChanged, this,
            [this](int) { apply(); });
    layout->addWidget(entity_combo_);

    primary_check_ = new QCheckBox(QStringLiteral("主用"), this);
    connect(primary_check_, &QCheckBox::toggled, this,
            [this](bool) { apply(); });
    layout->addWidget(primary_check_);
    layout->addStretch(1);
    setEnabled(false);
}

void IngestItemDetailPanel::set_item(
    data::PlannedItem* item,
    const std::vector<IngestEntityRow>& wells,
    const std::vector<IngestEntityRow>& surveys) {
    item_ = item;
    wells_ = wells;
    surveys_ = surveys;
    suppress_sync_ = true;
    title_label_->setText(
        item != nullptr
            ? QString::fromStdString(item->path.filename().string())
            : QStringLiteral("未选中"));
    setEnabled(item != nullptr);
    if (item != nullptr) {
        const auto& labels = decision_labels();
        int index = 0;
        for (size_t i = 0; i < labels.size(); ++i) {
            if (labels[i].first == item->decision) {
                index = int(i);
                break;
            }
        }
        decision_combo_->setCurrentIndex(index);
        reload_roles(*item);
        reload_entities(*item);
        primary_check_->setChecked(item->primary);
    }
    suppress_sync_ = false;
}

void IngestItemDetailPanel::reload_roles(const data::PlannedItem& item) {
    std::vector<std::string> roles(
        ingest_roles_for_entity_type(ingest_entity_type_for(item)));
    if (!item.role.empty() &&
        std::find(roles.begin(), roles.end(), item.role) == roles.end()) {
        roles.push_back(item.role);
    }
    role_combo_->blockSignals(true);
    role_combo_->clear();
    for (const auto& role : roles) {
        role_combo_->addItem(QString::fromStdString(role),
                             QString::fromStdString(role));
    }
    const int index = role_combo_->findData(
        QString::fromStdString(item.role));
    role_combo_->setCurrentIndex(std::max(0, index));
    role_combo_->blockSignals(false);
}

void IngestItemDetailPanel::reload_entities(
    const data::PlannedItem& item) {
    const auto options = ingest_entity_options(item, wells_, surveys_);
    entity_combo_->blockSignals(true);
    entity_combo_->clear();
    for (const auto& option : options) {
        entity_combo_->addItem(
            QString::fromStdString(option.label),
            QStringList{QString::fromStdString(option.entity_type),
                        QString::fromStdString(option.entity_id)});
    }
    const auto [cur_type, cur_id] = ingest_entity_current(item);
    const int index = entity_combo_->findData(
        QStringList{QString::fromStdString(cur_type),
                    QString::fromStdString(cur_id)});
    entity_combo_->setCurrentIndex(index >= 0 ? index : 0);
    entity_combo_->blockSignals(false);
}

void IngestItemDetailPanel::apply() {
    if (item_ == nullptr || suppress_sync_) {
        return;
    }
    const QString decision = decision_combo_->currentData().toString();
    if (!decision.isEmpty()) {
        item_->decision = decision.toStdString();
    }
    const QString role = role_combo_->currentData().toString();
    if (!role.isEmpty()) {
        item_->role = role.toStdString();
    }
    const QStringList entity_data =
        entity_combo_->currentData().toStringList();
    const std::string entity_type =
        entity_data.value(0).toStdString();
    const std::string entity_value =
        entity_data.value(1).toStdString();
    if (entity_value == std::string(kIngestNewEntityId)) {
        item_->identity.new_entity = true;
        if (item_->identity.strategy.empty()) {
            item_->identity.strategy = "manual";
        }
        item_->identity.confidence = "manual";
    } else if (!entity_value.empty()) {
        item_->identity.entity_type = entity_type;
        item_->identity.entity_id = entity_value;
        item_->identity.new_entity = false;
        item_->identity.strategy = "manual";
        item_->identity.confidence = "manual";
    }
    item_->primary = primary_check_->isChecked();
    emit item_edited();
}

// -- IngestPlanDialog --------------------------------------------------------------

IngestPlanDialog::IngestPlanDialog(
    QWidget* parent, IngestDialogHooks hooks, std::filesystem::path root)
    : QDialog(parent), hooks_(std::move(hooks)), root_(std::move(root)) {
    setWindowTitle(QStringLiteral("规划导入 (Ingest Plan)"));
    resize(1000, 640);
    job_ = std::make_unique<pwb::qgis_processing::PwbTaskOwner>(this);

    auto* layout = new QVBoxLayout(this);
    layout->setSpacing(tokens::kSpace2);

    header_label_ = new QLabel(
        QStringLiteral("扫描目标：") +
            QString::fromStdString(root_.string()),
        this);
    header_label_->setWordWrap(true);
    layout->addWidget(header_label_);
    summary_label_ =
        new QLabel(QStringLiteral("正在构建导入计划…"), this);
    layout->addWidget(summary_label_);
    progress_ = new QProgressBar(this);
    progress_->setRange(0, 1);
    progress_->setValue(0);
    layout->addWidget(progress_);

    // -- plan table -----------------------------------------------------------
    model_ = new ui_widgets::ObjectTableModel(
        {ui_widgets::ColumnSpec{
             QStringLiteral("status"), QStringLiteral("状态"),
             [](const QVariant& row) -> QVariant {
                 return QString::fromStdString(
                     ingest_status_display(row_item(row)));
             }},
         ui_widgets::ColumnSpec{
             QStringLiteral("file"), QStringLiteral("文件"),
             [](const QVariant& row) -> QVariant {
                 return QString::fromStdString(
                     row_item(row).path.filename().string());
             },
             {}, Qt::AlignLeft | Qt::AlignVCenter,
             [](const QVariant& row) {
                 return QString::fromStdString(
                     row_item(row).path.string());
             }},
         ui_widgets::ColumnSpec{
             QStringLiteral("type"), QStringLiteral("类型"),
             [](const QVariant& row) -> QVariant {
                 return QString::fromStdString(row_item(row).type);
             }},
         ui_widgets::ColumnSpec{
             QStringLiteral("entity"), QStringLiteral("实体（推断）"),
             [](const QVariant& row) -> QVariant {
                 return QString::fromStdString(
                     ingest_entity_display(row_item(row)));
             }},
         ui_widgets::ColumnSpec{
             QStringLiteral("confidence"), QStringLiteral("置信度"),
             [](const QVariant& row) -> QVariant {
                 return QString::fromStdString(
                     ingest_confidence_display(row_item(row)));
             }},
         ui_widgets::ColumnSpec{
             QStringLiteral("role"), QStringLiteral("角色"),
             [](const QVariant& row) -> QVariant {
                 return QString::fromStdString(row_item(row).role);
             }},
         ui_widgets::ColumnSpec{
             QStringLiteral("primary"), QStringLiteral("主用"),
             [](const QVariant& row) -> QVariant {
                 return row_item(row).primary ? QStringLiteral("✓")
                                              : QString();
             }},
         ui_widgets::ColumnSpec{
             QStringLiteral("decision"), QStringLiteral("决策"),
             [](const QVariant& row) -> QVariant {
                 return QString::fromStdString(
                     decision_display(row_item(row)));
             }},
         ui_widgets::ColumnSpec{
             QStringLiteral("note"), QStringLiteral("备注"),
             [](const QVariant& row) -> QVariant {
                 return QString::fromStdString(
                     ingest_note_display(row_item(row)));
             }}},
        [](const QVariant& row) {
            return QString::fromStdString(row_item(row).path.string());
        },
        this);
    table_ = new QTableView(this);
    table_->setModel(model_);
    table_->setSelectionBehavior(QAbstractItemView::SelectRows);
    table_->setSelectionMode(QAbstractItemView::ExtendedSelection);
    table_->setEditTriggers(QAbstractItemView::NoEditTriggers);
    table_->setAlternatingRowColors(true);
    table_->horizontalHeader()->setSectionResizeMode(
        QHeaderView::Interactive);
    table_->horizontalHeader()->setStretchLastSection(false);
    table_->verticalHeader()->setVisible(false);
    connect(table_->selectionModel(),
            &QItemSelectionModel::selectionChanged, this,
            &IngestPlanDialog::on_selection_changed);
    layout->addWidget(table_, 1);

    detail_ = new IngestItemDetailPanel(this);
    connect(detail_, &IngestItemDetailPanel::item_edited, this,
            &IngestPlanDialog::on_item_edited);
    layout->addWidget(detail_);

    auto* buttons = new QHBoxLayout();
    accept_all_btn_ =
        new QPushButton(QStringLiteral("全部接受"), this);
    accept_all_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    connect(accept_all_btn_, &QPushButton::clicked, this,
            &IngestPlanDialog::accept_all);
    buttons->addWidget(accept_all_btn_);

    skip_unresolved_btn_ =
        new QPushButton(QStringLiteral("待确认项设为跳过"), this);
    skip_unresolved_btn_->setObjectName(
        QStringLiteral("SecondaryButton"));
    connect(skip_unresolved_btn_, &QPushButton::clicked, this,
            &IngestPlanDialog::skip_unresolved);
    buttons->addWidget(skip_unresolved_btn_);

    buttons->addStretch(1);

    cancel_run_btn_ =
        new QPushButton(QStringLiteral("取消执行"), this);
    cancel_run_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    connect(cancel_run_btn_, &QPushButton::clicked, this,
            &IngestPlanDialog::cancel_run);
    cancel_run_btn_->setVisible(false);
    buttons->addWidget(cancel_run_btn_);

    execute_btn_ = new QPushButton(QStringLiteral("执行导入"), this);
    execute_btn_->setObjectName(QStringLiteral("PrimaryButton"));
    execute_btn_->setEnabled(false);
    connect(execute_btn_, &QPushButton::clicked, this,
            &IngestPlanDialog::execute);
    buttons->addWidget(execute_btn_);

    auto* close_btn = new QPushButton(QStringLiteral("关闭"), this);
    close_btn->setObjectName(QStringLiteral("SecondaryButton"));
    connect(close_btn, &QPushButton::clicked, this, &QDialog::accept);
    buttons->addWidget(close_btn);
    layout->addLayout(buttons);

    start_build();
}

IngestPlanDialog::~IngestPlanDialog() = default;

std::vector<IngestEntityRow> IngestPlanDialog::wells() const {
    return hooks_.wells ? hooks_.wells() : std::vector<IngestEntityRow>{};
}

std::vector<IngestEntityRow> IngestPlanDialog::surveys() const {
    return hooks_.surveys ? hooks_.surveys()
                          : std::vector<IngestEntityRow>{};
}

// -- worker -----------------------------------------------------------------

void IngestPlanDialog::start_build() {
    if (!hooks_.build) {
        summary_label_->setText(QStringLiteral("导入服务不可用"));
        return;
    }
    const auto root = root_;
    job::JobSpec spec;
    spec.title = "build ingest plan";
    spec.run = [this, root](job::JobContext& ctx) -> std::any {
        data::IngestPlanOptions options;
        options.progress = [&ctx](int done, int total) {
            ctx.report_progress(double(done), double(total));
        };
        options.cancel = [&ctx] {
            return ctx.token().is_cancelled();
        };
        return hooks_.build(root, options);
    };
    pwb::qgis_processing::start_job_spec(
        *job_, std::move(spec),
        [this](const pwb::qgis_processing::CompatJobOutcome& outcome) {
            running_ = false;
            switch (outcome.state) {
            case job::JobState::done:
            case job::JobState::degraded: {
                plan_ = std::any_cast<data::IngestPlan>(outcome.result);
                progress_->setRange(0, 1);
                progress_->setValue(1);
                rebuild_rows();
                refresh_summary();
                execute_btn_->setEnabled(!plan_->items.empty());
                detail_->set_item(nullptr, {}, {});
                break;
            }
            case job::JobState::failed:
                summary_label_->setText(QString::fromStdString(
                    outcome.error));
                break;
            case job::JobState::cancelled:
                summary_label_->setText(
                    QStringLiteral("已取消构建"));
                break;
            default:
                break;
            }
        },
        [this](double ratio, const QString&) {
            progress_->setRange(0, 1000);
            progress_->setValue(int(ratio * 1000));
        });
}

void IngestPlanDialog::execute() {
    if (!plan_ || !hooks_.execute || job_->is_running()) {
        return;
    }
    if (!plan_->unresolved().empty() &&
        !ingest_unresolved_skipped(*plan_)) {
        const auto answer = QMessageBox::question(
            this, QStringLiteral("存在待确认项"),
            QStringLiteral(
                "仍有身份待确认的文件（将按当前决策执行，未确认项默认跳过）。"
                "继续吗？"),
            QMessageBox::Yes | QMessageBox::No);
        if (answer != QMessageBox::Yes) {
            return;
        }
    }
    set_running(true);

    const auto plan = *plan_;  // snapshot — worker must not share the copy
    job::JobSpec spec;
    spec.title = "execute ingest plan";
    spec.run = [this, plan](job::JobContext& ctx) -> std::any {
        data::IngestExecuteOptions options;
        options.bind = true;
        options.progress = [&ctx](int done, int total) {
            ctx.report_progress(double(done), double(total));
        };
        options.cancel = [&ctx] {
            return ctx.token().is_cancelled();
        };
        return hooks_.execute(plan, options);
    };
    pwb::qgis_processing::start_job_spec(
        *job_, std::move(spec),
        [this](const pwb::qgis_processing::CompatJobOutcome& outcome) {
            set_running(false);
            switch (outcome.state) {
            case job::JobState::done:
            case job::JobState::degraded: {
                const auto report =
                    std::any_cast<data::IngestExecuteReport>(
                        outcome.result);
                summary_label_->setText(
                    QString::fromStdString(ingest_done_text(report)));
                emit ingest_finished();
                break;
            }
            case job::JobState::failed:
                summary_label_->setText(QString::fromStdString(
                    outcome.error));
                break;
            case job::JobState::cancelled:
                summary_label_->setText(
                    QStringLiteral("已取消执行"));
                break;
            default:
                break;
            }
        },
        [this](double ratio, const QString&) {
            progress_->setRange(0, 1000);
            progress_->setValue(int(ratio * 1000));
        });
}

void IngestPlanDialog::cancel_run() {
    if (job_->is_running()) {
        job_->cancel();
        cancel_run_btn_->setEnabled(false);
    }
}

void IngestPlanDialog::teardown_worker() {
    // Cooperative stop (cancel first, bounded join; on timeout the job
    // detaches to the keeper — never destroy a live thread).
    if (job_->is_running()) {
        job_->cancel();
        job_->shutdown(5000);
    }
}

void IngestPlanDialog::closeEvent(QCloseEvent* event) {
    cancel_run();
    teardown_worker();
    QDialog::closeEvent(event);
}

void IngestPlanDialog::set_running(bool running) {
    running_ = running;
    cancel_run_btn_->setVisible(running);
    execute_btn_->setEnabled(!running && plan_.has_value());
    accept_all_btn_->setEnabled(!running);
    skip_unresolved_btn_->setEnabled(!running);
    detail_->setEnabled(false);  // 执行期间计划只读
}

// -- plan editing -----------------------------------------------------------------

void IngestPlanDialog::on_selection_changed() {
    const auto indexes = table_->selectionModel()->selectedRows();
    if (indexes.isEmpty() || !plan_) {
        detail_->set_item(nullptr, {}, {});
        return;
    }
    const int row = indexes.first().row();
    if (row < 0 || row >= int(plan_->items.size())) {
        detail_->set_item(nullptr, {}, {});
        return;
    }
    if (running_) {
        return;  // plan is read-only while executing
    }
    detail_->set_item(&plan_->items[size_t(row)], wells(), surveys());
}

void IngestPlanDialog::on_item_edited() {
    rebuild_rows();
    refresh_summary();
}

void IngestPlanDialog::accept_all() {
    if (!plan_) {
        return;
    }
    ingest_accept_all(*plan_);
    on_item_edited();
}

void IngestPlanDialog::skip_unresolved() {
    if (!plan_) {
        return;
    }
    ingest_skip_unresolved(*plan_);
    on_item_edited();
}

void IngestPlanDialog::refresh_summary() {
    if (!plan_) {
        return;
    }
    summary_label_->setText(
        QString::fromStdString(ingest_plan_summary_text(*plan_)));
}

void IngestPlanDialog::rebuild_rows() {
    std::vector<QVariant> rows;
    if (plan_) {
        rows.reserve(plan_->items.size());
        for (const auto& item : plan_->items) {
            rows.push_back(QVariant::fromValue(item));
        }
    }
    model_->set_rows(rows);
}

}  // namespace pwb::ui_review::qt

Q_DECLARE_METATYPE(pwb::data::PlannedItem)
