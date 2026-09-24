#include "pwb/ui_review/qt/version_workbench_dialog.hpp"

#include <pwb/qgis_processing/job_compat.hpp>
#include "pwb/ui_data_core/asset_view.hpp"
#include "pwb/ui_review/tokens.hpp"
#include "pwb/ui_widgets/object_table.hpp"

#include <QDesktopServices>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QLabel>
#include <QMessageBox>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QTableView>
#include <QTableWidget>
#include <QUrl>
#include <QVBoxLayout>

#include <algorithm>
#include <set>

namespace pwb::ui_review::qt {

namespace {

catalog::DataVersion row_version(const QVariant& row) {
    return row.value<catalog::DataVersion>();
}

QString trashed_fg(const QVariant& row) {
    return row_version(row).trashed
               ? QStringLiteral("TEXT_SECONDARY")
               : QString();
}

}  // namespace

// -- VersionCompareDialog ------------------------------------------------------

VersionCompareDialog::VersionCompareDialog(
    QWidget* parent, const catalog::DataVersion& newer,
    const catalog::DataVersion& older)
    : QDialog(parent) {
    setWindowTitle(
        QString::fromStdString(compare_title(newer, older)));
    resize(720, 440);
    auto* layout = new QVBoxLayout(this);
    layout->setSpacing(tokens::kSpace2);

    table_ = new QTableWidget(0, 4, this);
    table_->setHorizontalHeaderLabels(
        {QStringLiteral("字段"),
         QStringLiteral("v%1").arg(newer.version_number),
         QStringLiteral("v%1").arg(older.version_number),
         QStringLiteral("结果")});
    table_->horizontalHeader()->setSectionResizeMode(
        QHeaderView::ResizeToContents);
    table_->horizontalHeader()->setStretchLastSection(true);
    table_->verticalHeader()->setVisible(false);
    table_->setEditTriggers(QTableWidget::NoEditTriggers);
    table_->setAlternatingRowColors(true);
    layout->addWidget(table_, 1);

    for (const CompareRow& r : version_compare_rows(newer, older)) {
        const int row = table_->rowCount();
        table_->insertRow(row);
        table_->setItem(row, 0, new QTableWidgetItem(
                                   QString::fromStdString(r.field)));
        table_->setItem(row, 1, new QTableWidgetItem(
                                   QString::fromStdString(r.left)));
        table_->setItem(row, 2, new QTableWidgetItem(
                                   QString::fromStdString(r.right)));
        auto* marker = new QTableWidgetItem(r.differ
                                                ? QStringLiteral("异")
                                                : QStringLiteral("同"));
        if (r.differ) {
            marker->setForeground(Qt::red);
        }
        table_->setItem(row, 3, marker);
    }

    auto* buttons = new QHBoxLayout();
    buttons->addStretch();
    auto* close_btn = new QPushButton(QStringLiteral("关闭"), this);
    connect(close_btn, &QPushButton::clicked, this, &QDialog::accept);
    buttons->addWidget(close_btn);
    layout->addLayout(buttons);
}

// -- VersionWorkbenchDialog ----------------------------------------------------

VersionWorkbenchDialog::VersionWorkbenchDialog(
    QWidget* parent, std::function<ICatalogApi*()> service_provider,
    QString asset_id)
    : QDialog(parent),
      service_provider_(std::move(service_provider)),
      asset_id_(std::move(asset_id)) {
    setWindowTitle(QStringLiteral("版本工作台 (Version Workbench)"));
    resize(940, 640);
    promote_job_ = std::make_unique<pwb::qgis_processing::PwbTaskOwner>(this);

    auto* layout = new QVBoxLayout(this);
    layout->setSpacing(tokens::kSpace2);

    auto* header = new QHBoxLayout();
    header_label_ = new QLabel(QStringLiteral("版本工作台"), this);
    header_label_->setWordWrap(true);
    header->addWidget(header_label_, 1);
    count_label_ = new QLabel(QString(), this);
    header->addWidget(count_label_);
    layout->addLayout(header);

    // -- version timeline (newest first) --------------------------------------
    auto trashed_fg_fn = [](const QVariant& row) { return trashed_fg(row); };
    versions_model_ = new ui_widgets::ObjectTableModel(
        {ui_widgets::ColumnSpec{
             QStringLiteral("version"), QStringLiteral("版本"),
             [this](const QVariant& row) -> QVariant {
                 return QString::fromStdString(version_cell(
                     row_version(row), current_version_id_));
             },
             {}, Qt::AlignLeft | Qt::AlignVCenter, {}, trashed_fg_fn},
         ui_widgets::ColumnSpec{
             QStringLiteral("stage"), QStringLiteral("阶段"),
             [](const QVariant& row) -> QVariant {
                 return QString::fromStdString(
                     stage_display(row_version(row)));
             },
             {}, Qt::AlignLeft | Qt::AlignVCenter, {}, trashed_fg_fn},
         ui_widgets::ColumnSpec{
             QStringLiteral("checksum"), QStringLiteral("校验和"),
             [](const QVariant& row) -> QVariant {
                 return QString::fromStdString(
                     checksum_display(row_version(row).sha256));
             },
             {}, Qt::AlignLeft | Qt::AlignVCenter, {}, trashed_fg_fn},
         ui_widgets::ColumnSpec{
             QStringLiteral("size"), QStringLiteral("大小"),
             [](const QVariant& row) -> QVariant {
                 return QString::fromStdString(
                     ui_data_core::format_size(
                         row_version(row).size_bytes));
             },
             {}, Qt::AlignLeft | Qt::AlignVCenter, {}, trashed_fg_fn},
         ui_widgets::ColumnSpec{
             QStringLiteral("run"), QStringLiteral("生成 Run"),
             [](const QVariant& row) -> QVariant {
                 const auto& rid = row_version(row).run_id;
                 return QString::fromStdString(short_id(
                     rid ? std::optional<std::string>(rid->str())
                         : std::nullopt));
             },
             {}, Qt::AlignLeft | Qt::AlignVCenter, {}, trashed_fg_fn},
         ui_widgets::ColumnSpec{
             QStringLiteral("created"), QStringLiteral("时间"),
             [](const QVariant& row) -> QVariant {
                 const std::string& t = row_version(row).created_at;
                 return QString::fromStdString(
                     t.substr(0, std::min<size_t>(19, t.size())));
             },
             {}, Qt::AlignLeft | Qt::AlignVCenter, {}, trashed_fg_fn},
         ui_widgets::ColumnSpec{
             QStringLiteral("source"), QStringLiteral("源"),
             [](const QVariant& row) -> QVariant {
                 return row_version(row).managed
                            ? QStringLiteral("托管")
                            : QStringLiteral("外部");
             },
             {}, Qt::AlignLeft | Qt::AlignVCenter, {}, trashed_fg_fn}},
        [](const QVariant& row) {
            return QString::fromStdString(row_version(row).id.str());
        },
        this);

    versions_table_ = new QTableView(this);
    versions_table_->setModel(versions_model_);
    ui_widgets::bind_table_defaults(versions_table_);
    // ExtendedSelection: exactly-two selection gates 对比元数据.
    versions_table_->setSelectionMode(QTableView::ExtendedSelection);
    versions_table_->horizontalHeader()->setSectionResizeMode(
        QHeaderView::ResizeToContents);
    versions_table_->horizontalHeader()->setStretchLastSection(true);
    versions_table_->verticalHeader()->setDefaultSectionSize(28);
    connect(versions_table_->selectionModel(),
            &QItemSelectionModel::selectionChanged, this,
            &VersionWorkbenchDialog::on_selection_changed);
    timeline_selection_ =
        std::make_unique<ui_widgets::StableSelection>(versions_table_);
    layout->addWidget(versions_table_, 1);

    // -- detail panel -----------------------------------------------------------
    detail_title_label_ = new QLabel(QStringLiteral("版本详情"), this);
    layout->addWidget(detail_title_label_);
    detail_parents_label_ =
        new QLabel(QStringLiteral("父版本: —"), this);
    detail_parents_label_->setWordWrap(true);
    layout->addWidget(detail_parents_label_);
    detail_run_label_ = new QLabel(QStringLiteral("生成 Run: —"), this);
    detail_run_label_->setWordWrap(true);
    layout->addWidget(detail_run_label_);
    layout->addWidget(new QLabel(QStringLiteral("Run 参数:"), this));
    detail_run_params_ = new QPlainTextEdit(this);
    detail_run_params_->setReadOnly(true);
    detail_run_params_->setMaximumHeight(72);
    detail_run_params_->setPlaceholderText(QStringLiteral("—"));
    layout->addWidget(detail_run_params_);
    detail_path_label_ = new QLabel(QStringLiteral("记录路径: —"), this);
    detail_path_label_->setWordWrap(true);
    layout->addWidget(detail_path_label_);
    detail_resolved_label_ =
        new QLabel(QStringLiteral("解析位置: —"), this);
    detail_resolved_label_->setWordWrap(true);
    layout->addWidget(detail_resolved_label_);
    layout->addWidget(
        new QLabel(QStringLiteral("元数据 (JSON):"), this));
    detail_meta_text_ = new QPlainTextEdit(this);
    detail_meta_text_->setReadOnly(true);
    layout->addWidget(detail_meta_text_, 1);

    // -- actions ------------------------------------------------------------------
    auto* buttons = new QHBoxLayout();
    promote_btn_ =
        new QPushButton(QStringLiteral("提升为正式数据…"), this);
    promote_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    promote_btn_->setToolTip(QStringLiteral(
        "将选中版本复制为新的不可变正式成果 (OUTPUT) 版本"));
    connect(promote_btn_, &QPushButton::clicked, this,
            &VersionWorkbenchDialog::on_promote_clicked);
    buttons->addWidget(promote_btn_);

    open_btn_ = new QPushButton(QStringLiteral("打开位置"), this);
    open_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    open_btn_->setToolTip(
        QStringLiteral("在文件管理器中打开版本载荷所在目录"));
    connect(open_btn_, &QPushButton::clicked, this,
            &VersionWorkbenchDialog::on_open_clicked);
    buttons->addWidget(open_btn_);

    compare_btn_ =
        new QPushButton(QStringLiteral("对比元数据"), this);
    compare_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    compare_btn_->setToolTip(
        QStringLiteral("按住 Ctrl 选择恰好两个版本后对比"));
    connect(compare_btn_, &QPushButton::clicked, this,
            &VersionWorkbenchDialog::on_compare_clicked);
    buttons->addWidget(compare_btn_);

    trash_btn_ = new QPushButton(QStringLiteral("删除版本"), this);
    trash_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    connect(trash_btn_, &QPushButton::clicked, this,
            &VersionWorkbenchDialog::on_trash_clicked);
    buttons->addWidget(trash_btn_);

    restore_btn_ =
        new QPushButton(QStringLiteral("还原版本"), this);
    restore_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    connect(restore_btn_, &QPushButton::clicked, this,
            &VersionWorkbenchDialog::on_restore_clicked);
    buttons->addWidget(restore_btn_);

    buttons->addStretch();
    auto* close_btn = new QPushButton(QStringLiteral("关闭"), this);
    connect(close_btn, &QPushButton::clicked, this, &QDialog::accept);
    buttons->addWidget(close_btn);
    layout->addLayout(buttons);

    reload_versions();
}

VersionWorkbenchDialog::~VersionWorkbenchDialog() = default;

ICatalogApi* VersionWorkbenchDialog::service() const {
    return service_provider_ ? service_provider_() : nullptr;
}

void VersionWorkbenchDialog::reload_versions() {
    ICatalogApi* svc = service();
    if (svc == nullptr) {
        header_label_->setText(
            QStringLiteral("未连接数据目录（请先打开项目）"));
        count_label_->setText(QString());
        versions_.clear();
        current_version_id_.clear();
        apply_timeline_rows();
        show_detail(nullptr);
        sync_action_buttons();
        return;
    }
    const auto asset = svc->get_asset(asset_id_.toStdString());
    if (!asset) {
        header_label_->setText(QStringLiteral(
            "该数据资产已不存在（可能已被彻底删除）"));
        count_label_->setText(QString());
        versions_.clear();
        current_version_id_.clear();
        apply_timeline_rows();
        show_detail(nullptr);
        sync_action_buttons();
        return;
    }
    // list_versions is ascending; the timeline is newest-first.
    versions_ = svc->list_versions(asset_id_.toStdString());
    std::reverse(versions_.begin(), versions_.end());
    current_version_id_ = asset->current_version_id
                              ? asset->current_version_id->str()
                              : std::string();
    const catalog::DataVersion* current = nullptr;
    for (const auto& v : versions_) {
        if (v.id.str() == current_version_id_) {
            current = &v;
            break;
        }
    }
    header_label_->setText(QString::fromStdString(workbench_header_text(
        *asset, current ? std::optional<int>(current->version_number)
                        : std::nullopt)));
    count_label_->setText(QString::fromStdString(
        workbench_count_text(int(versions_.size()))));

    apply_timeline_rows();
    // 选择保持后由 selectionChanged 驱动详情；无选中时回到占位详情。
    if (single_selection() == nullptr) {
        show_detail(nullptr);
    }
    sync_action_buttons();
}

void VersionWorkbenchDialog::apply_timeline_rows() {
    const auto keys = timeline_selection_->capture();
    const QString current_key =
        versions_model_->key_for_index(versions_table_->currentIndex());
    std::vector<QVariant> rows;
    rows.reserve(versions_.size());
    for (const auto& v : versions_) {
        rows.push_back(QVariant::fromValue(v));
    }
    versions_model_->set_rows(rows);
    timeline_selection_->restore(keys, current_key);
}

// -- selection ---------------------------------------------------------------

std::vector<int> VersionWorkbenchDialog::selected_rows() const {
    std::set<int> rows;
    const auto indexes =
        versions_table_->selectionModel()->selectedIndexes();
    for (const auto& index : indexes) {
        rows.insert(index.row());
    }
    return {rows.begin(), rows.end()};
}

const catalog::DataVersion*
VersionWorkbenchDialog::single_selection() const {
    const auto rows = selected_rows();
    if (rows.size() != 1 || rows[0] < 0 ||
        rows[0] >= int(versions_.size())) {
        return nullptr;
    }
    return &versions_[size_t(rows[0])];
}

void VersionWorkbenchDialog::on_selection_changed() {
    show_detail(single_selection());
    sync_action_buttons();
}

void VersionWorkbenchDialog::set_actions_enabled(bool enabled) {
    // Global gate during the off-thread promote (payload copy).
    for (QPushButton* button :
         {promote_btn_, trash_btn_, restore_btn_, compare_btn_,
          open_btn_}) {
        if (button != nullptr) {
            button->setEnabled(enabled);
        }
    }
}

void VersionWorkbenchDialog::sync_action_buttons() {
    const auto rows = selected_rows();
    const catalog::DataVersion* version =
        rows.size() == 1 && rows[0] < int(versions_.size())
            ? &versions_[size_t(rows[0])]
            : nullptr;
    bool payload_exists = false;
    if (version != nullptr) {
        ICatalogApi* svc = service();
        if (svc != nullptr) {
            payload_exists = svc->resolve_path(*version).is_file;
        }
    }
    const VersionActionGate gate =
        version_action_gate(int(rows.size()),
                            version != nullptr && version->trashed,
                            payload_exists);
    promote_btn_->setEnabled(gate.promote);
    trash_btn_->setEnabled(gate.trash);
    restore_btn_->setEnabled(gate.restore);
    compare_btn_->setEnabled(gate.compare);
    open_btn_->setEnabled(gate.open);
}

// -- detail rendering ------------------------------------------------------------

void VersionWorkbenchDialog::show_detail(
    const catalog::DataVersion* version) {
    std::optional<LineageHop> hop;
    std::optional<ResolvedPath> resolved;
    if (version != nullptr) {
        ICatalogApi* svc = service();
        if (svc != nullptr) {
            hop = svc->get_lineage(version->id.str());
            resolved = svc->resolve_path(*version);
        }
    }
    const VersionDetailText detail = version_detail_text(
        version, hop ? &*hop : nullptr, resolved);
    detail_title_label_->setText(QString::fromStdString(detail.title));
    detail_parents_label_->setText(
        QString::fromStdString(detail.parents));
    detail_run_label_->setText(QString::fromStdString(detail.run));
    detail_run_params_->setPlainText(
        QString::fromStdString(detail.run_params));
    detail_path_label_->setText(QString::fromStdString(detail.path));
    detail_resolved_label_->setText(
        QString::fromStdString(detail.resolved));
    detail_meta_text_->setPlainText(
        QString::fromStdString(detail.meta));
}

// -- actions -------------------------------------------------------------------

bool VersionWorkbenchDialog::confirm(const QString& title,
                                     const QString& text) {
    return QMessageBox::question(this, title, text,
                                 QMessageBox::Yes | QMessageBox::No,
                                 QMessageBox::No) == QMessageBox::Yes;
}

void VersionWorkbenchDialog::finish_mutation() {
    reload_versions();
    emit versions_changed();
}

void VersionWorkbenchDialog::on_promote_clicked() {
    const catalog::DataVersion* version = single_selection();
    ICatalogApi* svc = service();
    if (version == nullptr || version->trashed || svc == nullptr) {
        return;
    }
    if (!confirm(QStringLiteral("提升为正式数据"),
                 QStringLiteral(
                     "将 v%1 复制为新的不可变正式成果 (OUTPUT) 版本？"
                     "（源版本保持不变以保留溯源；大文件复制+校验在后台执行）")
                     .arg(version->version_number))) {
        return;
    }
    // promote = payload copy + SHA-256 + fsync — off the GUI thread.
    const std::string version_id = version->id.str();
    set_actions_enabled(false);
    job::JobSpec spec;
    spec.title = "promote version";
    spec.run = [svc, version_id](job::JobContext&) -> std::any {
        return svc->promote_version(version_id);
    };
    pwb::qgis_processing::start_job_spec(
        *promote_job_, std::move(spec),
        [this](const pwb::qgis_processing::CompatJobOutcome& outcome) {
        set_actions_enabled(true);
        if (outcome.state == job::JobState::failed) {
            QMessageBox::critical(this, QStringLiteral("提升失败"),
                                  QStringLiteral("提升版本失败: ") +
                                      QString::fromStdString(
                                          outcome.error));
        } else if (outcome.state == job::JobState::done) {
            // promote_version returns a DataError — empty means success.
            const auto error =
                std::any_cast<domain::DataError>(outcome.result);
            if (!error.ok()) {
                QMessageBox::critical(
                    this, QStringLiteral("提升失败"),
                    QStringLiteral("提升版本失败: ") +
                        QString::fromStdString(error.message));
            }
        }
        finish_mutation();
    });
}

void VersionWorkbenchDialog::on_open_clicked() {
    const catalog::DataVersion* version = single_selection();
    ICatalogApi* svc = service();
    if (version == nullptr || svc == nullptr) {
        return;
    }
    const ResolvedPath resolved = svc->resolve_path(*version);
    if (!resolved.is_file) {
        return;
    }
    // resolved.parent() — the payload's containing directory.
    const std::filesystem::path parent =
        std::filesystem::path(resolved.path).parent_path();
    QDesktopServices::openUrl(
        QUrl::fromLocalFile(QString::fromStdString(parent.string())));
}

void VersionWorkbenchDialog::on_compare_clicked() {
    const auto rows = selected_rows();
    if (rows.size() != 2) {
        return;
    }
    // Rows are newest-first: the lower row index is the newer version.
    VersionCompareDialog compare(this, versions_[size_t(rows[0])],
                                 versions_[size_t(rows[1])]);
    compare.exec();
}

void VersionWorkbenchDialog::on_trash_clicked() {
    const catalog::DataVersion* version = single_selection();
    ICatalogApi* svc = service();
    if (version == nullptr || version->trashed || svc == nullptr) {
        return;
    }
    if (!confirm(QStringLiteral("删除版本"),
                 QStringLiteral(
                     "将 v%1 移入回收站？载荷将移入 trash/，"
                     "可随时在版本工作台还原。")
                     .arg(version->version_number))) {
        return;
    }
    const auto error = svc->trash_version(version->id.str(),
                                          "版本工作台删除");
    if (!error.ok()) {
        QMessageBox::critical(this, QStringLiteral("删除失败"),
                              QStringLiteral("删除版本失败: ") +
                                  QString::fromStdString(error.message));
        return;
    }
    finish_mutation();
}

void VersionWorkbenchDialog::on_restore_clicked() {
    const catalog::DataVersion* version = single_selection();
    ICatalogApi* svc = service();
    if (version == nullptr || !version->trashed || svc == nullptr) {
        return;
    }
    if (!confirm(QStringLiteral("还原版本"),
                 QStringLiteral("将 v%1 从回收站还原？")
                     .arg(version->version_number))) {
        return;
    }
    const auto error = svc->restore_version(version->id.str());
    if (!error.ok()) {
        QMessageBox::critical(this, QStringLiteral("还原失败"),
                              QStringLiteral("还原版本失败: ") +
                                  QString::fromStdString(error.message));
        return;
    }
    finish_mutation();
}

}  // namespace pwb::ui_review::qt

Q_DECLARE_METATYPE(pwb::catalog::DataVersion)
