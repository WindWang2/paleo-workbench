// UI-06 — data_asset_table.py :: DataAssetTable Qt shell.
//
// Chips + column settings + QTableView + selection/context-menu/sort
// behavior. Two seams stay external, exactly like the Python dependencies:
//  - AssetRowSource: the table model (asset_table_model.py /
//    paged_asset_model.py — UI-03's slice). Row identity is the
//    ("resource"|"artifact", id) pair.
//  - FilterIndex: set_filter_fn(query → ordered source-row indices).
//    filter_index.py is UI-03's; the widget only consumes its output.
#pragma once

#include <QAbstractTableModel>
#include <QTableView>
#include <QWidget>

#include <functional>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <vector>

#include <pwb/ui_pages_data/asset_view.hpp>
#include <pwb/ui_pages_data/filter_query.hpp>
#include <pwb/ui_pages_data/table_model.hpp>

class QAction;
class QMenu;
class QPushButton;

namespace pwb::ui_pages_data::qt {

class FilterChipsBar;

// asset_table_model.AssetTableModel / paged_asset_model seam. The concrete
// model (UI-03) subclasses this; the table reads rows through it.
class AssetRowSource : public QAbstractTableModel {
    Q_OBJECT
public:
    using QAbstractTableModel::QAbstractTableModel;
    // Row → asset handle; nullptr for sparse/unloaded rows.
    virtual const AssetRow* asset_at(int row) const = 0;
    // Row → normalized view; defaults to asset_at's view.
    virtual const AssetView* view_at(int row) const {
        const AssetRow* asset = asset_at(row);
        return asset ? &asset->view : nullptr;
    }
    // last_sort parity — nullopt when the user never sorted.
    virtual std::optional<std::pair<int, Qt::SortOrder>> last_sort() const {
        return std::nullopt;
    }
    // Paged mode only: stable key → resident row (-1 when not resident).
    virtual int row_for_key(
        const std::pair<std::string, std::string>& /*key*/) const {
        return -1;
    }
};

// filter_index.FilterIndex seam: FilterQuery → ordered indices into the
// source asset vector the host passed to update_assets.
using FilterIndexFn =
    std::function<std::vector<int>(const FilterQuery& query)>;

class DataAssetTable : public QWidget {
    Q_OBJECT
public:
    explicit DataAssetTable(QWidget* parent = nullptr);

    // Source assets in canonical order (resources then artifacts then
    // extras — the host mirrors Python's concatenation). filter_fn feeds
    // the model's filtered rows.
    void set_filter_fn(FilterIndexFn fn);
    void set_model(AssetRowSource* model);
    // Paged-mode second model (also an AssetRowSource; row_for_key used).
    void set_paged_model(AssetRowSource* model);

    // update_assets parity: rebuild visible rows through the filter seam.
    void update_assets(const std::vector<AssetRow>& assets);

    void set_category(const QString& category);  // via legacy_category_parse_fn
    // Legacy-category → FilterQuery seam (filter_index._parse_legacy_category).
    void set_legacy_category_parse_fn(
        std::function<FilterQuery(const QString&, const std::string&)> fn);

    void set_filter_query(const FilterQuery& query);
    const FilterQuery& filter_query() const { return filter_query_; }
    void set_search_text(const QString& text);
    std::string search_text() const { return search_text_; }
    void apply_saved_filter(const FilterQuery& query);

    int visible_asset_count() const;
    const AssetRow* asset_at(int view_row) const;
    const AssetView* view_at(int view_row) const;
    const std::vector<AssetRow>& selected_assets() const {
        return selected_assets_;
    }
    // Materialized copy — the widget stores row POINTERS (#1388), so
    // this resolves them on demand instead of deep-copying per reset.
    std::vector<AssetRow> visible_assets() const;
    void set_selected_asset(const AssetRow* asset);

    std::vector<std::string> visible_column_keys() const {
        return visible_column_keys_;
    }
    void set_visible_columns(const std::vector<std::string>& keys);
    void reset_columns();

    // Paged mode (update_paged/exit_paged_mode parity; provider wiring is
    // the model's business — the widget only routes the query + signals).
    bool enter_paged_mode();   // apply_query succeeded?
    void exit_paged_mode();
    bool in_paged_mode() const { return in_paged_mode_; }

    FilterChipsBar* chips_bar() { return chips_bar_; }
    QTableView* table() { return table_; }
    QPushButton* column_settings_button() { return column_settings_btn_; }

Q_SIGNALS:
    void selected_asset_changed(
        const std::optional<pwb::ui_pages_data::AssetRow>& asset);
    void selected_assets_changed(
        const std::vector<pwb::ui_pages_data::AssetRow>& assets);
    void context_menu_requested(
        const QPoint& global_pos,
        const std::vector<pwb::ui_pages_data::AssetRow>& target);
    void search_text_changed(const QString& text);
    void paged_mode_unavailable();

private:
    void apply_filter();
    void build_column_settings_menu();
    void set_column_visible_from_action(const std::string& key, bool on);
    void sync_column_actions();
    void emit_selection();
    void on_context_menu(const QPoint& pos);
    std::optional<std::pair<std::string, std::string>>
    asset_key(const AssetRow* asset) const;
    void on_model_reset();
    void on_section_resized(int logical, int old_size, int new_size);
    void on_header_clicked(int column);
    void reapply_sort(
        std::optional<std::pair<int, Qt::SortOrder>> pre_build_sort);
    void emit_selection_changes(
        const std::optional<AssetRow>& prev_primary,
        const std::vector<AssetRow>& prev_multi);
    bool sync_selection();
    AssetRowSource* active_model() const;
    void install_model(AssetRowSource* model);

    std::vector<AssetRow> assets_;            // canonical source order
    // Row pointers into assets_ / the active model's rows — the cache is
    // selection/highlight matching only, so storing values paid a full
    // AssetRow deep copy per row on every model reset (#1388).
    std::vector<const AssetRow*> visible_assets_;
    std::optional<AssetRow> selected_asset_;
    std::vector<AssetRow> selected_assets_;
    FilterQuery filter_query_;
    std::string search_text_;
    std::vector<std::string> visible_column_keys_;
    std::map<std::string, QAction*> column_actions_;
    bool syncing_column_actions_ = false;
    std::set<std::string> user_resized_columns_;
    std::optional<std::vector<std::string>> auto_fit_columns_key_;
    bool fitting_columns_ = false;
    bool in_paged_mode_ = false;

    FilterIndexFn filter_fn_;
    std::function<FilterQuery(const QString&, const std::string&)>
        legacy_parse_fn_;

    FilterChipsBar* chips_bar_;
    QPushButton* column_settings_btn_;
    QMenu* column_settings_menu_;
    QAction* reset_columns_action_;
    QTableView* table_;
    AssetRowSource* model_ = nullptr;
    // CLOSURE-PREVIEW (task 04): the shipped row source — auto-installed
    // so the table always has a working model (UI-03 hosts replace it via
    // set_model, which re-points model_ and keeps the owned source idle).
    class VectorAssetRowSource* owned_model_ = nullptr;
    AssetRowSource* paged_model_ = nullptr;
};

}  // namespace pwb::ui_pages_data::qt
