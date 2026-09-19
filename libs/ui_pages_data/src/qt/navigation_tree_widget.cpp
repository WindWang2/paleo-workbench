// UI-06 — NavigationTree shell (see qt/navigation_tree_widget.hpp).
#include <pwb/ui_pages_data/qt/navigation_tree_widget.hpp>

#include <QMenu>
#include <QScrollBar>
#include <QTreeWidgetItem>
#include <QVariantMap>

#include <pwb/ui_shell/style_registry.hpp>

namespace pwb::ui_pages_data::qt {
namespace {

// Domain node types that skip the legacy category_changed emission
// (navigation_tree._on_current_changed verbatim).
bool is_domain_node(const std::string& node_type) {
    return node_type == "entity" || node_type == "entity_group" ||
           node_type == "auxiliary" || node_type == "stage_any";
}

}  // namespace

NavigationTree::NavigationTree(QWidget* parent) : QTreeWidget(parent) {
    setObjectName(QStringLiteral("NavigationTree"));
    setHeaderHidden(true);
    setRootIsDecorated(true);
    ui_shell::style_bind(this, [] {
        const auto p = ui_shell::style_palette();
        auto at = [&](const char* k) {
            const auto it = p.find(k);
            return it != p.end() ? QString::fromStdString(it->second)
                                 : QString();
        };
        return QStringLiteral(
                   "QTreeWidget#NavigationTree { background: %1;"
                   " border: 1px solid %2; border-radius: 4px; }")
            .arg(at("BG_SIDEBAR"), at("BORDER"));  // RADIUS_CARD
    });
    setMinimumWidth(200);
    setContextMenuPolicy(Qt::ContextMenuPolicy::CustomContextMenu);
    connect(this, &QTreeWidget::customContextMenuRequested, this,
            &NavigationTree::on_context_menu);
    connect(this, &QTreeWidget::currentItemChanged, this,
            &NavigationTree::on_current_changed);
    connect(this, &QTreeWidget::itemClicked, this,
            &NavigationTree::on_item_clicked);
    connect(this, &QTreeWidget::itemActivated, this,
            &NavigationTree::on_item_activated);
    model_.build();
    rebuild_items();
    setCurrentItem(nullptr);
}

// --- model → QVariant (the FilterQuery lives at kRoleQuery) -----------------

QVariantMap NavigationTree::query_to_variant(const FilterQuery& q) {
    QVariantMap m;
    m["node_type"] = QString::fromStdString(q.node_type);
    if (q.node_value) m["node_value"] = QString::fromStdString(*q.node_value);
    if (!q.search_text.empty())
        m["search_text"] = QString::fromStdString(q.search_text);
    if (q.stage) m["stage"] = QString::fromStdString(*q.stage);
    if (q.data_type) m["data_type"] = QString::fromStdString(*q.data_type);
    if (q.tag) m["tag"] = QString::fromStdString(*q.tag);
    if (q.integrity) m["integrity"] = QString::fromStdString(*q.integrity);
    if (!q.tags.empty()) {
        QStringList tags;
        for (const auto& t : q.tags) tags << QString::fromStdString(t);
        m["tags"] = tags;
    }
    if (q.tag_operator != "and")
        m["tag_operator"] = QString::fromStdString(q.tag_operator);
    if (q.review_status)
        m["review_status"] = QString::fromStdString(*q.review_status);
    if (q.entity_asset_ids) {
        QStringList ids;
        for (const auto& id : *q.entity_asset_ids)
            ids << QString::fromStdString(id);
        m["entity_asset_ids"] = ids;
    }
    if (q.entity_role)
        m["entity_role"] = QString::fromStdString(*q.entity_role);
    if (q.asset_id) m["asset_id"] = QString::fromStdString(*q.asset_id);
    return m;
}

FilterQuery NavigationTree::query_from_variant(const QVariantMap& m) {
    FilterQuery q;
    q.node_type = m.value("node_type", "all").toString().toStdString();
    auto opt = [&](const char* k) -> std::optional<std::string> {
        if (!m.contains(k)) return std::nullopt;
        return m[k].toString().toStdString();
    };
    q.node_value = opt("node_value");
    q.search_text = m.value("search_text").toString().toStdString();
    q.stage = opt("stage");
    q.data_type = opt("data_type");
    q.tag = opt("tag");
    q.integrity = opt("integrity");
    for (const auto& v : m.value("tags").toStringList()) {
        q.tags.push_back(v.toStdString());
    }
    if (m.contains("tag_operator"))
        q.tag_operator = m["tag_operator"].toString().toStdString();
    q.review_status = opt("review_status");
    if (m.contains("entity_asset_ids")) {
        std::set<std::string> ids;
        for (const auto& v : m["entity_asset_ids"].toStringList()) {
            ids.insert(v.toStdString());
        }
        q.entity_asset_ids = std::move(ids);
    }
    q.entity_role = opt("entity_role");
    q.asset_id = opt("asset_id");
    return q;
}

// --- row identity for expansion memory -------------------------------------

QString NavigationTree::row_identity(const NavRow& row) const {
    if (!row.key.empty()) return QString::fromStdString(row.key);
    // Count-bearing rows strip the trailing " n" so identity survives
    // count updates (Python _label_of: text.rsplit(" ", 1)[0]).
    const std::string& text = row.text;
    const auto pos = text.rfind(' ');
    const std::string base =
        (pos != std::string::npos) ? text.substr(0, pos) : text;
    return QStringLiteral("text:") + QString::fromStdString(base);
}

// --- materialization ---------------------------------------------------------

void NavigationTree::capture_expansion() {
    std::function<void(QTreeWidgetItem*)> walk = [&](QTreeWidgetItem* item) {
        const int row = item->data(0, kRoleModelRow).toInt();
        if (row >= 0 && row < static_cast<int>(model_.rows().size())) {
            expansion_[row_identity(model_.rows()[row])] =
                item->isExpanded();
        }
        for (int i = 0; i < item->childCount(); ++i) walk(item->child(i));
    };
    for (int i = 0; i < topLevelItemCount(); ++i) walk(topLevelItem(i));
}

void NavigationTree::rebuild_items() {
    capture_expansion();
    const int scroll = verticalScrollBar()->value();
    clear();

    const auto& rows = model_.rows();
    std::vector<QTreeWidgetItem*> items(rows.size(), nullptr);
    for (std::size_t i = 0; i < rows.size(); ++i) {
        const NavRow& row = rows[i];
        QTreeWidgetItem* parent_item =
            row.parent >= 0 ? items[static_cast<std::size_t>(row.parent)]
                            : invisibleRootItem();
        auto* item = new QTreeWidgetItem(
            parent_item, {QString::fromStdString(row.text)});
        if (row.query.has_value()) {
            item->setData(0, kRoleQuery, query_to_variant(*row.query));
        }
        if (!row.key.empty()) {
            item->setData(0, kRoleLegacyKey,
                          QString::fromStdString(row.key));
        }
        if (row.show_more_group.has_value()) {
            item->setData(0, kRoleShowMore,
                          QString::fromStdString(*row.show_more_group));
        }
        item->setData(0, kRoleModelRow, static_cast<int>(i));
        if (!row.selectable) {
            item->setFlags(item->flags() & ~Qt::ItemFlag::ItemIsSelectable);
        }
        if (row.disabled) item->setDisabled(true);
        if (!row.tooltip.empty()) {
            item->setToolTip(0, QString::fromStdString(row.tooltip));
        }
        // Expansion: remembered state wins; otherwise the model's initial
        // flag (Python sets expansion once at build).
        const QString id = row_identity(row);
        const auto it = expansion_.find(id);
        item->setExpanded(it != expansion_.end() ? it->second
                                                 : row.expanded);
        items[i] = item;
    }
    if (const auto sel = model_.selected_row(); sel.has_value() &&
        *sel >= 0 && *sel < static_cast<int>(items.size())) {
        setCurrentItem(items[static_cast<std::size_t>(*sel)]);
    }
    verticalScrollBar()->setValue(scroll);
}

// --- public API (model forwards + rebuild) -----------------------------------

void NavigationTree::set_project(const NavProjectView& project) {
    model_.set_project(project);
    rebuild_items();
}

void NavigationTree::clear_project() {
    model_.clear_project();
    rebuild_items();
}

void NavigationTree::apply_counts(const CatalogCounts& counts) {
    model_.apply_counts(counts);
    rebuild_items();
}

void NavigationTree::set_trash_count(int count) {
    model_.set_trash_count(count);
    rebuild_items();
}

bool NavigationTree::highlight_well(const std::string& well_id) {
    if (!model_.highlight_well(well_id)) return false;
    rebuild_items();
    if (const auto sel = model_.selected_row();
        sel.has_value() && *sel >= 0 &&
        *sel < static_cast<int>(model_.rows().size())) {
        // scrollToItem parity.
        QTreeWidgetItem* target = nullptr;
        std::function<void(QTreeWidgetItem*)> walk =
            [&](QTreeWidgetItem* item) {
                if (target) return;
                if (item->data(0, kRoleModelRow).toInt() == *sel) {
                    target = item;
                    return;
                }
                for (int i = 0; i < item->childCount(); ++i)
                    walk(item->child(i));
            };
        for (int i = 0; i < topLevelItemCount(); ++i) walk(topLevelItem(i));
        if (target) scrollToItem(target);
    }
    return true;
}

FilterQuery NavigationTree::current_filter_query() const {
    QTreeWidgetItem* current = currentItem();
    if (current == nullptr) return FilterQuery{};
    const QVariant v = current->data(0, kRoleQuery);
    if (!v.isValid()) return FilterQuery{};
    return query_from_variant(v.toMap());
}

std::string NavigationTree::selected_category() const {
    QTreeWidgetItem* current = currentItem();
    if (current == nullptr) return "全部";
    const QVariant key = current->data(0, kRoleLegacyKey);
    if (key.isValid()) return key.toString().toStdString();
    const QVariant qv = current->data(0, kRoleQuery);
    if (qv.isValid()) {
        const FilterQuery q = query_from_variant(qv.toMap());
        if (q.node_value) return *q.node_value;
    }
    return "全部";
}

QTreeWidgetItem* NavigationTree::find_category_item(
    const QString& label) const {
    QTreeWidgetItem* found = nullptr;
    std::function<void(QTreeWidgetItem*)> walk = [&](QTreeWidgetItem* item) {
        if (found) return;
        const QString text = item->text(0);
        const QString base = text.left(text.lastIndexOf(' '));
        if (base == label || text.startsWith(label)) {
            found = item;
            return;
        }
        for (int i = 0; i < item->childCount(); ++i) walk(item->child(i));
    };
    for (int i = 0; i < topLevelItemCount(); ++i) walk(topLevelItem(i));
    return found;
}

// --- item signals --------------------------------------------------------------

void NavigationTree::on_current_changed(QTreeWidgetItem* current,
                                        QTreeWidgetItem* /*previous*/) {
    if (current == nullptr) return;
    const int row = current->data(0, kRoleModelRow).toInt();
    if (row >= 0 && row < static_cast<int>(model_.rows().size())) {
        model_.select(row);
    }
    const QVariant qv = current->data(0, kRoleQuery);
    const QVariant key = current->data(0, kRoleLegacyKey);
    if (!qv.isValid()) return;
    const FilterQuery query = query_from_variant(qv.toMap());
    Q_EMIT filter_query_changed(query);
    // Domain nodes are fully handled by the FilterQuery channel; emitting
    // their label as a legacy "category" would re-parse into an
    // incompatible legacy query and clobber the smart filter.
    if (is_domain_node(query.node_type)) return;
    QString emit_str = key.isValid()
                           ? key.toString()
                           : (query.node_value
                                  ? QString::fromStdString(*query.node_value)
                                  : QStringLiteral("全部"));
    if (emit_str == QLatin1String("全部数据") ||
        emit_str == QLatin1String("all")) {
        emit_str = QStringLiteral("全部");
    }
    Q_EMIT category_changed(emit_str);
}

void NavigationTree::on_item_clicked(QTreeWidgetItem* item, int /*column*/) {
    const QVariant group = item->data(0, kRoleShowMore);
    if (group.isValid()) {
        model_.activate_next_page(group.toString().toStdString());
        rebuild_items();
    }
}

void NavigationTree::on_item_activated(QTreeWidgetItem* item,
                                       int /*column*/) {
    // Double-click/activation on an ENTITY row opens its data view.
    const QVariant qv = item->data(0, kRoleQuery);
    if (!qv.isValid()) return;
    const FilterQuery query = query_from_variant(qv.toMap());
    if (query.node_type == "entity" && !query.asset_id.has_value() &&
        query.node_value) {
        Q_EMIT entity_activated(QString::fromStdString(*query.node_value));
    }
}

void NavigationTree::on_context_menu(const QPoint& pos) {
    QTreeWidgetItem* item = itemAt(pos);
    if (item == nullptr) return;
    const int row = item->data(0, kRoleModelRow).toInt();
    const auto menu_kind =
        (row >= 0 && row < static_cast<int>(model_.rows().size()))
            ? model_.row_menu(row)
            : NavTreeModel::RowMenu::None;
    if (menu_kind == NavTreeModel::RowMenu::ManageTags) {
        QMenu menu(this);
        QAction* manage = menu.addAction(QStringLiteral("管理标签"));
        if (menu.exec(viewport()->mapToGlobal(pos)) == manage) {
            Q_EMIT manage_tags_requested();
        }
        return;
    }
    if (menu_kind == NavTreeModel::RowMenu::DeleteWell) {
        setCurrentItem(item);
        QMenu menu(this);
        QAction* del = menu.addAction(QStringLiteral("删除井…"));
        const QVariant qv = item->data(0, kRoleQuery);
        if (menu.exec(viewport()->mapToGlobal(pos)) == del && qv.isValid()) {
            const FilterQuery query = query_from_variant(qv.toMap());
            if (query.node_value) {
                Q_EMIT delete_well_requested(
                    QString::fromStdString(*query.node_value));
            }
        }
    }
}

}  // namespace pwb::ui_pages_data::qt
