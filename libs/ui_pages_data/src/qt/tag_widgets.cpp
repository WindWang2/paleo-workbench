// UI-06 — tag widget shells (see qt/tag_widgets.hpp).
#include <pwb/ui_pages_data/qt/tag_widgets.hpp>

#include <QCheckBox>
#include <QDialogButtonBox>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QInputDialog>
#include <QLabel>
#include <QMessageBox>
#include <QPushButton>
#include <QScrollArea>
#include <QStandardItemModel>
#include <QTimer>
#include <QVBoxLayout>

#include <algorithm>

#include <pwb/ui_pages_data/tag_text.hpp>
#include <pwb/ui_pages_data/timings.hpp>
#include <pwb/ui_shell/style_registry.hpp>

namespace pwb::ui_pages_data::qt {

namespace {

QString pal(const char* key) {
    const auto p = ui_shell::style_palette();
    const auto it = p.find(key);
    return it != p.end() ? QString::fromStdString(it->second) : QString();
}

}  // namespace

// --- TagBadge ------------------------------------------------------------------

TagBadge::TagBadge(const QString& tag_name, bool removable,
                   QWidget* parent)
    : QWidget(parent), tag_name_(tag_name.trimmed()) {
    auto* layout = new QHBoxLayout(this);
    layout->setContentsMargins(6, 2, 6, 2);
    layout->setSpacing(4);
    auto* label = new QLabel(QStringLiteral("#%1").arg(tag_name_), this);
    ui_shell::style_bind(label, [] {
        return QStringLiteral(
                   "color: %1; font-size: 11px; font-weight: 500;")
            .arg(pal("PRIMARY"));
    });
    layout->addWidget(label);
    if (removable) {
        auto* remove_btn = new QPushButton(QStringLiteral("×"), this);
        remove_btn->setFixedSize(14, 14);
        remove_btn->setCursor(Qt::CursorShape::PointingHandCursor);
        remove_btn->setToolTip(QStringLiteral("移除标签"));
        ui_shell::style_bind(remove_btn, [] {
            return QStringLiteral(
                "QPushButton { border: none; background: transparent;"
                " padding: 0px; }");
        });
        connect(remove_btn, &QPushButton::clicked, this,
                [this] { Q_EMIT remove_requested(tag_name_); });
        layout->addWidget(remove_btn);
    }
    ui_shell::style_bind(this, [] {
        return QStringLiteral(
                   "QWidget { background-color: %1;"
                   " border: 1px solid %2; border-radius: 4px; }")
            .arg(pal("BG_SIDEBAR"), pal("BORDER"));
    });
}

// --- TagContainerWidget ---------------------------------------------------------

TagContainerWidget::TagContainerWidget(bool removable, QWidget* parent)
    : QWidget(parent), removable_(removable) {
    layout_ = new QHBoxLayout(this);
    layout_->setContentsMargins(0, 0, 0, 0);
    layout_->setSpacing(4);
    add_btn_ = new QPushButton(QStringLiteral("+ 标签"), this);
    add_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    add_btn_->setToolTip(QStringLiteral("添加新标签"));
    add_btn_->setFixedHeight(22);
    connect(add_btn_, &QPushButton::clicked, this,
            &TagContainerWidget::prompt_add_tag);
    layout_->addWidget(add_btn_);
    layout_->addStretch();
}

void TagContainerWidget::set_tags(const std::vector<std::string>& tags) {
    tags_.clear();
    for (const auto& raw : tags) {
        const auto t = QString::fromStdString(raw).trimmed();
        if (!t.isEmpty()) tags_.push_back(t.toStdString());
    }
    while (layout_->count() > 2) {
        QLayoutItem* item = layout_->takeAt(0);
        if (item->widget() != nullptr && item->widget() != add_btn_) {
            item->widget()->deleteLater();
        }
        delete item;
    }
    for (const auto& tag : tags_) {
        auto* badge = new TagBadge(QString::fromStdString(tag),
                                   removable_, this);
        connect(badge, &TagBadge::remove_requested, this,
                &TagContainerWidget::on_remove_tag);
        layout_->insertWidget(layout_->count() - 2, badge);
    }
}

void TagContainerWidget::on_remove_tag(const QString& tag_name) {
    const auto it = std::find(tags_.begin(), tags_.end(),
                              tag_name.toStdString());
    if (it == tags_.end()) return;
    tags_.erase(it);
    set_tags(tags_);
    Q_EMIT tag_removed(tag_name);
}

void TagContainerWidget::prompt_add_tag() {
    TagInputDialog dlg(tags_, this);
    if (dlg.exec() != QDialog::DialogCode::Accepted) return;
    const QString new_tag = dlg.tag_name();
    if (new_tag.isEmpty()) return;
    if (std::find(tags_.begin(), tags_.end(), new_tag.toStdString()) !=
        tags_.end()) {
        return;
    }
    tags_.push_back(new_tag.toStdString());
    set_tags(tags_);
    Q_EMIT tag_added(new_tag);
}

// --- TagInputDialog -------------------------------------------------------------

TagInputDialog::TagInputDialog(std::vector<std::string> existing_tags,
                               QWidget* parent)
    : QDialog(parent), existing_(std::move(existing_tags)) {
    for (auto& t : existing_) {
        std::transform(t.begin(), t.end(), t.begin(), ::tolower);
    }
    setWindowTitle(QStringLiteral("添加标签"));
    setMinimumWidth(280);
    auto* layout = new QVBoxLayout(this);
    label_ = new QLabel(QStringLiteral("请输入标签名称:"), this);
    layout->addWidget(label_);
    input_ = new QLineEdit(this);
    input_->setPlaceholderText(
        QStringLiteral("例如: 重点井, 探井, 2026..."));
    layout->addWidget(input_);
    error_label_ = new QLabel(QString(), this);
    ui_shell::style_bind(error_label_, [] {
        return QStringLiteral("color: %1; font-size: 11px;")
            .arg(pal("ERROR_RED"));
    });
    layout->addWidget(error_label_);
    auto* buttons = new QDialogButtonBox(
        QDialogButtonBox::StandardButton::Ok |
            QDialogButtonBox::StandardButton::Cancel,
        this);
    connect(buttons, &QDialogButtonBox::accepted, this,
            &TagInputDialog::validate_and_accept);
    connect(buttons, &QDialogButtonBox::rejected, this,
            &TagInputDialog::reject);
    layout->addWidget(buttons);
}

QString TagInputDialog::tag_name() const {
    QString text = input_->text().trimmed();
    while (text.startsWith(QLatin1Char('#'))) text = text.mid(1);
    return text;
}

void TagInputDialog::validate_and_accept() {
    const QString name = tag_name();
    if (name.isEmpty()) {
        error_label_->setText(QStringLiteral("标签名称不能为空"));
        return;
    }
    const auto lower = name.toLower().toStdString();
    if (std::find(existing_.begin(), existing_.end(), lower) !=
        existing_.end()) {
        error_label_->setText(QStringLiteral("该标签已存在"));
        return;
    }
    accept();
}

// --- BulkAddTagDialog ------------------------------------------------------------

BulkAddTagDialog::BulkAddTagDialog(QWidget* parent) : QDialog(parent) {
    setWindowTitle(QStringLiteral("批量添加标签"));
    setMinimumWidth(320);
    auto* layout = new QVBoxLayout(this);
    layout->addWidget(new QLabel(
        QStringLiteral("请输入标签名称（多个标签用逗号或分号分隔）:"), this));
    input_ = new QLineEdit(this);
    input_->setPlaceholderText(
        QStringLiteral("例如: 重点井, 探井; 2026..."));
    layout->addWidget(input_);
    error_label_ = new QLabel(QString(), this);
    ui_shell::style_bind(error_label_, [] {
        return QStringLiteral("color: %1; font-size: 11px;")
            .arg(pal("ERROR_RED"));
    });
    layout->addWidget(error_label_);
    auto* buttons = new QDialogButtonBox(
        QDialogButtonBox::StandardButton::Ok |
            QDialogButtonBox::StandardButton::Cancel,
        this);
    connect(buttons, &QDialogButtonBox::accepted, this,
            &BulkAddTagDialog::validate_and_accept);
    connect(buttons, &QDialogButtonBox::rejected, this,
            &BulkAddTagDialog::reject);
    layout->addWidget(buttons);
}

std::vector<std::string> BulkAddTagDialog::tag_names() const {
    return parse_multi_tag_input(input_->text().toStdString());
}

void BulkAddTagDialog::validate_and_accept() {
    if (tag_names().empty()) {
        error_label_->setText(
            QStringLiteral("请至少输入一个有效的标签名称"));
        return;
    }
    accept();
}

// --- BulkRemoveTagDialog -----------------------------------------------------------

BulkRemoveTagDialog::BulkRemoveTagDialog(
    std::vector<std::string> candidate_tags, QWidget* parent)
    : QDialog(parent) {
    setWindowTitle(QStringLiteral("批量移除标签"));
    setMinimumWidth(320);
    auto* layout = new QVBoxLayout(this);
    layout->addWidget(
        new QLabel(QStringLiteral("勾选要从选中数据移除的标签:"), this));
    auto* scroll = new QScrollArea(this);
    scroll->setWidgetResizable(true);
    scroll->setFrameShape(QScrollArea::Shape::NoFrame);
    auto* container = new QWidget();
    auto* container_layout = new QVBoxLayout(container);
    container_layout->setContentsMargins(0, 0, 0, 0);
    container_layout->setSpacing(4);
    container_layout->setAlignment(Qt::AlignmentFlag::AlignTop);
    for (const auto& raw : candidate_tags) {
        const auto tag = QString::fromStdString(raw).trimmed();
        if (tag.isEmpty()) continue;
        auto* checkbox = new QCheckBox(tag, container);
        checkboxes_.push_back(checkbox);
        container_layout->addWidget(checkbox);
    }
    container_layout->addStretch();
    scroll->setWidget(container);
    layout->addWidget(scroll, 1);
    auto* buttons = new QDialogButtonBox(
        QDialogButtonBox::StandardButton::Ok |
            QDialogButtonBox::StandardButton::Cancel,
        this);
    buttons->button(QDialogButtonBox::StandardButton::Ok)
        ->setText(QStringLiteral("移除"));
    connect(buttons, &QDialogButtonBox::accepted, this,
            &BulkRemoveTagDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, this,
            &BulkRemoveTagDialog::reject);
    layout->addWidget(buttons);
}

std::vector<std::string> BulkRemoveTagDialog::selected_tags() const {
    std::vector<std::string> out;
    for (const auto* cb : checkboxes_) {
        if (cb->isChecked()) out.push_back(cb->text().toStdString());
    }
    return out;
}

// --- TagManagerDialog -------------------------------------------------------------

TagManagerDialog::TagManagerDialog(
    std::function<TagServiceApi*()> service_provider, QWidget* parent)
    : QDialog(parent), service_provider_(std::move(service_provider)) {
    setWindowTitle(QStringLiteral("标签管理"));
    setMinimumSize(480, 420);
    auto* layout = new QVBoxLayout(this);

    hint_label_ = new QLabel(
        QStringLiteral("未连接数据目录 — 标签管理不可用"), this);
    ui_shell::style_bind(hint_label_, [] {
        return QStringLiteral("color: %1;").arg(pal("TEXT_SECONDARY"));
    });
    hint_label_->setAlignment(Qt::AlignmentFlag::AlignCenter);
    layout->addWidget(hint_label_);

    search_debounce_ = new QTimer(this);
    search_debounce_->setSingleShot(true);
    search_debounce_->setInterval(kSearchDebounceMs);
    connect(search_debounce_, &QTimer::timeout, this,
            &TagManagerDialog::reload_table);

    auto* search_row = new QHBoxLayout();
    search_input_ = new QLineEdit(this);
    search_input_->setPlaceholderText(QStringLiteral("搜索标签..."));
    connect(search_input_, &QLineEdit::textChanged, this,
            [this](const QString&) { search_debounce_->start(); });
    search_row->addWidget(search_input_, 1);
    layout->addLayout(search_row);

    model_ = new QStandardItemModel(this);
    model_->setColumnCount(3);
    model_->setHorizontalHeaderLabels(
        {QStringLiteral("标签"), QStringLiteral("Asset 使用数"),
         QStringLiteral("Version 使用数")});
    table_ = new QTableView(this);
    table_->setModel(model_);
    table_->horizontalHeader()->setSectionResizeMode(
        QHeaderView::ResizeMode::Stretch);
    table_->setSelectionMode(
        QTableView::SelectionMode::SingleSelection);
    table_->setSelectionBehavior(
        QTableView::SelectionBehavior::SelectRows);
    connect(table_->selectionModel(), &QItemSelectionModel::selectionChanged,
            this, [this] { sync_row_actions(); });
    connect(table_, &QTableView::doubleClicked, this,
            [this](const QModelIndex& index) {
                on_row_double_clicked(index.row());
            });
    layout->addWidget(table_, 1);

    auto* button_row = new QHBoxLayout();
    create_btn_ = new QPushButton(QStringLiteral("新建"), this);
    rename_btn_ = new QPushButton(QStringLiteral("重命名"), this);
    merge_btn_ = new QPushButton(QStringLiteral("合并"), this);
    delete_btn_ = new QPushButton(QStringLiteral("删除无用"), this);
    prune_btn_ = new QPushButton(QStringLiteral("清理全部无用"), this);
    refresh_btn_ = new QPushButton(QStringLiteral("刷新"), this);
    for (auto* btn : {create_btn_, rename_btn_, merge_btn_, delete_btn_,
                      prune_btn_, refresh_btn_}) {
        btn->setObjectName(QStringLiteral("SecondaryButton"));
        button_row->addWidget(btn);
    }
    button_row->addStretch();
    layout->addLayout(button_row);

    connect(create_btn_, &QPushButton::clicked, this,
            &TagManagerDialog::on_create);
    connect(rename_btn_, &QPushButton::clicked, this,
            &TagManagerDialog::on_rename);
    connect(merge_btn_, &QPushButton::clicked, this,
            &TagManagerDialog::on_merge);
    connect(delete_btn_, &QPushButton::clicked, this,
            &TagManagerDialog::on_delete_unused);
    connect(prune_btn_, &QPushButton::clicked, this,
            &TagManagerDialog::on_prune_unused);
    connect(refresh_btn_, &QPushButton::clicked, this,
            &TagManagerDialog::reload);

    reload();
}

TagServiceApi* TagManagerDialog::service() {
    try {
        return service_provider_ ? service_provider_() : nullptr;
    } catch (...) {
        return nullptr;
    }
}

std::vector<TagUsageRow> TagManagerDialog::usage_rows() {
    auto* svc = service();
    if (svc == nullptr) return {};
    std::string error;
    auto rows = svc->tag_usage(&error);
    if (!error.empty()) {
        load_error_ = "标签统计加载失败: " + error;
        return {};
    }
    const auto text = search_input_->text().trimmed();
    if (!text.isEmpty()) {
        std::string search_error;
        const auto matched = svc->search_tags(text.toStdString(),
                                              &search_error);
        if (!search_error.empty()) {
            load_error_ = "标签搜索失败: " + search_error;
        }
        std::vector<TagUsageRow> filtered;
        for (const auto& row : rows) {
            if (std::find(matched.begin(), matched.end(), row.name) !=
                matched.end()) {
                filtered.push_back(row);
            }
        }
        rows = std::move(filtered);
    }
    std::sort(rows.begin(), rows.end(), [](const auto& a, const auto& b) {
        return QString::fromStdString(a.display_name).toLower() <
               QString::fromStdString(b.display_name).toLower();
    });
    return rows;
}

void TagManagerDialog::reload() { reload_table(); }

void TagManagerDialog::reload_table() {
    const bool has_service = service() != nullptr;
    load_error_.clear();
    rows_ = has_service ? usage_rows() : std::vector<TagUsageRow>{};
    if (has_service && !load_error_.empty()) {
        hint_label_->setText(QString::fromStdString(load_error_));
        hint_label_->setVisible(true);
        rows_.clear();
    } else if (!has_service) {
        hint_label_->setText(
            QStringLiteral("未连接数据目录 — 标签管理不可用"));
        hint_label_->setVisible(true);
    } else {
        hint_label_->setVisible(false);
    }

    model_->removeRows(0, model_->rowCount());
    for (const auto& row : rows_) {
        model_->appendRow(
            {new QStandardItem(QString::fromStdString(row.display_name)),
             new QStandardItem(QString::number(row.assets)),
             new QStandardItem(QString::number(row.versions))});
    }

    for (auto* btn : {create_btn_, rename_btn_, merge_btn_, delete_btn_,
                      prune_btn_, refresh_btn_}) {
        btn->setEnabled(has_service);
    }
    sync_row_actions();
}

const TagUsageRow* TagManagerDialog::current_row() const {
    const int row = table_->currentIndex().row();
    if (row < 0 || row >= static_cast<int>(rows_.size())) return nullptr;
    return &rows_[static_cast<std::size_t>(row)];
}

void TagManagerDialog::sync_row_actions() {
    const bool has_row = current_row() != nullptr;
    for (auto* btn : {rename_btn_, merge_btn_, delete_btn_}) {
        btn->setEnabled(has_row && service() != nullptr);
    }
}

void TagManagerDialog::notify_changed() {
    reload();
    Q_EMIT tags_changed();
}

void TagManagerDialog::on_create() {
    auto* svc = service();
    if (svc == nullptr) return;
    std::vector<std::string> existing;
    for (const auto& row : rows_) existing.push_back(row.display_name);
    if (existing.empty()) existing = svc->list_tags();
    TagInputDialog dlg(existing, this);
    dlg.setWindowTitle(QStringLiteral("新建标签"));
    if (dlg.exec() != QDialog::DialogCode::Accepted) return;
    const auto name = dlg.tag_name().toStdString();
    if (name.empty()) return;
    std::string error;
    if (!svc->create_tag(name, &error)) {
        QMessageBox::critical(this, QStringLiteral("新建标签失败"),
                              QStringLiteral("新建标签失败: %1")
                                  .arg(QString::fromStdString(error)));
        return;
    }
    notify_changed();
}

void TagManagerDialog::on_rename() {
    auto* svc = service();
    const auto* row = current_row();
    if (svc == nullptr || row == nullptr) return;
    const QString old_name = QString::fromStdString(row->display_name);
    // Refuse when the row is stale (tag deleted elsewhere since load).
    const auto names = svc->list_tags();
    if (std::find(names.begin(), names.end(), row->name) == names.end()) {
        QMessageBox::warning(
            this, QStringLiteral("标签不存在"),
            QStringLiteral("标签 “%1” 已不存在，请刷新后重试。")
                .arg(old_name));
        reload();
        return;
    }
    TagInputDialog dlg({}, this);
    dlg.setWindowTitle(QStringLiteral("重命名标签"));
    dlg.label()->setText(
        QStringLiteral("将标签 “%1” 重命名为:").arg(old_name));
    if (dlg.exec() != QDialog::DialogCode::Accepted) return;
    const auto new_name = dlg.tag_name().toStdString();
    if (new_name.empty()) return;

    std::string error;
    if (!svc->rename_tag(row->name, new_name, "error", &error)) {
        if (error.find("already exists") == std::string::npos) {
            QMessageBox::critical(this, QStringLiteral("重命名失败"),
                                  QStringLiteral("重命名标签失败: %1")
                                      .arg(QString::fromStdString(error)));
            return;
        }
        const auto answer = QMessageBox::question(
            this, QStringLiteral("标签冲突"),
            QStringLiteral(
                "标签 “%1” 已存在。\n是否将 “%2” 合并到 “%1”？")
                .arg(QString::fromStdString(new_name), old_name),
            QMessageBox::StandardButton::Yes |
                QMessageBox::StandardButton::No,
            QMessageBox::StandardButton::No);
        if (answer != QMessageBox::StandardButton::Yes) return;
        error.clear();
        if (!svc->rename_tag(row->name, new_name, "merge", &error)) {
            QMessageBox::critical(this, QStringLiteral("合并失败"),
                                  QStringLiteral("合并标签失败: %1")
                                      .arg(QString::fromStdString(error)));
            notify_changed();
            return;
        }
    }
    notify_changed();
}

void TagManagerDialog::on_merge() {
    auto* svc = service();
    const auto* row = current_row();
    if (svc == nullptr || row == nullptr) return;
    const QString source = QString::fromStdString(row->display_name);
    QStringList targets;
    for (const auto& r : rows_) {
        if (r.name != row->name) {
            targets << QString::fromStdString(r.display_name);
        }
    }
    if (targets.isEmpty()) {
        QMessageBox::information(this, QStringLiteral("合并标签"),
                                 QStringLiteral("没有其他标签可作为合并目标"));
        return;
    }
    bool ok = false;
    const QString target = QInputDialog::getItem(
        this, QStringLiteral("合并标签"),
        QStringLiteral("将 “%1” 合并到:").arg(source), targets, 0, false,
        &ok);
    if (!ok || target.isEmpty()) return;
    std::string error;
    if (!svc->merge_tags(source.toStdString(), target.toStdString(),
                         &error)) {
        QMessageBox::critical(this, QStringLiteral("合并失败"),
                              QStringLiteral("合并标签失败: %1")
                                  .arg(QString::fromStdString(error)));
        return;
    }
    notify_changed();
}

void TagManagerDialog::on_delete_unused() {
    auto* svc = service();
    const auto* row = current_row();
    if (svc == nullptr || row == nullptr) return;
    if (row->assets + row->versions > 0) {
        QMessageBox::information(
            this, QStringLiteral("标签在使用中"),
            QStringLiteral(
                "标签 “%1” 仍关联 %2 个资产、%3 个版本，无法删除。")
                .arg(QString::fromStdString(row->display_name))
                .arg(row->assets)
                .arg(row->versions));
        return;
    }
    std::string error;
    if (!svc->delete_unused_tag(row->name, &error)) {
        QMessageBox::warning(this, QStringLiteral("删除失败"),
                             QStringLiteral("删除标签失败: %1")
                                 .arg(QString::fromStdString(error)));
        return;
    }
    notify_changed();
}

void TagManagerDialog::on_prune_unused() {
    auto* svc = service();
    if (svc == nullptr) return;
    // Count from the FULL usage table (global op — confirmation matches
    // scope), not the search-filtered rows.
    std::string error;
    const auto all = svc->tag_usage(&error);
    if (!error.empty()) {
        QMessageBox::critical(this, QStringLiteral("清理失败"),
                              QStringLiteral("读取标签使用情况失败: %1")
                                  .arg(QString::fromStdString(error)));
        return;
    }
    int unused_total = 0;
    for (const auto& info : all) {
        if (info.assets == 0 && info.versions == 0) ++unused_total;
    }
    if (unused_total == 0) {
        QMessageBox::information(this, QStringLiteral("清理无用标签"),
                                 QStringLiteral("没有可清理的无用标签"));
        return;
    }
    const auto answer = QMessageBox::question(
        this, QStringLiteral("清理全部无用标签"),
        QStringLiteral("将删除 %1 个未使用的标签，继续？")
            .arg(unused_total),
        QMessageBox::StandardButton::Yes |
            QMessageBox::StandardButton::No,
        QMessageBox::StandardButton::No);
    if (answer != QMessageBox::StandardButton::Yes) return;
    error.clear();
    const auto removed = svc->prune_unused_tags(&error);
    if (!error.empty()) {
        QMessageBox::critical(this, QStringLiteral("清理失败"),
                              QStringLiteral("清理无用标签失败: %1")
                                  .arg(QString::fromStdString(error)));
        return;
    }
    QMessageBox::information(this, QStringLiteral("清理完成"),
                             QStringLiteral("已清理 %1 个无用标签")
                                 .arg(removed.size()));
    notify_changed();
}

void TagManagerDialog::on_row_double_clicked(int row) {
    if (0 <= row && row < static_cast<int>(rows_.size())) {
        Q_EMIT tag_selected(
            QString::fromStdString(rows_[static_cast<std::size_t>(row)]
                                       .display_name));
    }
}

}  // namespace pwb::ui_pages_data::qt
