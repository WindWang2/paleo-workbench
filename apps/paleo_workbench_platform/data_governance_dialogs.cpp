// ws0 数据治理闭环 — 对话框实现。见 data_governance_dialogs.hpp。
#include "data_governance_dialogs.hpp"

#include <pwb/data/governance.hpp>
#include <pwb/data/role_registry.hpp>

#include <QCheckBox>
#include <QComboBox>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QLabel>
#include <QLineEdit>
#include <QListWidget>
#include <QMessageBox>
#include <QPushButton>
#include <QTableWidget>
#include <QVBoxLayout>

#include <algorithm>

namespace pwb::app::data_governance {

namespace gov = pwb::data::governance;

bool report_outcome(QWidget* parent, const QString& title, bool ok,
                    const std::string& error, const std::string& summary) {
    if (!ok) {
        QMessageBox::warning(
            parent, title,
            QString::fromUtf8(error.empty() ? "操作失败" : error.c_str()));
        return false;
    }
    return true;
}

namespace {

QString zh(const std::string& text) { return QString::fromUtf8(text.c_str()); }

// 词汇表（registry 顺序，中文标签）+「自定义…」项；自定义时启用输入框。
void fill_role_combo(QComboBox* combo, QLineEdit* custom,
                     const std::string& entity_type,
                     const std::string& current_role) {
    combo->blockSignals(true);
    combo->clear();
    int select = -1;
    const auto roles = pwb::data::roles_for_entity_type(entity_type);
    for (std::size_t i = 0; i < roles.size(); ++i) {
        const std::string role(roles[i]);
        const std::string display = pwb::data::role_display(roles[i]);
        combo->addItem(zh(display), QString::fromStdString(role));
        if (role == current_role) select = static_cast<int>(i);
    }
    combo->addItem(QStringLiteral("自定义…"), QStringLiteral("\x01custom"));
    combo->blockSignals(false);
    const bool custom_role =
        current_role.empty() ? false : select < 0;
    if (custom_role) {
        combo->setCurrentIndex(combo->count() - 1);
        custom->setText(QString::fromStdString(current_role));
    } else if (select >= 0) {
        combo->setCurrentIndex(select);
        custom->clear();
    } else {
        combo->setCurrentIndex(0);
        custom->clear();
    }
    custom->setEnabled(combo->currentData().toString() ==
                       QStringLiteral("\x01custom"));
}

// 组合角色输入：词汇项返回 key；自定义项返回输入框文本。
std::string combo_role_text(const QComboBox* combo, const QLineEdit* custom) {
    const QString data = combo->currentData().toString();
    if (data == QStringLiteral("\x01custom")) {
        return custom->text().toStdString();
    }
    return data.toStdString();
}

QTableWidget* make_table(const QStringList& headers) {
    auto* table = new QTableWidget;
    table->setColumnCount(headers.size());
    table->setHorizontalHeaderLabels(headers);
    table->verticalHeader()->setVisible(false);
    table->setSelectionBehavior(QAbstractItemView::SelectRows);
    table->setSelectionMode(QAbstractItemView::SingleSelection);
    table->setEditTriggers(QAbstractItemView::NoEditTriggers);
    table->horizontalHeader()->setStretchLastSection(true);
    return table;
}

}  // namespace

// ---------------------------------------------------------------------------
// LinkWellDialog
// ---------------------------------------------------------------------------

LinkWellDialog::LinkWellDialog(const std::filesystem::path& project_file,
                               const std::string& asset_id,
                               const std::string& asset_name,
                               std::function<void()> refresh_notify,
                               QWidget* parent)
    : QDialog(parent),
      project_file_(project_file),
      asset_id_(asset_id),
      refresh_notify_(std::move(refresh_notify)) {
    setWindowTitle(QStringLiteral("关联到井"));
    setModal(false);
    resize(560, 520);

    auto* layout = new QVBoxLayout(this);
    asset_label_ = new QLabel(
        QStringLiteral("资产：%1\nID：%2")
            .arg(zh(asset_name))
            .arg(QString::fromStdString(asset_id)));
    layout->addWidget(asset_label_);

    links_table_ = make_table({QStringLiteral("实体"),
                               QStringLiteral("角色"), QStringLiteral("主数据"),
                               QStringLiteral("解除")});
    links_table_->setSelectionMode(QAbstractItemView::ExtendedSelection);
    layout->addWidget(new QLabel(QStringLiteral("已有关联（选中后可解除）：")));
    layout->addWidget(links_table_);
    unlink_button_ = new QPushButton(QStringLiteral("解除选中的关联"));
    layout->addWidget(unlink_button_);
    QObject::connect(unlink_button_, &QPushButton::clicked, this, [this] {
        apply_unlink(links_table_->currentRow());
    });

    layout->addWidget(new QLabel(QStringLiteral("选择井：")));
    well_search_ = new QLineEdit;
    well_search_->setPlaceholderText(QStringLiteral("按名称/UWI/ID 过滤"));
    layout->addWidget(well_search_);
    well_list_ = new QListWidget;
    layout->addWidget(well_list_, 1);

    auto* role_row = new QHBoxLayout;
    role_combo_ = new QComboBox;
    role_custom_ = new QLineEdit;
    role_custom_->setPlaceholderText(QStringLiteral("自定义角色名"));
    role_custom_->setEnabled(false);
    primary_check_ = new QCheckBox(QStringLiteral("设为主数据（同组自动降级）"));
    role_row->addWidget(new QLabel(QStringLiteral("角色：")), 0);
    role_row->addWidget(role_combo_, 1);
    role_row->addWidget(role_custom_, 1);
    role_row->addWidget(primary_check_);
    layout->addLayout(role_row);

    auto* buttons = new QHBoxLayout;
    auto* link_button = new QPushButton(QStringLiteral("关联"));
    auto* close_button = new QPushButton(QStringLiteral("关闭"));
    buttons->addStretch(1);
    buttons->addWidget(link_button);
    buttons->addWidget(close_button);
    layout->addLayout(buttons);

    fill_role_combo(role_combo_, role_custom_, "well", "well_log");
    QObject::connect(role_combo_, &QComboBox::currentIndexChanged, this,
                     [this](int) {
                         role_custom_->setEnabled(
                             role_combo_->currentData().toString() ==
                             QStringLiteral("\x01custom"));
                     });
    QObject::connect(well_search_, &QLineEdit::textChanged, this,
                     &LinkWellDialog::rebuild_well_list);
    QObject::connect(link_button, &QPushButton::clicked, this,
                     [this] { apply_link(); });
    QObject::connect(close_button, &QPushButton::clicked, this,
                     &QDialog::reject);

    rebuild_well_list();
    reload_links();
}

void LinkWellDialog::rebuild_well_list() {
    well_list_->blockSignals(true);
    well_list_->clear();
    const QString needle = well_search_->text();
    for (const auto& well : gov::wells(project_file_)) {
        const QString label =
            QStringLiteral("%1（UWI %2 · %3）")
                .arg(zh(well.name.empty() ? well.id : well.name))
                .arg(zh(well.uwi.empty() ? "—" : well.uwi))
                .arg(QString::fromStdString(well.id));
        if (!needle.isEmpty() && !label.contains(needle, Qt::CaseInsensitive))
            continue;
        auto* item = new QListWidgetItem(label);
        item->setData(Qt::UserRole, QString::fromStdString(well.id));
        well_list_->addItem(item);
    }
    well_list_->blockSignals(false);
}

void LinkWellDialog::reload_links() {
    links_table_->setRowCount(0);
    const auto links = gov::links_for_asset(project_file_, asset_id_);
    for (const auto& link : links) {
        const int row = links_table_->rowCount();
        links_table_->insertRow(row);
        const std::string entity_name =
            gov::entity_display_name(project_file_, link.entity_type,
                                     link.entity_id);
        // 行数据携带 link id：解除时按 id 匹配最新行序，打开期间的外部
        // 增删不会错删另一条（P2：行号漂移防线）。
        auto* entity_item = new QTableWidgetItem(
            zh(entity_name.empty() ? link.entity_id : entity_name));
        entity_item->setData(Qt::UserRole,
                             QString::fromStdString(link.id));
        links_table_->setItem(row, 0, entity_item);
        links_table_->setItem(
            row, 1,
            new QTableWidgetItem(zh(pwb::data::role_display(link.role))));
        links_table_->setItem(
            row, 2, new QTableWidgetItem(
                        link.is_primary ? QStringLiteral("✓") : QString()));
    }
}

void LinkWellDialog::select_well(const std::string& well_id) {
    for (int i = 0; i < well_list_->count(); ++i) {
        if (well_list_->item(i)->data(Qt::UserRole).toString().toStdString() ==
            well_id) {
            well_list_->setCurrentRow(i);
            return;
        }
    }
}

void LinkWellDialog::set_role_input(const std::string& role) {
    fill_role_combo(role_combo_, role_custom_, "well", role);
}

void LinkWellDialog::set_primary(bool primary) {
    primary_check_->setChecked(primary);
}

bool LinkWellDialog::apply_link() {
    const auto selected = well_list_->selectedItems();
    if (selected.isEmpty()) {
        QMessageBox::information(this, QStringLiteral("关联到井"),
                                 QStringLiteral("请先在列表中选择一口井。"));
        return false;
    }
    const std::string well_id =
        selected.front()->data(Qt::UserRole).toString().toStdString();
    const std::string role = combo_role_text(role_combo_, role_custom_);
    const auto outcome = gov::link_asset(
        project_file_, "well", well_id, asset_id_, role,
        primary_check_->isChecked());
    if (!report_outcome(this, QStringLiteral("关联到井"), outcome.ok,
                        outcome.error, outcome.summary)) {
        return false;
    }
    if (refresh_notify_) refresh_notify_();
    reload_links();
    rebuild_well_list();
    Q_EMIT applied();
    Q_EMIT status_message(zh(outcome.summary));
    return true;
}

bool LinkWellDialog::apply_unlink(int row) {
    if (row < 0 || row >= links_table_->rowCount()) return false;
    const QString link_id = links_table_->item(row, 0)->data(Qt::UserRole)
                                 .toString();
    const auto links = gov::links_for_asset(project_file_, asset_id_);
    const auto it = std::find_if(
        links.begin(), links.end(),
        [&](const pwb::data::EntityLinkView& link) {
            return QString::fromStdString(link.id) == link_id;
        });
    if (it == links.end()) {
        QMessageBox::information(this, QStringLiteral("解除关联"),
                                 QStringLiteral("该链接已被移除（列表将刷新）。"));
        reload_links();
        return false;
    }
    const auto& link = *it;
    const auto outcome = gov::unlink_asset(project_file_, link.entity_type,
                                           link.entity_id, asset_id_,
                                           link.role);
    if (!report_outcome(this, QStringLiteral("解除关联"), outcome.ok,
                        outcome.error, outcome.summary)) {
        return false;
    }
    if (refresh_notify_) refresh_notify_();
    reload_links();
    Q_EMIT applied();
    Q_EMIT status_message(zh(outcome.summary));
    return true;
}

std::vector<std::string> LinkWellDialog::linked_entity_ids() const {
    std::vector<std::string> ids;
    for (const auto& link : gov::links_for_asset(project_file_, asset_id_)) {
        ids.push_back(link.entity_id);
    }
    return ids;
}

// ---------------------------------------------------------------------------
// SetRoleDialog
// ---------------------------------------------------------------------------

SetRoleDialog::SetRoleDialog(const std::filesystem::path& project_file,
                             const std::string& asset_id,
                             const std::string& asset_name,
                             std::function<void()> refresh_notify,
                             QWidget* parent)
    : QDialog(parent),
      project_file_(project_file),
      asset_id_(asset_id),
      refresh_notify_(std::move(refresh_notify)) {
    setWindowTitle(QStringLiteral("设置角色"));
    setModal(false);
    resize(520, 420);

    auto* layout = new QVBoxLayout(this);
    asset_label_ = new QLabel(
        QStringLiteral("资产：%1\nID：%2")
            .arg(zh(asset_name))
            .arg(QString::fromStdString(asset_id)));
    layout->addWidget(asset_label_);
    layout->addWidget(new QLabel(
        QStringLiteral("选择一条关联，然后设置新角色：")));
    links_table_ = make_table({QStringLiteral("实体"),
                               QStringLiteral("当前角色"),
                               QStringLiteral("主数据")});
    layout->addWidget(links_table_, 1);

    auto* role_row = new QHBoxLayout;
    role_combo_ = new QComboBox;
    role_custom_ = new QLineEdit;
    role_custom_->setPlaceholderText(QStringLiteral("自定义角色名"));
    role_custom_->setEnabled(false);
    role_row->addWidget(new QLabel(QStringLiteral("新角色：")));
    role_row->addWidget(role_combo_, 1);
    role_row->addWidget(role_custom_, 1);
    layout->addLayout(role_row);

    auto* buttons = new QHBoxLayout;
    auto* apply_button = new QPushButton(QStringLiteral("应用"));
    auto* close_button = new QPushButton(QStringLiteral("关闭"));
    buttons->addStretch(1);
    buttons->addWidget(apply_button);
    buttons->addWidget(close_button);
    layout->addLayout(buttons);

    QObject::connect(role_combo_, &QComboBox::currentIndexChanged, this,
                     [this](int) {
                         role_custom_->setEnabled(
                             role_combo_->currentData().toString() ==
                             QStringLiteral("\x01custom"));
                     });
    QObject::connect(links_table_, &QTableWidget::cellClicked, this,
                     [this](int, int) {
                         const auto links =
                             gov::links_for_asset(project_file_, asset_id_);
                         const int row = links_table_->currentRow();
                         if (row >= 0 &&
                             static_cast<std::size_t>(row) < links.size()) {
                             fill_role_combo(
                                 role_combo_, role_custom_,
                                 links[static_cast<std::size_t>(row)]
                                     .entity_type,
                                 links[static_cast<std::size_t>(row)].role);
                         }
                     });
    QObject::connect(apply_button, &QPushButton::clicked, this,
                     [this] { apply_role(); });
    QObject::connect(close_button, &QPushButton::clicked, this,
                     &QDialog::reject);

    reload_links();
    fill_role_combo(role_combo_, role_custom_, "well", "");
}

void SetRoleDialog::reload_links() {
    links_table_->setRowCount(0);
    for (const auto& link : gov::links_for_asset(project_file_, asset_id_)) {
        const int row = links_table_->rowCount();
        links_table_->insertRow(row);
        const std::string entity_name =
            gov::entity_display_name(project_file_, link.entity_type,
                                     link.entity_id);
        links_table_->setItem(
            row, 0,
            new QTableWidgetItem(zh(entity_name.empty() ? link.entity_id
                                                        : entity_name)));
        links_table_->setItem(
            row, 1,
            new QTableWidgetItem(zh(pwb::data::role_display(link.role))));
        links_table_->setItem(
            row, 2, new QTableWidgetItem(
                        link.is_primary ? QStringLiteral("✓") : QString()));
    }
}

void SetRoleDialog::select_link(int row) {
    if (row >= 0 && row < links_table_->rowCount()) {
        links_table_->selectRow(row);
        const auto links = gov::links_for_asset(project_file_, asset_id_);
        if (static_cast<std::size_t>(row) < links.size()) {
            fill_role_combo(role_combo_, role_custom_,
                            links[static_cast<std::size_t>(row)].entity_type,
                            links[static_cast<std::size_t>(row)].role);
        }
    }
}

void SetRoleDialog::set_role_input(const std::string& role) {
    const auto links = gov::links_for_asset(project_file_, asset_id_);
    const int row = links_table_->currentRow();
    const std::string entity_type =
        (row >= 0 && static_cast<std::size_t>(row) < links.size())
            ? links[static_cast<std::size_t>(row)].entity_type
            : "well";
    fill_role_combo(role_combo_, role_custom_, entity_type, role);
}

bool SetRoleDialog::apply_role() {
    const auto links = gov::links_for_asset(project_file_, asset_id_);
    const int row = links_table_->currentRow();
    if (row < 0 || static_cast<std::size_t>(row) >= links.size()) {
        QMessageBox::information(this, QStringLiteral("设置角色"),
                                 QStringLiteral("请先选择一条关联。"));
        return false;
    }
    const auto& link = links[static_cast<std::size_t>(row)];
    const std::string new_role = combo_role_text(role_combo_, role_custom_);
    const auto outcome =
        gov::set_asset_link_role(project_file_, link.entity_type,
                                 link.entity_id, asset_id_, link.role,
                                 new_role);
    if (!report_outcome(this, QStringLiteral("设置角色"), outcome.ok,
                        outcome.error, outcome.summary)) {
        return false;
    }
    if (refresh_notify_) refresh_notify_();
    reload_links();
    Q_EMIT applied();
    Q_EMIT status_message(zh(outcome.summary));
    return true;
}

// ---------------------------------------------------------------------------
// TagsDialog
// ---------------------------------------------------------------------------

TagsDialog::TagsDialog(const std::filesystem::path& project_file,
                       const std::vector<std::string>& asset_ids,
                       const std::vector<std::string>& asset_names,
                       std::function<void()> refresh_notify,
                       QWidget* parent)
    : QDialog(parent),
      project_file_(project_file),
      asset_ids_(asset_ids),
      refresh_notify_(std::move(refresh_notify)) {
    setWindowTitle(QStringLiteral("标签管理"));
    setModal(false);
    resize(480, 420);

    QString names;
    for (std::size_t i = 0; i < asset_names.size() && i < 5; ++i) {
        if (i != 0) names += QStringLiteral("、");
        names += zh(asset_names[i]);
    }
    if (asset_names.size() > 5) names += QStringLiteral(" 等 %1 项").arg(asset_names.size());

    auto* layout = new QVBoxLayout(this);
    scope_label_ = new QLabel(
        QStringLiteral("对 %1 项资产应用标签：%2")
            .arg(asset_ids.size())
            .arg(names));
    scope_label_->setWordWrap(true);
    layout->addWidget(scope_label_);

    layout->addWidget(new QLabel(QStringLiteral("当前标签（选中后可移除）：")));
    current_tags_ = new QListWidget;
    layout->addWidget(current_tags_, 1);

    auto* add_row = new QHBoxLayout;
    add_input_ = new QLineEdit;
    add_input_->setPlaceholderText(
        QStringLiteral("新标签（逗号/分号分隔多个；自动合并空白与大小写）"));
    auto* add_button = new QPushButton(QStringLiteral("添加"));
    add_row->addWidget(add_input_, 1);
    add_row->addWidget(add_button);
    layout->addLayout(add_row);

    remove_button_ = new QPushButton(
        QStringLiteral("移除选中标签（全部选中资产）"));
    layout->addWidget(remove_button_);

    auto* close_button = new QPushButton(QStringLiteral("关闭"));
    auto* close_row = new QHBoxLayout;
    close_row->addStretch(1);
    close_row->addWidget(close_button);
    layout->addLayout(close_row);

    QObject::connect(add_button, &QPushButton::clicked, this,
                     [this] { apply_add(add_input_->text().toStdString()); });
    QObject::connect(remove_button_, &QPushButton::clicked, this, [this] {
        const auto selected = current_tags_->selectedItems();
        if (selected.isEmpty()) return;
        apply_remove(selected.front()->text().toStdString());
    });
    QObject::connect(close_button, &QPushButton::clicked, this,
                     &QDialog::reject);

    reload_tags();
}

void TagsDialog::reload_tags() {
    current_tags_->clear();
    // 各资产标签的并集 + 覆盖计数（标签只由 TagStore 正规化产出）。
    std::vector<std::string> joined;
    for (const auto& per_asset : gov::tags_for_assets(project_file_,
                                                      asset_ids_)) {
        joined.insert(joined.end(), per_asset.tags.begin(),
                      per_asset.tags.end());
    }
    std::sort(joined.begin(), joined.end());
    joined.erase(std::unique(joined.begin(), joined.end()), joined.end());
    for (const auto& tag : joined) {
        auto* item = new QListWidgetItem(QString::fromStdString(tag));
        current_tags_->addItem(item);
    }
}

bool TagsDialog::apply_add(const std::string& raw_names) {
    // 分隔符：半角/全角逗号与分号；空白清理在服务层（TagStore 正规化）。
    std::string normalized = raw_names;
    for (const std::string& wide : {std::string("，"), std::string("；")}) {
        std::string::size_type pos = 0;
        while ((pos = normalized.find(wide, pos)) != std::string::npos) {
            normalized.replace(pos, wide.size(), ",");
            pos += 1;
        }
    }
    std::vector<std::string> names;
    std::string current;
    for (const char c : normalized) {
        if (c == ',' || c == ';') {
            names.push_back(current);
            current.clear();
        } else {
            current.push_back(c);
        }
    }
    names.push_back(current);
    const auto outcome = gov::add_tags(project_file_, asset_ids_, names);
    if (!report_outcome(this, QStringLiteral("标签管理"), outcome.ok,
                        outcome.error, outcome.summary)) {
        return false;
    }
    if (refresh_notify_) refresh_notify_();
    reload_tags();
    add_input_->clear();
    Q_EMIT applied();
    Q_EMIT status_message(zh(outcome.summary));
    return true;
}

bool TagsDialog::apply_remove(const std::string& tag_name) {
    const auto outcome = gov::remove_tags(project_file_, asset_ids_,
                                          tag_name);
    if (!report_outcome(this, QStringLiteral("标签管理"), outcome.ok,
                        outcome.error, outcome.summary)) {
        return false;
    }
    if (refresh_notify_) refresh_notify_();
    reload_tags();
    Q_EMIT applied();
    Q_EMIT status_message(zh(outcome.summary));
    return true;
}

// ---------------------------------------------------------------------------
// TrashDialog
// ---------------------------------------------------------------------------

TrashDialog::TrashDialog(const std::filesystem::path& project_file,
                         std::function<void()> refresh_notify,
                         QWidget* parent)
    : QDialog(parent),
      project_file_(project_file),
      refresh_notify_(std::move(refresh_notify)) {
    setWindowTitle(QStringLiteral("回收站"));
    setModal(false);
    resize(640, 380);

    auto* layout = new QVBoxLayout(this);
    layout->addWidget(new QLabel(
        QStringLiteral("已软删除的资产（原始数据保留在工程 "
                       "artifacts/trash/，恢复后关联关系继续有效）：")));
    table_ = make_table({QStringLiteral("名称"), QStringLiteral("类型"),
                         QStringLiteral("版本数"), QStringLiteral("原因"),
                         QStringLiteral("移入时间")});
    table_->setSelectionMode(QAbstractItemView::ExtendedSelection);
    layout->addWidget(table_, 1);

    auto* buttons = new QHBoxLayout;
    auto* restore_button = new QPushButton(
        QStringLiteral("恢复选中（全部版本回到数据管理）"));
    auto* refresh_button = new QPushButton(QStringLiteral("刷新"));
    auto* close_button = new QPushButton(QStringLiteral("关闭"));
    buttons->addWidget(restore_button);
    buttons->addWidget(refresh_button);
    buttons->addStretch(1);
    buttons->addWidget(close_button);
    layout->addLayout(buttons);

    QObject::connect(restore_button, &QPushButton::clicked, this,
                     [this] { restore_selected(); });
    QObject::connect(refresh_button, &QPushButton::clicked, this,
                     [this] { reload(); });
    QObject::connect(close_button, &QPushButton::clicked, this,
                     &QDialog::reject);

    reload();
}

void TrashDialog::reload() {
    entries_ = gov::trashed_assets(project_file_);
    table_->setRowCount(0);
    for (const auto& entry : entries_) {
        const int row = table_->rowCount();
        table_->insertRow(row);
        table_->setItem(row, 0,
                        new QTableWidgetItem(zh(entry.name.empty()
                                                    ? entry.asset_id
                                                    : entry.name)));
        table_->setItem(row, 1, new QTableWidgetItem(zh(entry.type)));
        table_->setItem(
            row, 2, new QTableWidgetItem(QString::number(entry.version_count)));
        table_->setItem(
            row, 3,
            new QTableWidgetItem(zh(entry.reason.empty() ? "—" : entry.reason)));
        table_->setItem(row, 4,
                        new QTableWidgetItem(zh(entry.trashed_at)));
    }
}

int TrashDialog::table_rows() const { return table_->rowCount(); }

void TrashDialog::select_row_for(const std::string& asset_id) {
    for (std::size_t i = 0; i < entries_.size(); ++i) {
        if (entries_[i].asset_id == asset_id) {
            table_->selectRow(static_cast<int>(i));
            return;
        }
    }
}

bool TrashDialog::restore_selected() {    const auto rows = table_->selectionModel()->selectedRows();
    if (rows.isEmpty()) {
        QMessageBox::information(this, QStringLiteral("回收站"),
                                 QStringLiteral("请先选择要恢复的资产。"));
        return false;
    }
    std::vector<std::string> ids;
    for (const QModelIndex& index : rows) {
        const int row = index.row();
        if (row >= 0 && static_cast<std::size_t>(row) < entries_.size()) {
            ids.push_back(entries_[static_cast<std::size_t>(row)].asset_id);
        }
    }
    const auto outcome = gov::restore_assets(project_file_, ids);
    if (!report_outcome(this, QStringLiteral("回收站"), outcome.ok,
                        outcome.error, outcome.summary)) {
        reload();  // 部分成功时如实重载
        return false;
    }
    if (refresh_notify_) refresh_notify_();
    reload();
    Q_EMIT applied();
    Q_EMIT status_message(zh(outcome.summary));
    return true;
}

}  // namespace pwb::app::data_governance
