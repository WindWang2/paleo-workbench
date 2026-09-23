#include "pwb/ui_review/qt/relink_dialog.hpp"

#include "pwb/domain/stage.hpp"
#include <pwb/qgis_processing/job_compat.hpp>
#include "pwb/ui_review/relink_summary.hpp"
#include "pwb/ui_review/tokens.hpp"
#include "pwb/ui_widgets/object_table.hpp"
#include "pwb/ui_widgets/states.hpp"

#include <QCloseEvent>
#include <QFileDialog>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QLabel>
#include <QMessageBox>
#include <QPushButton>
#include <QResizeEvent>
#include <QTableView>
#include <QVBoxLayout>

#include <algorithm>
#include <cctype>

namespace pwb::ui_review::qt {

namespace {

catalog::MissingSource row_entry(const QVariant& row) {
    return row.value<catalog::MissingSource>();
}

// _STAGE_LABELS: raw→RAW, derived→DERIVED, ... (uppercase enum value).
QString stage_label_for(const catalog::MissingSource& entry) {
    std::string value(domain::to_string(entry.stage));
    for (char& c : value) {
        c = char(std::toupper(static_cast<unsigned char>(c)));
    }
    return QString::fromStdString(value);
}

}  // namespace

RelinkSourcesDialog::RelinkSourcesDialog(
    QWidget* parent, std::function<ICatalogApi*()> service_provider)
    : QDialog(parent), service_provider_(std::move(service_provider)) {
    setWindowTitle(QStringLiteral("缺失源与重新链接 (Relink)"));
    resize(880, 540);
    // One task per role: shutdown happens ONLY on dialog close.
    scan_job_ = std::make_unique<pwb::qgis_processing::PwbTaskOwner>(this);
    relink_job_ = std::make_unique<pwb::qgis_processing::PwbTaskOwner>(this);

    auto* layout = new QVBoxLayout(this);
    layout->setSpacing(tokens::kSpace2);

    summary_label_ = new QLabel(QStringLiteral("正在扫描缺失源…"), this);
    summary_label_->setWordWrap(true);
    summary_label_->setObjectName(
        QStringLiteral("WorkstationPanelTitle"));
    layout->addWidget(summary_label_);

    model_ = new ui_widgets::ObjectTableModel(
        {ui_widgets::ColumnSpec{
             QStringLiteral("data"), QStringLiteral("数据"),
             [](const QVariant& row) -> QVariant {
                 return QString::fromStdString(row_entry(row).asset_name);
             }},
         ui_widgets::ColumnSpec{
             QStringLiteral("stage"), QStringLiteral("阶段"),
             [](const QVariant& row) -> QVariant {
                 return stage_label_for(row_entry(row));
             }},
         ui_widgets::ColumnSpec{
             QStringLiteral("kind"), QStringLiteral("类别"),
             [](const QVariant& row) -> QVariant {
                 return row_entry(row).managed
                            ? QStringLiteral("托管")
                            : QStringLiteral("外部");
             }},
         ui_widgets::ColumnSpec{
             QStringLiteral("path"), QStringLiteral("记录路径"),
             [](const QVariant& row) -> QVariant {
                 return QString::fromStdString(
                     row_entry(row).recorded_path);
             }},
         ui_widgets::ColumnSpec{
             QStringLiteral("status"), QStringLiteral("状态"),
             [](const QVariant& row) -> QVariant {
                 return QString::fromStdString(
                     relink_entry_status(row_entry(row)));
             }}},
        [](const QVariant& row) {
            return QString::fromStdString(row_entry(row).version_id);
        },
        this);
    table_ = new QTableView(this);
    table_->setModel(model_);
    ui_widgets::bind_table_defaults(table_);
    table_->horizontalHeader()->setSectionResizeMode(
        3, QHeaderView::Stretch);
    layout->addWidget(table_, 1);

    empty_state_ = new ui_widgets::PwbEmptyState(
        QStringLiteral("未发现缺失源"),
        QStringLiteral("全部版本的数据源均可正常解析。"),
        QStringLiteral("inbox.svg"), nullptr, this);
    empty_state_->setAttribute(Qt::WA_TransparentForMouseEvents);
    empty_state_->setParent(table_);
    empty_state_->hide();
    connect(model_, &QAbstractItemModel::modelReset, this,
            &RelinkSourcesDialog::update_empty_state);
    connect(model_, &QAbstractItemModel::rowsInserted, this,
            &RelinkSourcesDialog::update_empty_state);
    connect(model_, &QAbstractItemModel::rowsRemoved, this,
            &RelinkSourcesDialog::update_empty_state);

    progress_ = new ui_widgets::PwbLoadingState(
        QStringLiteral("正在扫描缺失源…"), this);
    progress_->setVisible(false);
    layout->addWidget(progress_);

    detail_label_ = new QLabel(
        QStringLiteral(
            "重新链接仅在能证明身份时进行（sha256 或 记录的 size+mtime "
            "指纹）；无法证明将拒绝，绝不按文件名静默错绑。托管载荷缺失请"
            "重新导入。"),
        this);
    detail_label_->setWordWrap(true);
    detail_label_->setObjectName(
        QStringLiteral("WorkstationPanelFootnote"));
    layout->addWidget(detail_label_);

    auto* buttons = new QHBoxLayout();
    relink_btn_ = new QPushButton(QStringLiteral("重新链接…"), this);
    relink_btn_->setObjectName(QStringLiteral("PrimaryButton"));
    relink_btn_->setEnabled(false);
    connect(relink_btn_, &QPushButton::clicked, this,
            &RelinkSourcesDialog::relink_selected);
    buttons->addWidget(relink_btn_);
    folder_btn_ =
        new QPushButton(QStringLiteral("目录重定向…"), this);
    folder_btn_->setEnabled(false);
    connect(folder_btn_, &QPushButton::clicked, this,
            &RelinkSourcesDialog::relink_folder);
    buttons->addWidget(folder_btn_);
    rescan_btn_ = new QPushButton(QStringLiteral("重新扫描"), this);
    connect(rescan_btn_, &QPushButton::clicked, this,
            &RelinkSourcesDialog::start_scan);
    buttons->addWidget(rescan_btn_);
    buttons->addStretch();
    auto* close_btn = new QPushButton(QStringLiteral("关闭"), this);
    close_btn->setObjectName(QStringLiteral("SecondaryButton"));
    connect(close_btn, &QPushButton::clicked, this, &QDialog::reject);
    buttons->addWidget(close_btn);
    layout->addLayout(buttons);

    connect(table_->selectionModel(),
            &QItemSelectionModel::selectionChanged, this,
            &RelinkSourcesDialog::sync_buttons);
    start_scan();
}

RelinkSourcesDialog::~RelinkSourcesDialog() = default;

// -- worker plumbing ---------------------------------------------------------

void RelinkSourcesDialog::cancel_running() {
    // Close-time teardown only. The workers poll the cancel token between
    // items; the bounded join covers the item in flight.
    if (scan_job_->is_running()) {
        scan_job_->shutdown(3000);
    }
    if (relink_job_->is_running()) {
        relink_job_->shutdown(3000);
    }
    busy_ = false;
}

void RelinkSourcesDialog::closeEvent(QCloseEvent* event) {
    cancel_running();
    QDialog::closeEvent(event);
}

void RelinkSourcesDialog::reject() {
    cancel_running();
    QDialog::reject();
}

// -- scan ---------------------------------------------------------------------

void RelinkSourcesDialog::start_scan() {
    ICatalogApi* service =
        service_provider_ ? service_provider_() : nullptr;
    if (service == nullptr) {
        summary_label_->setText(QStringLiteral("数据目录不可用"));
        return;
    }
    if (busy_ || scan_job_->is_running() || relink_job_->is_running()) {
        return;  // one task at a time
    }
    busy_ = true;
    sync_buttons();
    summary_label_->setText(QStringLiteral("正在扫描缺失源…"));
    progress_->set_text(QStringLiteral("正在扫描缺失源…"));
    progress_->setVisible(true);

    job::JobSpec spec;
    spec.title = "missing-source scan";
    spec.run = [service](job::JobContext& ctx) -> std::any {
        return service->find_missing_sources(
            [&ctx] { return ctx.token().is_cancelled(); });
    };
    pwb::qgis_processing::start_job_spec(
        *scan_job_, std::move(spec),
        [this](const pwb::qgis_processing::CompatJobOutcome& outcome) {
        busy_ = false;
        progress_->setVisible(false);
        sync_buttons();
        switch (outcome.state) {
        case job::JobState::done:
        case job::JobState::degraded: {
            const auto report =
                std::any_cast<catalog::MissingSourceReport>(
                    outcome.result);
            entries_ = report.entries;
            const int relinkable = int(report.relinkable().size());
            summary_label_->setText(QString::fromStdString(
                relink_scan_summary(report.scanned,
                                    int(entries_.size()), relinkable)));
            std::vector<QVariant> rows;
            rows.reserve(entries_.size());
            for (const auto& e : entries_) {
                rows.push_back(QVariant::fromValue(e));
            }
            model_->set_rows(rows);
            break;
        }
        case job::JobState::failed:
            summary_label_->setText(QStringLiteral("扫描失败：") +
                                    QString::fromStdString(
                                        outcome.error));
            break;
        case job::JobState::cancelled:
            summary_label_->setText(QStringLiteral("扫描已取消"));
            break;
        default:
            break;
        }
    });
}

// -- relink ---------------------------------------------------------------------

const catalog::MissingSource*
RelinkSourcesDialog::selected_entry() const {
    const auto rows = table_->selectionModel()->selectedRows();
    if (rows.size() != 1) {
        return nullptr;
    }
    const int row = rows.first().row();
    if (row < 0 || row >= int(entries_.size())) {
        return nullptr;
    }
    return &entries_[size_t(row)];
}

void RelinkSourcesDialog::sync_buttons() {
    const bool idle = !busy_;
    const catalog::MissingSource* entry = selected_entry();
    relink_btn_->setEnabled(idle && entry != nullptr &&
                            entry->relinkable);
    const bool has_relinkable =
        std::any_of(entries_.begin(), entries_.end(),
                    [](const catalog::MissingSource& e) {
                        return e.relinkable;
                    });
    folder_btn_->setEnabled(idle && has_relinkable);
    rescan_btn_->setEnabled(idle);
}

void RelinkSourcesDialog::relink_selected() {
    const catalog::MissingSource* entry = selected_entry();
    if (entry == nullptr) {
        return;
    }
    const QString new_path = QFileDialog::getOpenFileName(
        this, QStringLiteral("选择新位置的文件"),
        QString::fromStdString(entry->recorded_path));
    if (new_path.isEmpty()) {
        return;
    }
    apply_relinks(
        {{entry, std::filesystem::path(new_path.toStdString())}});
}

void RelinkSourcesDialog::relink_folder() {
    const QString directory = QFileDialog::getExistingDirectory(
        this, QStringLiteral("选择迁移后的目录"));
    if (directory.isEmpty()) {
        return;
    }
    const std::filesystem::path root(directory.toStdString());
    std::vector<std::pair<const catalog::MissingSource*,
                          std::filesystem::path>>
        pending;
    for (const auto& entry : entries_) {
        if (!entry.relinkable) {
            continue;
        }
        const auto candidate =
            root / std::filesystem::path(entry.recorded_path)
                       .filename();
        std::error_code ec;
        if (std::filesystem::is_regular_file(candidate, ec)) {
            pending.emplace_back(&entry, candidate);
        }
    }
    if (pending.empty()) {
        QMessageBox::information(
            this, QStringLiteral("目录重定向"),
            QStringLiteral(
                "所选目录中没有与缺失源同名的文件；未做任何改动。"));
        return;
    }
    apply_relinks(pending);
}

void RelinkSourcesDialog::apply_relinks(
    const std::vector<std::pair<const catalog::MissingSource*,
                                std::filesystem::path>>& pending) {
    ICatalogApi* service =
        service_provider_ ? service_provider_() : nullptr;
    if (service == nullptr || busy_ || scan_job_->is_running() ||
        relink_job_->is_running()) {
        return;
    }
    // Snapshot (version_id, candidate, label) — pointers into entries_
    // must not cross the thread boundary.
    struct Pair {
        std::string version_id;
        std::filesystem::path candidate;
        std::string label;
    };
    std::vector<Pair> pairs;
    pairs.reserve(pending.size());
    for (const auto& [entry, candidate] : pending) {
        pairs.push_back(
            {entry->version_id, candidate, entry->asset_name});
    }

    busy_ = true;
    sync_buttons();
    progress_->set_text(QStringLiteral("正在验证并重链接…"));
    progress_->setVisible(true);

    job::JobSpec spec;
    spec.title = "relink external sources";
    spec.run = [service, pairs](job::JobContext& ctx) -> std::any {
        RelinkBatchResult result;
        for (const auto& pair : pairs) {
            if (ctx.token().is_cancelled()) {
                result.cancelled = true;
                break;
            }
            const auto error = service->relink_external_source(
                pair.version_id, pair.candidate);
            if (error.ok()) {
                ++result.ok;
            } else {
                // Identity-unprovable (ConflictBaseVersion) and other
                // codes alike: reason per row, entry stays missing.
                result.reasons.push_back(pair.label + ": " +
                                         error.message);
            }
        }
        return result;
    };
    pwb::qgis_processing::start_job_spec(
        *relink_job_, std::move(spec),
        [this](const pwb::qgis_processing::CompatJobOutcome& outcome) {
        busy_ = false;
        progress_->setVisible(false);
        sync_buttons();
        switch (outcome.state) {
        case job::JobState::done:
        case job::JobState::degraded: {
            const auto result =
                std::any_cast<RelinkBatchResult>(outcome.result);
            if (result.ok > 0) {
                emit sources_relinked(result.ok);
            }
            QMessageBox::information(
                this, QStringLiteral("重链接结果"),
                QString::fromStdString(relink_result_message(result)));
            break;
        }
        case job::JobState::failed:
            QMessageBox::warning(this, QStringLiteral("重链接失败"),
                                 QString::fromStdString(outcome.error));
            break;
        default:
            break;
        }
        start_scan();
    });
}

// -- empty state overlay ----------------------------------------------------------

void RelinkSourcesDialog::resizeEvent(QResizeEvent* event) {
    QDialog::resizeEvent(event);
    if (empty_state_->isVisible()) {
        empty_state_->setGeometry(table_->viewport()->rect());
    }
}

void RelinkSourcesDialog::update_empty_state() {
    // 扫描进行中不算空态（加载面已占位）。
    if (!busy_ && model_->rowCount() == 0) {
        empty_state_->setGeometry(table_->viewport()->rect());
        empty_state_->show();
        empty_state_->raise();
    } else {
        empty_state_->hide();
    }
}

}  // namespace pwb::ui_review::qt

Q_DECLARE_METATYPE(pwb::catalog::MissingSource)
