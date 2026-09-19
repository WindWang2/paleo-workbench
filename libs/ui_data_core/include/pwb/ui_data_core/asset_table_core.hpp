// asset_table_model.py port — the Qt-free model state machine and cell
// formatting behind AssetTableModel (RESOURCE_TYPE_LABELS, _sort_tuple,
// _match_positions_by_identity, _recycle_views, _format_cell_display,
// _format_cell_tooltip, _review_status_display, the sort-remembering row
// protocol #850-1/#1063/#1064).
//
// The Qt QAbstractTableModel shell (pwb_ui_data_qt) delegates to this core
// and wraps each mutation in begin/endResetModel.
#pragma once

#include "pwb/ui_data_core/asset_view.hpp"

#include <deque>
#include <functional>
#include <optional>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

namespace pwb::ui_data_core {

// RESOURCE_TYPE_LABELS (asset_table_model.py): RESOURCE_LABELS merged with
// the page's own overrides — "horizon" is "层位" here, NOT "层位数据".
const std::unordered_map<std::string, std::string>& resource_type_labels();

// _review_status_display(view): governance display or "—".
std::string review_status_display(const AssetView& view);

// _format_cell_display(view, key) — the DisplayRole switch (16 columns).
std::string format_cell_display(const AssetView& view, std::string_view key);

// _format_cell_tooltip(view, key) — the ToolTipRole switch.
std::string format_cell_tooltip(const AssetView& view, std::string_view key);

// ---------------------------------------------------------------------------
// _sort_tuple — sort by meaning, not by the formatted string (#651)
// ---------------------------------------------------------------------------

// Comparable form of one _sort_tuple result. The tuple shapes differ per
// column; `kind` selects the Python comparison rule.
struct AssetSortKey {
    int missing = 0;                     // leading 0/1 tuple element
    enum class Kind { Text, Bool, Nums, StrList, NonComparable } kind =
        Kind::Text;
    bool bool_value = false;             // managed
    std::vector<long long> nums;         // version numeric runs
    std::vector<std::string> strs;       // tags list
    std::string text;                    // scalar tail / scalar value
};

// _sort_tuple(view, key, format_cell) — one sort key per row.
AssetSortKey asset_sort_key(const AssetView& view, std::string_view key);

// Python tuple compare. Comparing two "lineage" keys raises TypeError in
// Python (LineageView is unorderable) — mirrored by throwing
// std::logic_error when both keys reach the unorderable tail.
int asset_sort_key_compare(const AssetSortKey& a, const AssetSortKey& b);

// ---------------------------------------------------------------------------
// _match_positions_by_identity / _recycle_views (#1063)
// ---------------------------------------------------------------------------

// Per-position old-index matches for identical objects (Python ``id()``
// buckets consumed greedily, in order). Identity comes from
// asset_handle_identity — same object → reuse is exact.
std::vector<std::optional<std::size_t>> match_positions_by_identity(
    const std::vector<AssetHandle>& old_assets,
    const std::vector<AssetHandle>& new_assets);

// _recycle_views: old view at the matched position, else build_view(asset).
std::vector<AssetView> recycle_views(
    const std::vector<AssetHandle>& old_assets,
    const std::vector<AssetView>& old_views,
    const std::vector<AssetHandle>& new_assets,
    const std::function<AssetView(const AssetHandle&)>& build_view);

// ---------------------------------------------------------------------------
// AssetTableCore — model state the Qt shell mirrors
// ---------------------------------------------------------------------------

// View-enricher slot: the callable plus an identity cookie the build-token
// compares (Python compares the (project_root, enricher) tuple — function
// identity, not equality of output).
struct ViewEnricher {
    std::function<AssetView(AssetView)> fn;
    const void* token = nullptr;
};

class AssetTableCore {
public:
    void set_project_root(const std::filesystem::path* root);
    void set_view_enricher(const ViewEnricher* enricher);  // non-owning

    void set_column_keys(std::vector<std::string> keys);   // drops last_sort
    void set_assets(std::vector<AssetHandle> assets);
    void set_filtered_rows(std::vector<int> rows);
    void set_assets_filtered(std::vector<AssetHandle> assets,
                             std::vector<int> rows,
                             const std::vector<std::string>* column_keys = nullptr,
                             const std::vector<AssetView>* views = nullptr);
    void sort(int column, bool descending);

    int row_count() const { return static_cast<int>(filtered_rows_.size()); }
    int column_count() const {
        return static_cast<int>(column_keys_.size());
    }
    const AssetHandle* asset_at(int view_row) const;
    const AssetView* view_at(int view_row) const;
    const std::vector<AssetHandle>& assets() const { return raw_assets_; }
    const std::vector<std::string>& column_keys() const { return column_keys_; }
    const std::vector<int>& filtered_rows() const { return filtered_rows_; }
    const std::vector<AssetView>& views() const { return views_; }
    // (column, descending) or nullopt.
    std::optional<std::pair<int, bool>> last_sort() const { return last_sort_; }
    // Views actually built by the last set_assets* call (#1063 reporting).
    int last_rebuild_view_builds() const { return last_rebuild_view_builds_; }

    // data(index, DisplayRole|ToolTipRole) helpers.
    std::string cell_display(int view_row, int column) const;
    std::string cell_tooltip(int view_row, int column) const;
    // headerData(Horizontal, DisplayRole|ToolTipRole).
    std::string header_display(int section) const;
    std::string header_tooltip(int section) const;

private:
    AssetView build_view(const AssetHandle& asset) const;
    void apply_last_sort();
    bool view_inputs_unchanged() const;

    std::vector<AssetHandle> raw_assets_;
    std::vector<AssetView> views_;
    std::vector<int> filtered_rows_;
    std::vector<std::string> column_keys_;
    std::optional<std::filesystem::path> project_root_;
    const ViewEnricher* enricher_ = nullptr;
    // (project_root, enricher-token) — the tuple Python compares.
    std::optional<std::pair<std::optional<std::filesystem::path>, const void*>>
        view_build_token_;
    std::optional<std::pair<int, bool>> last_sort_;
    int last_rebuild_view_builds_ = 0;
};

}  // namespace pwb::ui_data_core
