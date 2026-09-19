#include "pwb/ui_workstation/explorer_panel.hpp"

#include <QApplication>
#include <QClipboard>
#include <QHBoxLayout>
#include <QMenu>
#include <QScrollBar>
#include <QToolButton>
#include <QVBoxLayout>

#include <pwb/ui_widgets/icon_factory.hpp>

namespace pwb::ui_workstation {

namespace {

QVariantMap to_variant_map(const std::map<std::string, std::string>& m) {
    QVariantMap out;
    for (const auto& [k, v] : m) {
        out.insert(QString::fromStdString(k),
                   QString::fromStdString(v));
    }
    return out;
}

}  // namespace

WorkstationExplorer::WorkstationExplorer(QWidget* parent)
    : QFrame(parent) {
    setObjectName("WorkstationExplorer");
    // V9: 210 → 180 constraint convergence; no max width — the dock
    // owns sizing.
    setMinimumWidth(180);

    auto* outer = new QVBoxLayout(this);
    outer->setContentsMargins(8, 8, 8, 8);
    outer->setSpacing(6);

    auto* header = new QHBoxLayout();
    header->setContentsMargins(0, 0, 0, 0);
    title_label_ = new QLabel("资源管理器", this);
    title_label_->setObjectName("WorkstationPanelTitle");
    header->addWidget(title_label_);
    header->addStretch(1);
    auto* refresh_button = new QToolButton(this);
    refresh_button->setObjectName("WorkstationChromeButton");
    refresh_button->setIcon(
        ui_widgets::workstation_icon("refresh-cw.svg"));
    refresh_button->setToolTip("刷新");
    refresh_button->setAccessibleName("刷新");
    refresh_button->setAccessibleDescription("刷新资源树");
    connect(refresh_button, &QToolButton::clicked, this,
            [this] { refresh(); });
    header->addWidget(refresh_button);
    outer->addLayout(header);

    search_box_ = new QLineEdit(this);
    search_box_->setObjectName("WorkstationExplorerSearch");
    search_box_->setPlaceholderText("筛选当前对象...");
    search_box_->setClearButtonEnabled(true);
    outer->addWidget(search_box_);

    model_ = new QStandardItemModel(this);
    proxy_ = new QSortFilterProxyModel(this);
    proxy_->setSourceModel(model_);
    proxy_->setFilterCaseSensitivity(Qt::CaseSensitivity::CaseInsensitive);
    proxy_->setRecursiveFilteringEnabled(true);
    search_timer_ = new QTimer(this);
    search_timer_->setSingleShot(true);
    search_timer_->setInterval(kExplorerSearchDebounceMs);
    connect(search_timer_, &QTimer::timeout, this,
            &WorkstationExplorer::apply_search_filter);
    connect(search_box_, &QLineEdit::textChanged, this,
            [this](const QString&) { search_timer_->start(); });

    tree_ = new QTreeView(this);
    tree_->setObjectName("WorkstationExplorerTree");
    tree_->setModel(proxy_);
    tree_->setHeaderHidden(true);
    tree_->setUniformRowHeights(true);
    tree_->setAnimated(false);
    tree_->setEditTriggers(QAbstractItemView::EditTrigger::NoEditTriggers);
    tree_->setSelectionBehavior(
        QAbstractItemView::SelectionBehavior::SelectRows);
    tree_->setContextMenuPolicy(
        Qt::ContextMenuPolicy::CustomContextMenu);
    connect(tree_, &QTreeView::customContextMenuRequested, this,
            &WorkstationExplorer::show_context_menu);
    connect(tree_->selectionModel(),
            &QItemSelectionModel::currentChanged, this,
            [this](const QModelIndex& current, const QModelIndex&) {
                on_current_changed(current);
            });
    connect(tree_, &QTreeView::doubleClicked, this,
            &WorkstationExplorer::on_activated);
    outer->addWidget(tree_, 1);

    footer_label_ = new QLabel(this);
    footer_label_->setObjectName("WorkstationPanelFootnote");
    outer->addWidget(footer_label_);

    refresh();
}

void WorkstationExplorer::set_facts(const ExplorerFacts& facts) {
    facts_ = facts;
    refresh();
}

void WorkstationExplorer::mark_structure_dirty() {
    structure_dirty_ = true;
}

void WorkstationExplorer::set_mode(const std::string& mode) {
    mode_ = normalize_explorer_mode(mode);
    title_label_->setText(QString::fromStdString(
        explorer_mode_titles().at(mode_)));
    search_box_->setPlaceholderText(
        (mode_ == "data" || mode_ == "search") ? "搜索项目数据..."
                                               : "筛选当前对象...");
    // Mode switches take the incremental path but reset expansion to
    // the new tree's defaults.
    structure_dirty_ = true;
    refresh();
    if (mode_ == "search" || mode_ == "data") {
        search_box_->setFocus(Qt::FocusReason::ShortcutFocusReason);
    }
}

void WorkstationExplorer::focus_search() {
    search_box_->setFocus(Qt::FocusReason::ShortcutFocusReason);
    search_box_->selectAll();
}

void WorkstationExplorer::refresh() {
    reconcile(build_explorer_spec(mode_, facts_));
}

// --- diff reconcile ---------------------------------------------------

void WorkstationExplorer::reconcile(const ExplorerSpec& spec) {
    // Capture view state BEFORE mutating (Python _reconcile parity).
    const auto expanded = expanded_keys();
    const QString selected = current_key();
    const int scroll = tree_->verticalScrollBar()->value();

    tree_->setUpdatesEnabled(false);
    if (auto* selection = tree_->selectionModel()) {
        selection->blockSignals(true);
    }
    reconcile_children(model_->invisibleRootItem(), spec.roots, 0);
    if (auto* selection = tree_->selectionModel()) {
        selection->blockSignals(false);
    }

    if (structure_dirty_) {
        apply_default_expansion();
    } else {
        restore_expansion(expanded);
    }
    restore_selection(selected);
    tree_->verticalScrollBar()->setValue(scroll);
    tree_->setUpdatesEnabled(true);

    footer_label_->setText(QString::fromStdString(spec.footer));
}

bool WorkstationExplorer::reconcile_children(
    QStandardItem* parent, const std::vector<ExplorerNode>& nodes,
    int depth) {
    // Diff by stable key: update-in-place where the key already exists;
    // remove vanished rows back-to-front; insert new rows at position.
    bool changed = false;
    // 1) Update or remove existing rows.
    for (int row = parent->rowCount() - 1; row >= 0; --row) {
        QStandardItem* item = parent->child(row);
        const QString key =
            item->data(kExplorerKeyRole).toString();
        const ExplorerNode* match = nullptr;
        for (const auto& node : nodes) {
            if (key == QString::fromStdString(node.key)) {
                match = &node;
                break;
            }
        }
        if (match == nullptr) {
            parent->removeRow(row);
            changed = true;
            continue;
        }
        update_item(item, *match);
        changed |= reconcile_children(item, match->children, depth + 1);
    }
    // 2) Insert new keys at their spec position.
    for (std::size_t target = 0; target < nodes.size(); ++target) {
        const auto& node = nodes[target];
        const QString key = QString::fromStdString(node.key);
        QStandardItem* existing = nullptr;
        int existing_row = -1;
        for (int row = 0; row < parent->rowCount(); ++row) {
            if (parent->child(row)->data(kExplorerKeyRole).toString() ==
                key) {
                existing = parent->child(row);
                existing_row = row;
                break;
            }
        }
        if (existing == nullptr) {
            QStandardItem* item = create_item(node);
            parent->insertRow(static_cast<int>(target), item);
            changed = true;
            reconcile_children(item, node.children, depth + 1);
        } else if (existing_row != static_cast<int>(target)) {
            // Reorder: take the row out and re-insert at the spec slot.
            auto taken = parent->takeRow(existing_row);
            parent->insertRow(static_cast<int>(target), taken);
            changed = true;
        }
    }
    return changed;
}

QStandardItem* WorkstationExplorer::create_item(
    const ExplorerNode& node) const {
    auto* item = new QStandardItem(QString::fromStdString(node.label));
    item->setData(to_variant_map(node.payload), kExplorerObjectRole);
    item->setData(QString::fromStdString(node.key), kExplorerKeyRole);
    if (!node.icon.empty()) {
        const QString icon = QString::fromStdString(node.icon);
        item->setData(icon, kExplorerIconRole);
        item->setIcon(ui_widgets::workstation_icon(icon));
    }
    if (!node.tooltip.empty()) {
        item->setToolTip(QString::fromStdString(node.tooltip));
    }
    if (node.navigation.has_value()) {
        item->setData(QVariantList{node.navigation->first,
                                   QString::fromStdString(
                                       node.navigation->second)},
                      kExplorerNavigationRole);
    }
    if (node.object != nullptr) {
        item->setData(
            QVariant::fromValue(
                reinterpret_cast<quintptr>(node.object)),
            kExplorerOpaqueRole);
    }
    if (node.check_state.has_value()) {
        item->setCheckable(true);
        item->setCheckState(*node.check_state == 0
                              ? Qt::CheckState::Unchecked
                              : Qt::CheckState::Checked);
    }
    return item;
}

void WorkstationExplorer::update_item(QStandardItem* item,
                                      const ExplorerNode& node) const {
    const QString label = QString::fromStdString(node.label);
    if (item->text() != label) item->setText(label);
    item->setData(to_variant_map(node.payload), kExplorerObjectRole);
    const QString tip = QString::fromStdString(node.tooltip);
    if (item->toolTip() != tip) item->setToolTip(tip);
    if (node.navigation.has_value()) {
        item->setData(QVariantList{node.navigation->first,
                                   QString::fromStdString(
                                       node.navigation->second)},
                      kExplorerNavigationRole);
    } else {
        item->setData(QVariant(), kExplorerNavigationRole);
    }
    if (node.object != nullptr) {
        item->setData(
            QVariant::fromValue(
                reinterpret_cast<quintptr>(node.object)),
            kExplorerOpaqueRole);
    }
    const QString icon = QString::fromStdString(node.icon);
    if (item->data(kExplorerIconRole).toString() != icon) {
        item->setData(icon, kExplorerIconRole);
        item->setIcon(icon.isEmpty()
                          ? QIcon()
                          : ui_widgets::workstation_icon(icon));
    }
    if (!node.check_state.has_value()) {
        if (item->isCheckable()) item->setCheckable(false);
    } else {
        if (!item->isCheckable()) item->setCheckable(true);
        const auto state = *node.check_state == 0
                               ? Qt::CheckState::Unchecked
                               : Qt::CheckState::Checked;
        if (item->checkState() != state) item->setCheckState(state);
    }
}

// --- view-state preservation -------------------------------------------

void WorkstationExplorer::apply_default_expansion() {
    structure_dirty_ = false;
    std::function<void(QStandardItem*, int)> walk =
        [&](QStandardItem* item, int depth) {
            for (int row = 0; row < item->rowCount(); ++row) {
                QStandardItem* child = item->child(row);
                if (depth <= 1) {
                    const QModelIndex index =
                        proxy_index_for_item(child);
                    if (index.isValid()) tree_->setExpanded(index, true);
                }
                walk(child, depth + 1);
            }
        };
    walk(model_->invisibleRootItem(), 0);
}

std::set<std::string> WorkstationExplorer::expanded_keys() const {
    std::set<std::string> keys;
    std::function<void(QStandardItem*)> walk = [&](QStandardItem* item) {
        for (int row = 0; row < item->rowCount(); ++row) {
            QStandardItem* child = item->child(row);
            const QModelIndex index = proxy_index_for_item(child);
            if (index.isValid() && tree_->isExpanded(index)) {
                keys.insert(child->data(kExplorerKeyRole)
                                .toString()
                                .toStdString());
            }
            walk(child);
        }
    };
    walk(model_->invisibleRootItem());
    return keys;
}

void WorkstationExplorer::restore_expansion(
    const std::set<std::string>& keys) {
    std::function<void(QStandardItem*)> walk = [&](QStandardItem* item) {
        for (int row = 0; row < item->rowCount(); ++row) {
            QStandardItem* child = item->child(row);
            const QModelIndex index = proxy_index_for_item(child);
            if (index.isValid()) {
                tree_->setExpanded(
                    index,
                    keys.count(child->data(kExplorerKeyRole)
                                   .toString()
                                   .toStdString()) != 0);
            }
            walk(child);
        }
    };
    walk(model_->invisibleRootItem());
}

QString WorkstationExplorer::current_key() const {
    const QModelIndex current = tree_->currentIndex();
    if (!current.isValid()) return {};
    const QModelIndex source = proxy_->mapToSource(current);
    if (!source.isValid()) return {};
    return model_->itemFromIndex(source)
        ->data(kExplorerKeyRole)
        .toString();
}

void WorkstationExplorer::restore_selection(const QString& key) {
    if (key.isEmpty()) return;
    QStandardItem* item = find_item(key);
    if (item == nullptr) return;
    const QModelIndex index = proxy_index_for_item(item);
    if (index.isValid()) tree_->setCurrentIndex(index);
}

QStandardItem* WorkstationExplorer::find_item(const QString& key) const {
    std::function<QStandardItem*(QStandardItem*)> walk =
        [&](QStandardItem* item) -> QStandardItem* {
            for (int row = 0; row < item->rowCount(); ++row) {
                QStandardItem* child = item->child(row);
                if (child->data(kExplorerKeyRole).toString() == key) {
                    return child;
                }
                if (auto* found = walk(child)) return found;
            }
            return nullptr;
        };
    return walk(model_->invisibleRootItem());
}

QModelIndex WorkstationExplorer::proxy_index_for_item(
    QStandardItem* item) const {
    if (item == nullptr) return {};
    return proxy_->mapFromSource(item->index());
}

void WorkstationExplorer::apply_search_filter() {
    proxy_->setFilterFixedString(search_box_->text());
}

// --- signals ------------------------------------------------------------

void WorkstationExplorer::show_context_menu(const QPoint& pos) {
    const QModelIndex index = tree_->indexAt(pos);
    if (!index.isValid()) return;
    const QModelIndex source = proxy_->mapToSource(index);
    QStandardItem* item = model_->itemFromIndex(source);
    if (item == nullptr) return;
    const QVariantMap payload =
        item->data(kExplorerObjectRole).toMap();
    if (payload.isEmpty()) return;

    QMenu menu(this);
    QAction* open_action = menu.addAction("打开");
    connect(open_action, &QAction::triggered, this,
            [this, index] { on_activated(index); });
    QAction* copy_action = menu.addAction("复制名称");
    connect(copy_action, &QAction::triggered, this, [item] {
        QApplication::clipboard()->setText(item->text());
    });
    if (payload.value("kind").toString() == "workspace" &&
        payload.value("workspace").toString() == "joint") {
        QAction* joint = menu.addAction("井震联合解释");
        connect(joint, &QAction::triggered, this,
                [this] { emit joint_workspace_requested(); });
    }
    if (item->data(kExplorerOpaqueRole).isValid()) {
        QAction* activate = menu.addAction("激活");
        connect(activate, &QAction::triggered, this,
                [this, payload] { emit object_activated(payload); });
    }
    menu.exec(tree_->viewport()->mapToGlobal(pos));
}

void WorkstationExplorer::on_current_changed(
    const QModelIndex& current) {
    if (!current.isValid()) return;
    const QModelIndex source = proxy_->mapToSource(current);
    QStandardItem* item = model_->itemFromIndex(source);
    if (item == nullptr) return;
    const QVariantMap payload =
        item->data(kExplorerObjectRole).toMap();
    emit object_selected(payload);
    const QVariant nav = item->data(kExplorerNavigationRole);
    if (nav.isValid()) {
        const QVariantList pair = nav.toList();
        if (pair.size() == 2) {
            emit navigation_requested(pair[0].toInt(),
                                      pair[1].toString());
        }
    }
}

void WorkstationExplorer::on_activated(const QModelIndex& proxy_index) {
    if (!proxy_index.isValid()) return;
    const QModelIndex source = proxy_->mapToSource(proxy_index);
    QStandardItem* item = model_->itemFromIndex(source);
    if (item == nullptr) return;
    const QVariantMap payload =
        item->data(kExplorerObjectRole).toMap();
    if (payload.value("kind").toString() == "workspace" &&
        payload.value("workspace").toString() == "joint") {
        emit joint_workspace_requested();
        return;
    }
    emit object_activated(payload);
}

}  // namespace pwb::ui_workstation
