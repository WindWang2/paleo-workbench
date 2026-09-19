// UI-06 — navigation_tree.py :: NavigationTree Qt shell.
//
// The Qt-free NavTreeModel owns every row semantic (build order, paging,
// counts, dynamic tag/review leaves, selection fallback). This widget only
// materializes NavRows into QTreeWidgetItems and forwards item signals —
// expansion state and scroll position are view concerns preserved across
// rebuilds by identity-keyed memory (Python mutates items in place, which
// preserves both implicitly; a re-materializing port restores them).
#pragma once

#include <QTreeWidget>

#include <map>
#include <optional>
#include <string>

#include <pwb/ui_pages_data/nav_tree_model.hpp>

namespace pwb::ui_pages_data::qt {

// Item data roles (column 0):
//   UserRole+0 → FilterQuery payload (QVariantMap, absent on group rows)
//   UserRole+1 → legacy category key ("entity:x", "全部", stage value…)
//   UserRole+2 → show-more group key (the "▣ 显示更多" affordance)
//   UserRole+3 → model row index (valid until the next rebuild)
inline constexpr int kRoleQuery = Qt::ItemDataRole::UserRole;
inline constexpr int kRoleLegacyKey = Qt::ItemDataRole::UserRole + 1;
inline constexpr int kRoleShowMore = Qt::ItemDataRole::UserRole + 2;
inline constexpr int kRoleModelRow = Qt::ItemDataRole::UserRole + 3;

class NavigationTree : public QTreeWidget {
    Q_OBJECT
public:
    explicit NavigationTree(QWidget* parent = nullptr);

    NavTreeModel& model() { return model_; }

    // Same contract as the Python methods; each forwards to the model and
    // re-materializes items.
    void set_project(const NavProjectView& project);
    void clear_project();
    void apply_counts(const CatalogCounts& counts);
    void set_trash_count(int count);

    // Map → Data direction (materialize + select + scroll). False when
    // the well id is unknown.
    bool highlight_well(const std::string& well_id);

    FilterQuery current_filter_query() const;
    std::string selected_category() const;
    // The row the model considers selected (nullopt when none).
    std::optional<int> selected_row() const { return model_.selected_row(); }

    // find_category_item(label) parity: first row whose label-base equals
    // `label` or whose text starts with it (pre-order).
    QTreeWidgetItem* find_category_item(const QString& label) const;

Q_SIGNALS:
    void category_changed(const QString& category);
    void filter_query_changed(
        const pwb::ui_pages_data::FilterQuery& query);
    void manage_tags_requested();
    void delete_well_requested(const QString& well_id);
    void entity_activated(const QString& entity_id);

private:
    void rebuild_items();
    void capture_expansion();
    void apply_expansion();
    QString row_identity(const NavRow& row) const;
    static QVariantMap query_to_variant(const FilterQuery& query);
    static FilterQuery query_from_variant(const QVariantMap& map);

    void on_current_changed(QTreeWidgetItem* current,
                            QTreeWidgetItem* previous);
    void on_item_clicked(QTreeWidgetItem* item, int column);
    void on_item_activated(QTreeWidgetItem* item, int column);
    void on_context_menu(const QPoint& pos);

    NavTreeModel model_;
    std::map<QString, bool> expansion_;
};

}  // namespace pwb::ui_pages_data::qt
