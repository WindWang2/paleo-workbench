#include "pwb/ui_pages_mapedit/inspector_panel.hpp"

#include "pwb/domain/stage.hpp"
#include "pwb/ui_data_core/governance.hpp"
#include "pwb/ui_data_core/json_util.hpp"
#include "pwb/ui_pages_mapedit/table_preview_widget.hpp"
#include "pwb/ui_pages_mapedit/tag_widgets.hpp"
#include "pwb/ui_shell/style_registry.hpp"
#include "pwb/ui_widgets/object_table.hpp"
#include "pwb/ui_widgets/states.hpp"

#include <QAction>
#include <QApplication>
#include <QClipboard>
#include <QCursor>
#include <QDialog>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QItemSelectionModel>
#include <QLabel>
#include <QMenu>
#include <QPushButton>
#include <QScrollBar>
#include <QSizePolicy>
#include <QStringList>
#include <QTabWidget>
#include <QTreeWidget>
#include <QTreeWidgetItem>
#include <QVBoxLayout>

#include <algorithm>
#include <map>
#include <memory>

namespace pwb::ui_pages_mapedit {
namespace {

QString pal(const char* key) {
    const auto& p = ui_shell::style_palette();
    const auto it = p.find(key);
    return it != p.end() ? QString::fromStdString(it->second) : QString();
}

QString tok(const char* key) {
    const auto& p = ui_shell::style_palette();
    const auto it = p.find(key);
    return it != p.end() ? QString::fromStdString(it->second) : QString();
}

int tok_int(const char* key, int fallback) {
    bool ok = false;
    const int v = tok(key).toInt(&ok);
    return ok ? v : fallback;
}

// tokens.control_height(density): comfortable 30 / compact 26.
int control_height() {
    const auto& density = ui_shell::style_registry().current_density();
    return density == "compact" ? 26 : 30;
}

// _small_button_size(): density-aware 22px 小方按钮 (tag +/− 等).
QSize small_button_size() {
    const int side = control_height() - 6;
    return {side, side};
}

// _fit_key_value_table: key column hugs content, value column takes the
// rest; optional height cap folds rows to content.
void fit_key_value_table(TablePreviewWidget* table, bool cap_height,
                         int key_column_cap = -1, int max_height = 340) {
    QHeaderView* hdr = table->horizontalHeader();
    // 键值表不显示行号列。
    table->verticalHeader()->setVisible(false);
    if (key_column_cap < 0) {
        hdr->setSectionResizeMode(0, QHeaderView::ResizeToContents);
    } else {
        // Catalog keys can be long machine-style names; keep the key
        // header compact and stretch the value column.
        const int key_width = std::min(
            std::max(78, table->column_content_width(0) + 12),
            std::max(78, key_column_cap));
        hdr->setSectionResizeMode(0, QHeaderView::Interactive);
        table->setColumnWidth(0, key_width);
        hdr->setSectionResizeMode(1, QHeaderView::Stretch);
        hdr->setStretchLastSection(false);
    }
    if (cap_height) {
        const int height =
            hdr->sizeHint().height() + table->rowCount() * 28 +
            table->horizontalScrollBar()->sizeHint().height() +
            table->frameWidth() * 2 + 2;
        table->setMaximumHeight(std::min(height, max_height));
        // QTableView 的 sizeHint 偏小且不含行数信息——最小高度一并钉住。
        table->setMinimumHeight(std::min(height, max_height));
    }
}

}  // namespace

// --- IntegrityState → token ---------------------------------------------------

QString integrity_tone_token(ui_data_core::IntegrityState state) {
    using ui_data_core::IntegrityState;
    switch (state) {
        case IntegrityState::Verified: return QStringLiteral("SUCCESS");
        case IntegrityState::Modified: return QStringLiteral("WARNING");
        case IntegrityState::Missing: return QStringLiteral("ERROR_RED");
        case IntegrityState::Unmanaged:
        case IntegrityState::Unknown:
        default: return QStringLiteral("TEXT_SECONDARY");
    }
}

// --- VersionsTableView ---------------------------------------------------------

VersionsTableView::VersionsTableView(QWidget* parent) : QTableView(parent) {}

int VersionsTableView::rowCount() const {
    QAbstractItemModel* m = model();
    return m == nullptr ? 0 : m->rowCount();
}

int VersionsTableView::columnCount() const {
    QAbstractItemModel* m = model();
    return m == nullptr ? 0 : m->columnCount();
}

int VersionsTableView::currentRow() const {
    return currentIndex().row();
}

QString VersionsTableView::item_text(int row, int column) const {
    QAbstractItemModel* m = model();
    if (m == nullptr || row < 0 || column < 0 || row >= m->rowCount() ||
        column >= m->columnCount()) {
        return QString();
    }
    const QVariant value = m->data(m->index(row, column));
    return value.isNull() ? QString() : value.toString();
}

QString VersionsTableView::horizontal_header_text(int column) const {
    QAbstractItemModel* m = model();
    if (m == nullptr || column < 0 || column >= m->columnCount()) {
        return QString();
    }
    return m->headerData(column, Qt::Horizontal).toString();
}

// --- LineageTreeWidget ---------------------------------------------------------

LineageTreeWidget::LineageTreeWidget(QWidget* parent) : QWidget(parent) {
    auto* layout = new QVBoxLayout(this);
    const int s2 = tok_int("SPACE_2", 8);
    layout->setContentsMargins(s2, s2, s2, s2);
    layout->setSpacing(tok_int("SPACE_1", 4));

    tree = new QTreeWidget(this);
    tree->setHeaderLabel(QStringLiteral("血缘链"));
    tree->setColumnCount(1);
    tree->setSelectionMode(QTreeWidget::SingleSelection);
    tree->setEditTriggers(QTreeWidget::NoEditTriggers);
    connect(tree, &QTreeWidget::itemSelectionChanged, this,
            [this]() { on_selection(); });
    connect(tree, &QTreeWidget::itemDoubleClicked, this,
            [this](QTreeWidgetItem* item, int column) {
                on_double_clicked(item, column);
            });
    layout->addWidget(tree, 1);

    detail_label = new QLabel(
        QStringLiteral("点击节点查看版本 / 运行详情（双击版本定位数据行）"),
        this);
    detail_label->setWordWrap(true);
    detail_label->setAlignment(Qt::AlignTop | Qt::AlignLeft);
    detail_label->setObjectName(QStringLiteral("PwbStateHint"));
    detail_label->setMinimumHeight(56);
    layout->addWidget(detail_label);
}

void LineageTreeWidget::clear_chain(const QString& message) {
    tree->clear();
    selected_payload_.reset();
    detail_label->setText(message.isEmpty()
                              ? QStringLiteral("原始导入资产 / 无上游依赖")
                              : message);
}

void LineageTreeWidget::show_loading(const QString& message) {
    // V11（D1）：血缘后台遍历时的占位。
    tree->clear();
    selected_payload_.reset();
    detail_label->setText(message);
}

void LineageTreeWidget::load_chains(
    const ui_data_core::AssetView& view,
    const std::optional<catalog::LineageChain>& upstream,
    const std::optional<catalog::LineageChain>& downstream) {
    tree->clear();
    if (upstream) {
        auto* up_top = new QTreeWidgetItem(
            tree, {QStringLiteral("⬆ 上游追溯 (至 RAW 输入)")});
        up_top->setFlags(up_top->flags() & ~Qt::ItemIsSelectable);
        append_version_node(up_top, upstream->root,
                            QStringLiteral("up"));
        up_top->setExpanded(true);
        if (upstream->truncated) {
            auto* note = new QTreeWidgetItem(
                up_top,
                {QStringLiteral("… (层级/节点数达上限，已截断)")});
            note->setFlags(note->flags() & ~Qt::ItemIsSelectable);
        }
    } else {
        auto* current = new QTreeWidgetItem(
            tree,
            {QStringLiteral("■ 当前: %1 (%2)")
                 .arg(QString::fromStdString(view.name),
                      QString::fromStdString(view.current_version))});
        current->setFlags(current->flags() & ~Qt::ItemIsSelectable);
    }

    if (downstream) {
        auto* down_top = new QTreeWidgetItem(
            tree, {QStringLiteral("⬇ 下游衍生")});
        down_top->setFlags(down_top->flags() & ~Qt::ItemIsSelectable);
        for (const auto& child : downstream->root.children) {
            append_version_node(down_top, child,
                                QStringLiteral("down"));
        }
        // Stay collapsed: downstream trees can be wide.
        down_top->setExpanded(false);
        if (downstream->truncated) {
            auto* note = new QTreeWidgetItem(
                down_top, {QStringLiteral("… (已截断)")});
            note->setFlags(note->flags() & ~Qt::ItemIsSelectable);
        }
    }
    if (upstream && tree->topLevelItemCount() > 0) {
        expand_recursive(tree->topLevelItem(0));
    }
    detail_label->setText(QStringLiteral(
        "点击节点查看版本 / 运行详情（双击版本定位数据行）"));
}

void LineageTreeWidget::expand_recursive(QTreeWidgetItem* item) {
    item->setExpanded(true);
    for (int i = 0; i < item->childCount(); ++i) {
        expand_recursive(item->child(i));
    }
}

QTreeWidgetItem* LineageTreeWidget::append_version_node(
    QTreeWidgetItem* parent, const catalog::LineageChainNode& node,
    const QString& /*direction*/) {
    QString label = QStringLiteral("%1 %2 · %3 v%4")
                        .arg(QString::fromStdString(
                                 ui_data_core::stage_icon(node.stage)),
                             QString::fromStdString(node.asset_name),
                             QString::fromStdString(
                                 ui_data_core::stage_label(node.stage)))
                        .arg(node.version_number);
    if (node.trashed) {
        label += QStringLiteral(" ✕回收站");
    }
    auto* item = new QTreeWidgetItem(parent, {label});
    QVariantMap payload{
        {QStringLiteral("kind"), QStringLiteral("version")},
        {QStringLiteral("version_id"),
         QString::fromStdString(node.version_id)},
        {QStringLiteral("asset_id"),
         QString::fromStdString(node.asset_id)},
        {QStringLiteral("asset_name"),
         QString::fromStdString(node.asset_name)},
        {QStringLiteral("stage"),
         QString::fromStdString(
             std::string(domain::to_string(node.stage)))},
        {QStringLiteral("version_number"), node.version_number},
        {QStringLiteral("path"), QString::fromStdString(node.path)},
        {QStringLiteral("sha256"),
         node.sha256 ? QString::fromStdString(*node.sha256) : QString()},
        {QStringLiteral("created_at"),
         QString::fromStdString(node.created_at)},
        {QStringLiteral("managed"), node.managed},
        {QStringLiteral("trashed"), node.trashed},
        {QStringLiteral("tags"), [&node] {
             QStringList out;
             for (const auto& t : node.tags) {
                 out.append(QString::fromStdString(t));
             }
             return out;
         }()},
        {QStringLiteral("run_id"),
         node.run_id ? QString::fromStdString(*node.run_id) : QString()},
        {QStringLiteral("run_operation"),
         node.run_operation ? QString::fromStdString(*node.run_operation)
                            : QString()},
        {QStringLiteral("run_status"),
         node.run_status ? QString::fromStdString(*node.run_status)
                         : QString()},
        {QStringLiteral("run_generator"),
         node.run_generator ? QString::fromStdString(*node.run_generator)
                            : QString()},
    };
    item->setData(0, Qt::UserRole,
                  QVariantList{QStringLiteral("version"), payload});
    // Children: the producing run sits between the version and its linked
    // versions, mirroring OUTPUT → Run → INPUT semantics.
    QTreeWidgetItem* holder = item;
    if (node.run_operation) {
        auto* run_item = new QTreeWidgetItem(
            item, {QStringLiteral("⚙ %1 (run)")
                       .arg(QString::fromStdString(*node.run_operation))});
        QVariantMap run_payload{
            {QStringLiteral("kind"), QStringLiteral("run")},
            {QStringLiteral("run_id"),
             node.run_id ? QString::fromStdString(*node.run_id)
                         : QString()},
            {QStringLiteral("operation"),
             QString::fromStdString(*node.run_operation)},
            {QStringLiteral("status"),
             node.run_status ? QString::fromStdString(*node.run_status)
                             : QString()},
            {QStringLiteral("generator"),
             node.run_generator ? QString::fromStdString(*node.run_generator)
                                : QString()},
            {QStringLiteral("output_version_id"),
             QString::fromStdString(node.version_id)},
        };
        run_item->setData(
            0, Qt::UserRole,
            QVariantList{QStringLiteral("run"), run_payload});
        holder = run_item;
    }
    for (const auto& child : node.children) {
        append_version_node(holder, child, QStringLiteral("up"));
    }
    return item;
}

void LineageTreeWidget::on_selection() {
    const auto items = tree->selectedItems();
    if (items.isEmpty()) {
        selected_payload_.reset();
        return;
    }
    const QVariant payload = items.first()->data(0, Qt::UserRole);
    const auto pair = payload.toList();
    if (pair.size() < 2) {
        detail_label->setText(QString());
        return;
    }
    Payload selected{pair[0].toString(), pair[1].toMap()};
    selected_payload_ = selected;
    const QVariantMap& data = selected.data;
    if (selected.kind == QLatin1String("version")) {
        QString checksum = data.value(QStringLiteral("sha256")).toString();
        if (checksum.isEmpty()) {
            checksum = QStringLiteral("无");
        }
        if (checksum.size() > 16) {
            checksum = checksum.left(12) + QStringLiteral("…");
        }
        const QString tags =
            data.value(QStringLiteral("tags")).toStringList()
                .join(QStringLiteral("、"));
        const QString run =
            data.value(QStringLiteral("run_operation")).toString();
        detail_label->setText(QStringLiteral(
            "版本 %1 v%2 · 阶段 %3\n路径: %4\n校验和: %5 · 标签: %6 · 生成 Run: %7")
                .arg(data.value(QStringLiteral("asset_name")).toString())
                .arg(data.value(QStringLiteral("version_number")).toInt())
                .arg(data.value(QStringLiteral("stage")).toString())
                .arg(data.value(QStringLiteral("path")).toString().isEmpty()
                         ? QStringLiteral("—")
                         : data.value(QStringLiteral("path")).toString())
                .arg(checksum)
                .arg(tags.isEmpty() ? QStringLiteral("—") : tags)
                .arg(run.isEmpty() ? QStringLiteral("—") : run));
    } else {
        detail_label->setText(QStringLiteral(
            "Run %1 · 状态 %2 · generator %3\nid: %4")
                .arg(data.value(QStringLiteral("operation")).toString())
                .arg(data.value(QStringLiteral("status")).toString().isEmpty()
                         ? QStringLiteral("—")
                         : data.value(QStringLiteral("status")).toString())
                .arg(data.value(QStringLiteral("generator")).toString().isEmpty()
                         ? QStringLiteral("—")
                         : data.value(QStringLiteral("generator")).toString())
                .arg(data.value(QStringLiteral("run_id")).toString()));
    }
}

void LineageTreeWidget::on_double_clicked(QTreeWidgetItem* item,
                                          int /*column*/) {
    const auto pair = item->data(0, Qt::UserRole).toList();
    if (pair.size() < 2) {
        return;
    }
    if (pair[0].toString() == QLatin1String("version")) {
        const QVariantMap data = pair[1].toMap();
        emit version_activated(
            data.value(QStringLiteral("version_id")).toString(),
            data.value(QStringLiteral("asset_id")).toString());
    }
}

// --- InspectorPanel -----------------------------------------------------------

InspectorPanel::~InspectorPanel() = default;

InspectorPanel::InspectorPanel(QWidget* parent) : QFrame(parent) {
    setObjectName(QStringLiteral("InspectorPanel"));
    ui_shell::style_bind(this, [] {
        return QStringLiteral(
                   "QFrame#InspectorPanel { background: %1;"
                   " border: 1px solid %2; border-radius: %3px; }")
            .arg(pal("BG_SIDEBAR"), pal("BORDER"), tok("RADIUS_CARD"));
    });

    auto* layout = new QVBoxLayout(this);
    const int s2 = tok_int("SPACE_2", 8);
    layout->setContentsMargins(s2, s2, s2, s2);
    layout->setSpacing(tok_int("SPACE_1", 4));

    title_label = new QLabel(QStringLiteral("数据资产检查器"), this);
    title_label->setObjectName(QStringLiteral("PwbSectionHeader"));
    layout->addWidget(title_label);

    empty_label = new QLabel(QStringLiteral("请从列表中选择数据资产"), this);
    empty_label->setObjectName(QStringLiteral("EmptyStateLabel"));
    empty_label->setAlignment(Qt::AlignCenter);
    ui_shell::style_bind(empty_label, [] {
        return QStringLiteral("color: %1; font-size: %2; margin: 20px;")
            .arg(pal("TEXT_SECONDARY"), tok("FONT_SIZE_BASE"));
    });
    layout->addWidget(empty_label);

    tabs = new QTabWidget(this);
    tabs->setObjectName(QStringLiteral("InspectorTabs"));
    ui_shell::style_bind(tabs, [] {
        return QStringLiteral(
                   "QTabWidget::pane { border: 1px solid %1;"
                   " border-radius: %2px; background: %3; }"
                   " QTabBar::tab { padding: 4px 10px; font-size: %4;"
                   " font-weight: 500; color: %5; }"
                   " QTabBar::tab:selected { color: %6;"
                   " border-bottom: 2px solid %6; font-weight: 600; }")
            .arg(pal("BORDER"), tok("RADIUS_CARD"), pal("BG_BODY"),
                 tok("FONT_SIZE_STATUS"), pal("TEXT_SECONDARY"),
                 pal("PRIMARY"));
    });

    // Tab 1: 概要 Overview（表高贴合内容，下方不拖出空白网格）
    auto* overview_tab = new QWidget(tabs);
    auto* overview_layout = new QVBoxLayout(overview_tab);
    overview_layout->setContentsMargins(s2, s2, s2, s2);
    overview_layout->setSpacing(tok_int("SPACE_1", 4));
    overview_table = new TablePreviewWidget(overview_tab);
    overview_layout->addWidget(overview_table);
    overview_layout->addStretch(1);
    tabs->addTab(overview_tab, QStringLiteral("概要"));

    // Tab 2: 元数据 Metadata (治理信息 + 目录元数据 + 解析摘要)
    auto* metadata_tab = new QWidget(tabs);
    auto* metadata_layout = new QVBoxLayout(metadata_tab);
    metadata_layout->setContentsMargins(s2, s2, s2, s2);
    metadata_layout->setSpacing(tok_int("SPACE_1", 4));

    auto* governance_header_label = new QLabel(
        QStringLiteral(
            "治理信息 (来源 / 区域 / 负责人 / 学科 / 可信等级 / 审核状态):"),
        metadata_tab);
    governance_header_label->setObjectName(QStringLiteral("WorkFieldLabel"));
    governance_header_label->setMinimumWidth(0);
    governance_header_label->setSizePolicy(QSizePolicy::Expanding,
                                           QSizePolicy::Preferred);
    governance_table = new TablePreviewWidget(metadata_tab);
    governance_edit_btn =
        new QPushButton(QStringLiteral("编辑"), metadata_tab);
    governance_edit_btn->setObjectName(QStringLiteral("GovernanceEditLink"));
    governance_edit_btn->setAccessibleName(
        QStringLiteral("编辑治理信息"));
    ui_shell::style_track_control_height(governance_edit_btn);
    governance_edit_btn->setSizePolicy(QSizePolicy::Fixed,
                                       QSizePolicy::Fixed);
    ui_shell::style_bind(governance_edit_btn, [] {
        return QStringLiteral(
                   "QPushButton#GovernanceEditLink {"
                   " color: %1; background: transparent;"
                   " border: 1px solid transparent; border-radius: %2px;"
                   " font-size: %3; font-weight: 400; padding: 0 3px;"
                   " min-width: 28px; }"
                   " QPushButton#GovernanceEditLink:hover {"
                   " color: %4; background: %5; }"
                   " QPushButton#GovernanceEditLink:focus {"
                   " color: %4; border-color: %4; }")
            .arg(pal("TEXT_SECONDARY"), tok("RADIUS_BUTTON"),
                 tok("FONT_SIZE_STATUS"), pal("PRIMARY"),
                 pal("BG_SELECTION"));
    });
    governance_edit_btn->setToolTip(QStringLiteral(
        "编辑标准治理字段（写入数据目录，受控词表校验）"));
    connect(governance_edit_btn, &QPushButton::clicked, this,
            [this]() { on_governance_edit_clicked(); });
    // 把紧邻的编辑动作收进标题行。
    governance_header_layout_ = new QHBoxLayout();
    governance_header_layout_->setContentsMargins(0, 0, 0, 0);
    governance_header_layout_->setSpacing(s2);
    governance_header_layout_->addWidget(governance_header_label, 1);
    governance_header_layout_->addWidget(governance_edit_btn, 0);
    metadata_layout->addLayout(governance_header_layout_);
    metadata_layout->addWidget(governance_table);

    auto* cat_hdr = new QLabel(QStringLiteral("目录元数据 (Catalog):"),
                               metadata_tab);
    ui_shell::style_bind(cat_hdr, [] {
        return QStringLiteral("color: %1; font-size: %2;")
            .arg(pal("TEXT_SECONDARY"), tok("FONT_SIZE_STATUS"));
    });
    metadata_layout->addWidget(cat_hdr);
    catalog_metadata_table = new TablePreviewWidget(metadata_tab);
    metadata_layout->addWidget(catalog_metadata_table);

    auto* parsed_hdr =
        new QLabel(QStringLiteral("解析摘要 (Parsed Summary):"),
                   metadata_tab);
    ui_shell::style_bind(parsed_hdr, [] {
        return QStringLiteral("color: %1; font-size: %2;")
            .arg(pal("TEXT_SECONDARY"), tok("FONT_SIZE_STATUS"));
    });
    metadata_layout->addWidget(parsed_hdr);
    metadata_table = new TablePreviewWidget(metadata_tab);
    metadata_layout->addWidget(metadata_table);
    metadata_layout->addStretch(1);
    tabs->addTab(metadata_tab, QStringLiteral("元数据"));

    // Tab 3: 标签 Tags
    tags_widget = new QWidget(tabs);
    auto* tags_layout = new QVBoxLayout(tags_widget);
    tags_layout->setContentsMargins(s2, s2, s2, s2);
    tags_layout->setSpacing(s2);
    auto* tags_hdr = new QLabel(QStringLiteral("资产关联标签:"), tags_widget);
    ui_shell::style_bind(tags_hdr, [] {
        return QStringLiteral("color: %1; font-size: %2;")
            .arg(pal("TEXT_SECONDARY"), tok("FONT_SIZE_BASE"));
    });
    tags_layout->addWidget(tags_hdr);

    tag_container = new TagContainerWidget(true, tags_widget);
    connect(tag_container, &TagContainerWidget::tag_added, this,
            [this](const QString& name) { on_tag_added(name); });
    connect(tag_container, &TagContainerWidget::tag_removed, this,
            [this](const QString& name) { on_tag_removed(name); });
    tags_layout->addWidget(tag_container);
    tags_layout->addStretch();
    tabs->addTab(tags_widget, QStringLiteral("标签"));

    // Tab 4: 版本 Versions
    auto* version_tab = new QWidget(tabs);
    auto* version_layout = new QVBoxLayout(version_tab);
    version_layout->setContentsMargins(s2, s2, s2, s2);
    version_layout->setSpacing(tok_int("SPACE_1", 4));

    // Rows are the VersionView index: QVariantMap{"version_id", "row"}.
    // Column values resolve via the bound AssetView's versions vector.
    const auto ver_at = [this](const QVariant& row)
        -> const ui_data_core::VersionView* {
        const int r = row.toMap().value(QStringLiteral("row")).toInt();
        if (current_view_ && r >= 0 &&
            r < static_cast<int>(current_view_->versions.size())) {
            return &current_view_->versions[r];
        }
        return nullptr;
    };
    versions_model_ = new ui_widgets::ObjectTableModel(
        {ui_widgets::ColumnSpec{
             QStringLiteral("version"), QStringLiteral("版本"),
             [ver_at](const QVariant& row) -> QVariant {
                 const auto* ver = ver_at(row);
                 if (ver == nullptr) return QString();
                 return ver->is_current
                            ? QStringLiteral("★ %1").arg(QString::fromStdString(
                                  ver->version_id))
                            : QString::fromStdString(ver->version_id);
             }},
         ui_widgets::ColumnSpec{
             QStringLiteral("stage"), QStringLiteral("生命阶段"),
             [ver_at](const QVariant& row) -> QVariant {
                 const auto* ver = ver_at(row);
                 return ver == nullptr ? QString()
                                       : QString::fromStdString(
                                             ui_data_core::stage_label(
                                                 ver->stage));
             }},
         ui_widgets::ColumnSpec{
             QStringLiteral("checksum"), QStringLiteral("校验和"),
             [ver_at](const QVariant& row) -> QVariant {
                 const auto* ver = ver_at(row);
                 return ver == nullptr
                            ? QString()
                            : QString::fromStdString(ver->checksum_display());
             }},
         ui_widgets::ColumnSpec{
             QStringLiteral("created"), QStringLiteral("时间"),
             [ver_at](const QVariant& row) -> QVariant {
                 const auto* ver = ver_at(row);
                 return ver == nullptr
                            ? QString()
                            : QString::fromStdString(ver->created_at);
             }},
         ui_widgets::ColumnSpec{
             QStringLiteral("tags"), QStringLiteral("标签"),
             [ver_at](const QVariant& row) -> QVariant {
                 const auto* ver = ver_at(row);
                 if (ver == nullptr) return QString();
                 if (ver->tags.empty()) return QStringLiteral("—");
                 QStringList out;
                 for (const auto& t : ver->tags) {
                     out.append(QString::fromStdString(t));
                 }
                 return out.join(QStringLiteral("、"));
             }}},
        [](const QVariant& row) {
            return row.toMap().value(QStringLiteral("version_id"))
                .toString();
        },
        this);
    versions_table = new VersionsTableView(version_tab);
    versions_table->setModel(versions_model_);
    ui_widgets::bind_table_defaults(versions_table);
    versions_table->setSelectionMode(QTableView::SingleSelection);
    versions_table->horizontalHeader()->setSectionResizeMode(
        QHeaderView::Stretch);
    versions_table->verticalHeader()->setDefaultSectionSize(28);
    connect(versions_table->selectionModel(),
            &QItemSelectionModel::selectionChanged, this,
            [this](const QItemSelection&, const QItemSelection&) {
                on_version_selection_changed();
            });
    versions_selection_ =
        std::make_unique<ui_widgets::StableSelection>(versions_table);
    // 表高贴合内容：版本少时不向下拖出大片空白网格。
    version_layout->addWidget(versions_table, 0);

    // Version tag editor (F6): +/- on the selected version row.
    version_tags_bar = new QWidget(version_tab);
    auto* tag_row = new QHBoxLayout(version_tags_bar);
    tag_row->setContentsMargins(0, 0, 0, 0);
    tag_row->setSpacing(tok_int("SPACE_1", 4));
    version_tags_hint =
        new QLabel(QStringLiteral("版本标签:"), version_tags_bar);
    version_tags_hint->setObjectName(QStringLiteral("WorkFieldLabel"));
    tag_row->addWidget(version_tags_hint);
    version_tag_add_btn =
        new QPushButton(QStringLiteral("+"), version_tags_bar);
    version_tag_add_btn->setObjectName(QStringLiteral("SecondaryButton"));
    version_tag_add_btn->setFixedSize(small_button_size());
    version_tag_add_btn->setToolTip(QStringLiteral("为选中版本添加标签"));
    connect(version_tag_add_btn, &QPushButton::clicked, this,
            [this]() { on_version_tag_add(); });
    tag_row->addWidget(version_tag_add_btn);
    version_tag_remove_btn =
        new QPushButton(QStringLiteral("−"), version_tags_bar);
    version_tag_remove_btn->setObjectName(QStringLiteral("SecondaryButton"));
    version_tag_remove_btn->setFixedSize(small_button_size());
    version_tag_remove_btn->setToolTip(
        QStringLiteral("移除选中版本的标签"));
    connect(version_tag_remove_btn, &QPushButton::clicked, this,
            [this]() { on_version_tag_remove(); });
    tag_row->addWidget(version_tag_remove_btn);
    tag_row->addStretch();
    version_layout->addWidget(version_tags_bar);
    version_tags_bar->setVisible(false);

    // RAW → DERIVED: derive an editable copy of the selected RAW asset.
    create_derived_btn =
        new QPushButton(QStringLiteral("创建派生副本"), version_tab);
    create_derived_btn->setObjectName(QStringLiteral("SecondaryButton"));
    ui_shell::style_track_control_height(create_derived_btn);
    connect(create_derived_btn, &QPushButton::clicked, this,
            [this]() { on_create_derived_clicked(); });
    version_layout->addWidget(create_derived_btn);
    create_derived_hint = new QLabel(QString(), version_tab);
    create_derived_hint->setObjectName(QStringLiteral("WorkFieldLabel"));
    create_derived_hint->setWordWrap(true);
    version_layout->addWidget(create_derived_hint);
    version_layout->addStretch(1);

    tabs->addTab(version_tab, QStringLiteral("版本"));

    // Tab 5: 血缘 Lineage (full upstream/downstream tree)
    lineage_tree = new LineageTreeWidget(tabs);
    connect(lineage_tree, &LineageTreeWidget::version_activated, this,
            [this](const QString& vid, const QString& aid) {
                emit lineage_version_activated(vid, aid);
            });
    tabs->addTab(lineage_tree, QStringLiteral("血缘"));

    // Tab 6: 完整性 Integrity
    integrity_widget = new QWidget(tabs);
    auto* int_layout = new QVBoxLayout(integrity_widget);
    int_layout->setContentsMargins(s2, s2, s2, s2);
    int_layout->setSpacing(s2);

    integrity_status_lbl =
        new QLabel(QStringLiteral("状态: 未校验"), integrity_widget);
    ui_shell::style_bind(integrity_status_lbl, [this] {
        return render_integrity_status_sheet();
    });
    int_layout->addWidget(integrity_status_lbl);

    auto* hash_box = new QHBoxLayout();
    hash_label = new QLabel(QStringLiteral("SHA-256: —"), integrity_widget);
    hash_label->setWordWrap(true);
    ui_shell::style_bind(hash_label, [] {
        return QStringLiteral(
                   "font-family: monospace; font-size: %1; color: %2;")
            .arg(tok("FONT_SIZE_STATUS"), pal("TEXT_SECONDARY"));
    });
    hash_box->addWidget(hash_label, 1);

    copy_hash_btn =
        new QPushButton(QStringLiteral("复制 Hash"), integrity_widget);
    copy_hash_btn->setObjectName(QStringLiteral("SecondaryButton"));
    ui_shell::style_track_control_height(copy_hash_btn);
    connect(copy_hash_btn, &QPushButton::clicked, this,
            [this]() { copy_hash(); });
    hash_box->addWidget(copy_hash_btn);
    int_layout->addLayout(hash_box);

    verify_btn = new QPushButton(QStringLiteral("立即校验完整性"),
                                 integrity_widget);
    verify_btn->setObjectName(QStringLiteral("PrimaryButton"));
    connect(verify_btn, &QPushButton::clicked, this,
            [this]() { on_verify_clicked(); });
    int_layout->addWidget(verify_btn);
    int_layout->addStretch();
    tabs->addTab(integrity_widget, QStringLiteral("完整性"));

    layout->addWidget(tabs, 1);
    tabs->hide();
}

const ui_data_core::VersionView* InspectorPanel::selected_version() const {
    if (current_view_ && selected_version_row_ >= 0 &&
        selected_version_row_ <
            static_cast<int>(current_view_->versions.size())) {
        return &current_view_->versions[selected_version_row_];
    }
    return nullptr;
}

void InspectorPanel::update_asset(
    const ui_data_core::AssetHandle& asset,
    const std::optional<catalog::LineageChain>& lineage_up,
    const std::optional<catalog::LineageChain>& lineage_down) {
    current_asset_ = asset;
    if (!asset) {
        clear_asset();
        return;
    }

    empty_label->hide();
    tabs->show();

    current_view_ = ui_data_core::asset_view_from_object(asset);
    const ui_data_core::AssetView& view = *current_view_;
    title_label->setText(QStringLiteral("%1 %2").arg(
        QString::fromStdString(ui_data_core::stage_icon(view.stage)),
        QString::fromStdString(view.name)));

    populate_overview(view);
    populate_metadata(view);
    populate_tags(view);
    populate_versions(view);
    populate_lineage(view, lineage_up, lineage_down);
    populate_integrity(view);
}

void InspectorPanel::clear_asset() {
    current_asset_.reset();
    current_view_.reset();
    selected_version_row_ = -1;
    tabs->hide();
    empty_label->show();
    title_label->setText(QStringLiteral("数据资产检查器"));
    sync_derived_controls(nullptr);
}

void InspectorPanel::show_lineage_loading() {
    // V11（D1）：血缘在后台遍历时的占位（选择切换即刻可见）。
    if (!current_view_) {
        return;
    }
    lineage_tree->show_loading();
}

void InspectorPanel::update_lineage(
    const std::optional<catalog::LineageChain>& lineage_up,
    const std::optional<catalog::LineageChain>& lineage_down) {
    // V11（D1）：血缘异步返回后仅刷新血缘 tab。
    if (!current_view_) {
        return;
    }
    populate_lineage(*current_view_, lineage_up, lineage_down);
}

void InspectorPanel::populate_overview(
    const ui_data_core::AssetView& view) {
    std::vector<std::pair<QString, QString>> rows = {
        {QStringLiteral("逻辑名称"), QString::fromStdString(view.name)},
        {QStringLiteral("类型"), QString::fromStdString(view.type_label)},
        {QStringLiteral("格式"), QString::fromStdString(view.format)},
        {QStringLiteral("生命阶段"),
         QStringLiteral("%1 %2").arg(
             QString::fromStdString(ui_data_core::stage_icon(view.stage)),
             QString::fromStdString(
                 ui_data_core::stage_label(view.stage)))},
        {QStringLiteral("当前版本"),
         QString::fromStdString(view.current_version)},
        {QStringLiteral("管理方式"),
         view.managed ? QStringLiteral("受管 (Managed)")
                      : QStringLiteral("外部 (External)")},
        {QStringLiteral("完整性状态"),
         QStringLiteral("%1 %2").arg(
             QString::fromStdString(ui_data_core::integrity_state_icon(
                 view.integrity_state)),
             QString::fromStdString(ui_data_core::integrity_state_label(
                 view.integrity_state)))},
        {QStringLiteral("路径"), QString::fromStdString(view.path)},
        {QStringLiteral("大小"),
         QString::fromStdString(view.size_formatted)},
        {QStringLiteral("修改时间"),
         QString::fromStdString(view.modified_at)},
        {QStringLiteral("数据源"), QString::fromStdString(view.source)},
    };
    if (view.trashed) {
        rows.insert(rows.begin() + 1,
                    {QStringLiteral("回收站状态"),
                     QString::fromStdString(view.trashed_label())});
    }
    if (view.crs) {
        rows.emplace_back(QStringLiteral("CRS"),
                          QString::fromStdString(*view.crs));
    }
    // V13 W-M：反向定位——这个资产被哪些地图内容引用（派生投影）。
    const auto usage_rows = map_usage_rows(view);
    rows.insert(rows.end(), usage_rows.begin(), usage_rows.end());
    QStringList headers{QStringLiteral("属性"), QStringLiteral("值")};
    std::vector<QStringList> body;
    body.reserve(rows.size());
    for (const auto& [k, v] : rows) {
        body.push_back({k, v});
    }
    overview_table->load_table(headers, body);
    // 概要行数较多（11+），上限放宽到 520。
    fit_key_value_table(overview_table, true, -1, 520);
}

std::vector<std::pair<QString, QString>> InspectorPanel::map_usage_rows(
    const ui_data_core::AssetView& view) const {
    std::vector<std::pair<QString, QString>> rows;
    if (!map_usage_provider_) {
        return rows;
    }
    const QString asset_id = QString::fromStdString(view.id);
    if (asset_id.isEmpty()) {
        return rows;
    }
    QVariantMap report;
    try {
        report = map_usage_provider_(asset_id);
    } catch (...) {
        return rows;  // Python ``except Exception: return []`` parity
    }
    const auto usages = report.value(QStringLiteral("usages")).toList();
    if (usages.isEmpty()) {
        return rows;
    }
    QStringList layers, products;
    for (const auto& u : usages) {
        const auto m = u.toMap();
        const QString label =
            m.value(QStringLiteral("label")).toString();
        if (m.value(QStringLiteral("kind")).toString() ==
            QLatin1String("layer")) {
            layers.append(label);
        } else {
            products.append(label);
        }
    }
    const auto join_head = [](const QStringList& items) {
        const auto head = items.mid(0, 3);
        return head.join(QStringLiteral("、")) +
               (items.size() > 3 ? QStringLiteral("…") : QString());
    };
    if (!layers.isEmpty()) {
        rows.emplace_back(QStringLiteral("编图图层引用"),
                          QStringLiteral("%1 个（%2）")
                              .arg(layers.size())
                              .arg(join_head(layers)));
    }
    if (!products.isEmpty()) {
        rows.emplace_back(QStringLiteral("地图产品/输入集"),
                          QStringLiteral("%1 个（%2）")
                              .arg(products.size())
                              .arg(join_head(products)));
    }
    if (report.value(QStringLiteral("truncated")).toBool()) {
        rows.emplace_back(QStringLiteral("用途提示"),
                          QStringLiteral("（结果有截断）"));
    }
    return rows;
}

void InspectorPanel::populate_metadata(
    const ui_data_core::AssetView& view) {
    // 治理信息 (GOVERNANCE_KEYS order, display-mapped values).
    std::vector<QStringList> gov_rows;
    const auto gov = ui_data_core::governance_display_rows(
        [&view] {
            domain::Json obj = domain::Json::object();
            for (const auto& [k, v] : view.governance) {
                obj[k] = v;
            }
            return obj;
        }());
    for (const auto& [label, value] : gov) {
        gov_rows.push_back({QString::fromStdString(label),
                            QString::fromStdString(value)});
    }
    if (gov_rows.empty()) {
        gov_rows.push_back({QStringLiteral("提示"),
                            QStringLiteral("未填写（点击下方按钮编辑）")});
    }
    governance_table->load_table(
        {QStringLiteral("字段"), QStringLiteral("值")}, gov_rows);
    fit_key_value_table(governance_table, true, 156);

    // 目录元数据 (Catalog): sorted keys minus governance keys.
    std::vector<QStringList> catalog_rows;
    if (view.catalog_metadata.is_object()) {
        const auto& gov_keys = ui_data_core::governance_keys();
        for (const auto& [key, value] : view.catalog_metadata.items()) {
            if (std::find(gov_keys.begin(), gov_keys.end(), key) !=
                gov_keys.end()) {
                continue;
            }
            catalog_rows.push_back(
                {QString::fromStdString(key),
                 QString::fromStdString(ui_data_core::python_str(value))});
        }
    }
    if (catalog_rows.empty()) {
        catalog_rows.push_back({QStringLiteral("提示"),
                                QStringLiteral("暂无目录扩展元数据")});
    }
    catalog_metadata_table->load_table(
        {QStringLiteral("属性"), QStringLiteral("值")}, catalog_rows);
    fit_key_value_table(catalog_metadata_table, true, 156);

    // 解析摘要 (Parsed Summary) — label mapping + display conversion.
    static const std::map<std::string, QString> parsed_labels = {
        {"geojson_valid", QStringLiteral("GeoJSON 有效")},
        {"geojson_error", QStringLiteral("GeoJSON 错误")},
        {"feature_count", QStringLiteral("要素数量")},
        {"geometry_types", QStringLiteral("几何类型")},
        {"geojson_layer_role", QStringLiteral("图层角色")},
        {"geojson_layer_label", QStringLiteral("图层层级")},
        {"geojson_layer_level", QStringLiteral("层级序号")},
        {"facies_product_source_id", QStringLiteral("工具成果 ID")},
        {"facies_product_group_id", QStringLiteral("成果组 ID")},
        {"facies_product_complete", QStringLiteral("三层成果完整")},
        {"facies_product_layer_count", QStringLiteral("成果图层数")},
    };
    static const std::map<std::string, QString> role_labels = {
        {"facies", QStringLiteral("相")},
        {"subfacies", QStringLiteral("亚相")},
        {"microfacies", QStringLiteral("微相")},
    };
    const auto display_parsed_value = [](const std::string& key,
                                                     const domain::Json& v) {
        if (v.is_boolean()) {
            return v.get<bool>() ? QStringLiteral("是")
                                 : QStringLiteral("否");
        }
        if (key == "geojson_layer_role") {
            const auto s = ui_data_core::python_str(v);
            const auto it = role_labels.find(s);
            return it != role_labels.end() ? it->second
                                           : QString::fromStdString(s);
        }
        if (v.is_array()) {
            QStringList parts;
            for (const auto& item : v) {
                parts.append(QString::fromStdString(
                    ui_data_core::python_str(item)));
            }
            return parts.isEmpty() ? QStringLiteral("—")
                                   : parts.join(QStringLiteral("、"));
        }
        return QString::fromStdString(ui_data_core::python_str(v));
    };
    std::vector<QStringList> rows;
    if (view.parsed_summary.is_object()) {
        for (const auto& [k, v] : view.parsed_summary.items()) {
            const auto it = parsed_labels.find(k);
            rows.push_back(
                {it != parsed_labels.end() ? it->second
                                          : QString::fromStdString(k),
                 display_parsed_value(k, v)});
        }
    }
    if (rows.empty()) {
        rows.push_back({QStringLiteral("提示"),
                        QStringLiteral("暂无附加解析元数据")});
    }
    metadata_table->load_table(
        {QStringLiteral("属性"), QStringLiteral("值")}, rows);
    fit_key_value_table(metadata_table, true, 156);
}

void InspectorPanel::set_governance_enabled(bool enabled) {
    // Governance editing needs an active catalog (page toggles it).
    governance_edit_btn->setEnabled(enabled);
    governance_edit_btn->setVisible(true);
}

void InspectorPanel::on_governance_edit_clicked() {
    if (current_view_) {
        emit governance_edit_requested(*current_view_);
    }
}

void InspectorPanel::populate_tags(const ui_data_core::AssetView& view) {
    QStringList tags;
    for (const auto& t : view.tags) {
        tags.append(QString::fromStdString(t));
    }
    tag_container->set_tags(tags);
}

void InspectorPanel::populate_versions(const ui_data_core::AssetView& view) {
    selected_version_row_ = -1;
    // 差分重置（键 = version id）+ 按键恢复选择。
    const auto keys = versions_selection_->capture();
    const QString current_key = versions_model_->key_for_index(
        versions_table->currentIndex());
    std::vector<QVariant> rows;
    rows.reserve(view.versions.size());
    int row_index = 0;
    for (const auto& ver : view.versions) {
        rows.push_back(QVariantMap{
            {QStringLiteral("version_id"),
             QString::fromStdString(ver.version_id)},
            {QStringLiteral("row"), row_index++},
        });
    }
    versions_model_->set_rows(rows);
    versions_selection_->restore(keys, current_key);
    // Re-filling does not re-emit selection when the same key stays
    // current — re-derive so version-tag controls keep working.
    const int row = versions_table->currentRow();
    if (row >= 0 && row < static_cast<int>(view.versions.size())) {
        selected_version_row_ = row;
    }
    // 表高贴合内容（含表头与可能的水平滚动条），上限 340px。
    QHeaderView* hdr = versions_table->horizontalHeader();
    const int height = hdr->sizeHint().height() +
                       static_cast<int>(view.versions.size()) * 28 +
                       versions_table->horizontalScrollBar()
                           ->sizeHint()
                           .height() +
                       versions_table->frameWidth() * 2 + 2;
    versions_table->setMaximumHeight(std::min(std::max(height, 60), 340));
    sync_version_tag_controls();
    sync_derived_controls(&view);
}

// --- Version tags (F6) ---------------------------------------------------------

void InspectorPanel::set_version_tags_enabled(bool enabled) {
    // Enable/hide the version tag editor (needs an active catalog).
    version_tags_enabled_ = enabled;
    sync_version_tag_controls();
}

void InspectorPanel::on_version_selection_changed() {
    const int row = versions_table->currentRow();
    if (!current_view_ || row < 0 ||
        row >= static_cast<int>(current_view_->versions.size())) {
        selected_version_row_ = -1;
    } else {
        selected_version_row_ = row;
    }
    sync_version_tag_controls();
}

void InspectorPanel::sync_version_tag_controls() {
    version_tags_bar->setVisible(version_tags_enabled_);
    const auto* version = selected_version();
    const bool has_version = version != nullptr;
    version_tag_add_btn->setEnabled(has_version);
    version_tag_remove_btn->setEnabled(has_version &&
                                       !version->tags.empty());
}

// --- Derived copy (RAW → DERIVED) ----------------------------------------------

void InspectorPanel::sync_derived_controls(
    const ui_data_core::AssetView* view) {
    // 派生副本只有 RAW 阶段资产才有意义（与资产右键菜单同一门禁）。
    const ui_data_core::AssetView* resolved =
        view != nullptr ? view
                        : (current_view_ ? &*current_view_ : nullptr);
    if (resolved == nullptr) {
        create_derived_btn->setEnabled(false);
        create_derived_hint->setText(QString());
        return;
    }
    const bool is_raw = resolved->stage == domain::DataStage::Raw;
    create_derived_btn->setEnabled(is_raw);
    if (is_raw) {
        create_derived_hint->setText(QStringLiteral(
            "从该 RAW 资产派生一个可编辑副本：原件保持不变，"
            "副本落到「派生数据 (DERIVED)」阶段并钉住来源版本。"));
    } else {
        create_derived_hint->setText(QStringLiteral(
            "当前为「%1」阶段，不可再派生；"
            "派生副本只对 RAW 阶段资产开放。")
            .arg(QString::fromStdString(
                ui_data_core::stage_label(resolved->stage))));
    }
}

void InspectorPanel::on_create_derived_clicked() {
    if (current_asset_) {
        emit create_derived_requested(current_asset_);
    }
}

void InspectorPanel::on_version_tag_add() {
    const auto* version = selected_version();
    if (version == nullptr) {
        return;
    }
    QStringList existing;
    for (const auto& t : version->tags) {
        existing.append(QString::fromStdString(t));
    }
    TagInputDialog dlg(existing, this);
    dlg.setWindowTitle(QStringLiteral("添加版本标签"));
    if (dlg.exec() != QDialog::Accepted) {
        return;
    }
    const QString name = dlg.get_tag_name();
    if (!name.isEmpty()) {
        emit version_tag_added(
            QString::fromStdString(version->version_id), name);
    }
}

void InspectorPanel::on_version_tag_remove() {
    const auto* version = selected_version();
    if (version == nullptr || version->tags.empty()) {
        return;
    }
    QMenu menu(this);
    for (const auto& tag : version->tags) {
        menu.addAction(QString::fromStdString(tag));
    }
    QAction* action = menu.exec(QCursor::pos());
    if (action != nullptr && !action->text().isEmpty()) {
        emit version_tag_removed(
            QString::fromStdString(version->version_id), action->text());
    }
}

void InspectorPanel::populate_lineage(
    const ui_data_core::AssetView& view,
    const std::optional<catalog::LineageChain>& lineage_up,
    const std::optional<catalog::LineageChain>& lineage_down) {
    if (!lineage_up && !lineage_down) {
        const auto& lineage = view.lineage;
        if (lineage.has_lineage()) {
            // Un-enriched legacy view: keep the one-hop summary as text.
            std::vector<std::pair<QString, QString>> rows;
            if (!lineage.parent_ids.empty()) {
                const auto& names = !lineage.parent_names.empty()
                                        ? lineage.parent_names
                                        : lineage.parent_ids;
                QStringList joined;
                for (const auto& n : names) {
                    joined.append(QString::fromStdString(n));
                }
                rows.emplace_back(QStringLiteral("父节点 / 上游资产"),
                                  joined.join(QStringLiteral(", ")));
            }
            // Python ``if lineage.run_id:`` truthiness — an optional holding
            // "" must not produce a row.
            if (lineage.run_id && !lineage.run_id->empty()) {
                rows.emplace_back(QStringLiteral("生成 Runs / 任务"),
                                  QString::fromStdString(*lineage.run_id));
            }
            if (lineage.workflow_step && !lineage.workflow_step->empty()) {
                rows.emplace_back(
                    QStringLiteral("工作流步骤"),
                    QString::fromStdString(*lineage.workflow_step));
            }
            if (!lineage.child_ids.empty()) {
                const auto& names = !lineage.child_names.empty()
                                        ? lineage.child_names
                                        : lineage.child_ids;
                QStringList joined;
                for (const auto& n : names) {
                    joined.append(QString::fromStdString(n));
                }
                rows.emplace_back(QStringLiteral("子节点 / 下游衍生"),
                                  joined.join(QStringLiteral(", ")));
            }
            QStringList parts;
            for (const auto& [k, v] : rows) {
                parts.append(k + QStringLiteral(": ") + v);
            }
            lineage_tree->clear_chain(parts.join(QStringLiteral("；")));
        } else {
            lineage_tree->clear_chain();
        }
        return;
    }
    lineage_tree->load_chains(view, lineage_up, lineage_down);
}

QString InspectorPanel::render_integrity_status_sheet() const {
    return QStringLiteral("font-size: %1; font-weight: bold; color: %2;")
        .arg(tok("FONT_SIZE_BASE"),
             pal(integrity_color_token_.toUtf8().constData()));
}

void InspectorPanel::populate_integrity(
    const ui_data_core::AssetView& view) {
    const auto st = view.integrity_state;
    integrity_status_lbl->setText(QStringLiteral("完整性状态: %1 %2").arg(
        QString::fromStdString(ui_data_core::integrity_state_icon(st)),
        QString::fromStdString(ui_data_core::integrity_state_label(st))));
    integrity_color_token_ = integrity_tone_token(st);
    // 重注册即重渲染（数据态变化立即生效）。
    ui_shell::style_bind(integrity_status_lbl, [this] {
        return render_integrity_status_sheet();
    });

    // Python ``view.checksum or "未生成校验和"`` — "" behaves like None.
    const bool has_checksum =
        view.checksum.has_value() && !view.checksum->empty();
    const QString checksum = has_checksum
                                 ? QString::fromStdString(*view.checksum)
                                 : QStringLiteral("未生成校验和");
    hash_label->setText(QStringLiteral("SHA-256: %1").arg(checksum));
    copy_hash_btn->setEnabled(has_checksum);
}

void InspectorPanel::copy_hash() {
    if (current_view_ && current_view_->checksum &&
        !current_view_->checksum->empty()) {
        if (QClipboard* clipboard = QApplication::clipboard()) {
            clipboard->setText(
                QString::fromStdString(*current_view_->checksum));
        }
    }
}

void InspectorPanel::on_verify_clicked() {
    if (current_asset_) {
        emit verify_requested(current_asset_);
    }
}

void InspectorPanel::on_tag_added(const QString& tag_name) {
    if (current_asset_) {
        emit tag_added(current_asset_, tag_name);
    }
}

void InspectorPanel::on_tag_removed(const QString& tag_name) {
    if (current_asset_) {
        emit tag_removed(current_asset_, tag_name);
    }
}

}  // namespace pwb::ui_pages_mapedit
