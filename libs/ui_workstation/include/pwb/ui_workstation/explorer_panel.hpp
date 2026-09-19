#pragma once

// Qt shell over explorer_spec (UI-12) — port of
// paleo_workbench/ui/workstation/explorer.py's widget layer:
// QStandardItemModel + recursive QSortFilterProxyModel + 200 ms search
// debounce + stable-key diff reconcile (expansion/selection/scroll
// survive refreshes). The spec comes from build_explorer_spec over an
// injected ExplorerFacts projection — this widget never touches the
// project authority itself.

#include <set>

#include <QFrame>
#include <QItemSelection>
#include <QLabel>
#include <QLineEdit>
#include <QSortFilterProxyModel>
#include <QStandardItemModel>
#include <QTimer>
#include <QTreeView>
#include <QVariantMap>

#include <pwb/ui_workstation/explorer_spec.hpp>

namespace pwb::ui_workstation {

// Roles (Python OBJECT_ROLE / KEY_ROLE / ICON_ROLE / NAVIGATION_ROLE).
inline constexpr int kExplorerObjectRole = Qt::UserRole + 1;
inline constexpr int kExplorerKeyRole = Qt::UserRole + 2;
inline constexpr int kExplorerIconRole = Qt::UserRole + 3;
inline constexpr int kExplorerNavigationRole = Qt::UserRole + 4;
inline constexpr int kExplorerOpaqueRole = Qt::UserRole + 5;

class WorkstationExplorer : public QFrame {
    Q_OBJECT
public:
    explicit WorkstationExplorer(QWidget* parent = nullptr);

    // Feed a new fact projection and re-run the diff reconcile.
    void set_facts(const ExplorerFacts& facts);
    // Project switch: structure reset → default expansion restored.
    void mark_structure_dirty();
    const ExplorerFacts& facts() const { return facts_; }

    void set_mode(const std::string& mode);
    std::string mode() const { return mode_; }
    void focus_search();
    // 工程文档变化后的增量刷新入口（保持视图状态）。
    void refresh();

    // Test/host seam: stable-key lookup into the source model.
    QStandardItem* find_item(const QString& key) const;
    QModelIndex proxy_index_for_item(QStandardItem* item) const;

signals:
    // payload = QVariantMap of the node's payload dict (kind + keys).
    void object_selected(const QVariantMap& payload);
    void object_activated(const QVariantMap& payload);
    void navigation_requested(int hub_index, const QString& key);
    void joint_workspace_requested();
    // Checkable user-layer rows: host applies the visibility verdict.
    void check_toggled(const QVariantMap& payload, bool checked);

private:
    void reconcile(const ExplorerSpec& spec);
    bool reconcile_children(QStandardItem* parent,
                            const std::vector<ExplorerNode>& nodes,
                            int depth);
    QStandardItem* create_item(const ExplorerNode& node) const;
    void update_item(QStandardItem* item, const ExplorerNode& node) const;
    void apply_default_expansion();
    void restore_expansion(const std::set<std::string>& keys);
    std::set<std::string> expanded_keys() const;
    QString current_key() const;
    void restore_selection(const QString& key);
    void apply_search_filter();
    void show_context_menu(const QPoint& pos);
    void on_activated(const QModelIndex& proxy_index);
    void on_current_changed(const QModelIndex& current);

    ExplorerFacts facts_;
    std::string mode_ = "project";
    bool structure_dirty_ = true;

    QLabel* title_label_ = nullptr;
    QLineEdit* search_box_ = nullptr;
    QStandardItemModel* model_ = nullptr;
    QSortFilterProxyModel* proxy_ = nullptr;
    QTreeView* tree_ = nullptr;
    QLabel* footer_label_ = nullptr;
    QTimer* search_timer_ = nullptr;
};

}  // namespace pwb::ui_workstation
