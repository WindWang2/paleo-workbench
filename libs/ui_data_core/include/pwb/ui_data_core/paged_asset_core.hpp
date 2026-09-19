// paged_asset_model.py port — the Qt-free halves of the paged catalog
// browser:
//
// * ``CatalogPageProvider`` — FilterQuery → query-param translation +
//   deterministic pages + keyset-cursor bookkeeping + index-backed counts.
//   The ``source`` is the catalog query seam (DataCatalogService paged
//   facade or a raw CatalogIndex in tests).
// * ``PagedAssetCore`` — the PagedAssetTableModel state machine: honest
//   rowCount (index total), sparse bounded LRU page cache, coalesced
//   off-thread fetch scheduling, latest-only epoch, demand queue,
//   retry bookkeeping. Qt model signals are reduced to hooks the shell
//   implements.
//
// SqlCatalogAssetRef / _load_metadata / asset_view_from_sql_row live in
// asset_view.hpp/.cpp.
#pragma once

#include "pwb/ui_data_core/asset_table_core.hpp"
#include "pwb/ui_data_core/filter_index.hpp"

#include <deque>
#include <functional>
#include <list>
#include <optional>
#include <set>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

namespace pwb::ui_data_core {

inline constexpr int kPagedModeThreshold = 25'000;
inline constexpr int kPagedPageSize = 500;

// _UNMAPPABLE_NODE_TYPES — "integrity" needs a filesystem probe;
// "auxiliary" is legacy-only.
const std::set<std::string>& unmappable_node_types();
// MAX_SQL_ASSET_ID_SET — above this the chunked IN predicate degenerates.
inline constexpr int kMaxSqlAssetIdSet = 5'000;

// _COLUMN_TO_ORDER — table column key → SQL order key (nullopt when the
// column has no SQL equivalent).
std::optional<std::string> column_to_order(std::string_view column_key);

// ---------------------------------------------------------------------------
// CatalogPageSource — the query seam (search_assets_page / count_assets /
// catalog_aggregates keyword contract)
// ---------------------------------------------------------------------------

// snapshot_params() material: the frozen query one fetch carries. The same
// struct serves count_assets — sources read the fields they need.
struct PagedQueryParams {
    std::optional<std::string> text;
    std::optional<std::string> stage;  // DataStage|str passthrough
    std::vector<std::string> tags;
    std::string tag_op = "and";
    std::optional<std::string> type;
    std::optional<std::string> asset_id;
    std::vector<std::string> asset_ids;
    bool include_trashed = false;
    bool trashed_only = false;
    std::string order_by = "name";
    int generation = 0;
};

// Keyset cursor: (last_name, last_asset_id) of the previous sequential page.
using PagedKeyset = std::pair<std::string, std::string>;

class CatalogPageSource {
public:
    virtual ~CatalogPageSource() = default;
    // count_assets(**count_params).
    virtual long long count_assets(const PagedQueryParams& params) = 0;
    // search_assets_page(**params, offset, after) → row dicts.
    virtual std::vector<domain::Json> search_assets_page(
        const PagedQueryParams& params, int offset,
        const std::optional<PagedKeyset>& after) = 0;
    // catalog_aggregates() → group-by badges dict.
    virtual domain::Json catalog_aggregates() = 0;
    // cached_catalog_aggregates() — warm-only probe; raw-index sources have
    // none (default → nullopt).
    virtual std::optional<domain::Json> cached_catalog_aggregates();
};

// ---------------------------------------------------------------------------
// CatalogPageProvider — query translation + pages + cursor map
// ---------------------------------------------------------------------------

class CatalogPageProvider {
public:
    CatalogPageProvider(CatalogPageSource* source,
                        std::optional<std::filesystem::path> project_root =
                            std::nullopt);

    // index — backwards-compatible alias for the query source.
    CatalogPageSource* index() const { return source_; }
    int generation() const { return generation_; }
    const std::optional<std::filesystem::path>& project_root() const {
        return project_root_;
    }

    // Group-by badges; failures degrade to {}.
    domain::Json total_source_aggregates();
    // Warm aggregates only — nullopt lets the host defer the cold pass.
    std::optional<domain::Json> total_source_aggregates_cached();

    // apply_filter_query — translate a FilterQuery; false when unmappable.
    bool apply_filter_query(const FilterQuery& query);

    // snapshot_params — frozen query copy (raw include_trashed/trashed_only).
    PagedQueryParams snapshot_params() const;

    // total() — index-backed count under the CURRENT parameters.
    long long total() const;

    // page(offset, limit) — one page under the CURRENT query parameters.
    std::vector<AssetView> page(int offset,
                                std::optional<int> limit = std::nullopt);
    // page_with(params, offset, limit) — one page under a prior snapshot.
    std::vector<AssetView> page_with(const PagedQueryParams& params,
                                     int offset,
                                     std::optional<int> limit = std::nullopt);

    // set_order(column_key, descending) — false when no SQL order exists.
    bool set_order(const std::optional<std::string>& column_key,
                   bool descending);

private:
    PagedQueryParams count_params() const;
    std::optional<PagedKeyset> cursor_for_offset(int offset) const;

    CatalogPageSource* source_;  // non-owning
    std::optional<std::filesystem::path> project_root_;

    std::optional<std::string> text_;
    std::optional<std::string> stage_;
    std::optional<std::string> type_;
    std::vector<std::string> tags_;
    std::string tag_op_ = "and";
    std::optional<std::string> asset_id_;
    std::optional<std::vector<std::string>> asset_ids_;
    bool include_trashed_ = false;
    bool trashed_only_ = false;
    std::string order_by_ = "name";
    // offset → keyset cursor for the NEXT sequential page (value may be a
    // stored "no rows" marker).
    std::unordered_map<int, std::optional<PagedKeyset>> page_cursors_;
    // Bumped on every query/order change; a stale-epoch fetch must not
    // re-pollute the cursor map with the OLD query's cursor.
    int generation_ = 0;
};

// ---------------------------------------------------------------------------
// PagedAssetCore — the sparse, async page-cache state machine
// ---------------------------------------------------------------------------

class PagedAssetCore {
public:
    static constexpr int kPageCacheLimit = 24;   // pages resident
    static constexpr int kMaxInflight = 4;       // outstanding fetches
    static constexpr int kSeenKeysLimit = 8192;  // key→row memory

    struct Hooks {
        // Schedule one off-thread page fetch (the Qt shell pools
        // runnables). Must deliver on_page_ready/on_page_failed exactly
        // once per call.
        std::function<void(int epoch, int offset,
                           const PagedQueryParams& params)>
            start_fetch;
        // dataChanged(top, bottom) — resident rows whose content arrived.
        std::function<void(int top_row, int bottom_row)> rows_changed;
        // beginResetModel / endResetModel boundaries.
        std::function<void()> reset_begin;
        std::function<void()> reset_end;
    };

    PagedAssetCore(CatalogPageProvider* provider, Hooks hooks);

    CatalogPageProvider* provider() const { return provider_; }
    void set_provider(CatalogPageProvider* provider) { provider_ = provider; }

    // refresh — re-run the count, drop every cached page, serve page 0
    // synchronously (propagates provider failures like the Python).
    void refresh();
    // provider_page — synchronous single-page fetch (compat/tests); a
    // failed fetch degrades to {}.
    std::vector<AssetView> provider_page(int offset);
    bool apply_query(const FilterQuery& query);

    // canFetchMore / fetchMore / rowCount.
    bool can_fetch_more() const;
    void fetch_more();
    int row_count() const { return total_; }

    // view_at — resident view or nullptr (LRU touch on hit).
    const AssetView* view_at(int view_row);
    // data() DisplayRole path: resident view, or schedules the page and
    // returns nullptr (caller renders "…").
    const AssetView* view_or_schedule(int view_row);
    AssetHandle asset_at(int view_row);
    // Raw assets of the RESIDENT pages, in page order (bounded).
    std::vector<AssetHandle> assets();
    // Row of a previously-resident asset by stable key (LRU touch).
    std::optional<int> row_for_key(
        const std::optional<std::pair<std::string, std::string>>& key);

    // sort — the WHOLE result through SQL order, never the fetched prefix.
    // Returns false when the column has no SQL order.
    bool sort(std::string_view column_key, bool descending);
    std::optional<std::pair<std::string, bool>> last_sort() const {
        return last_sort_;
    }

    // Delivery sinks — the shell's _PageFetchSignals equivalents.
    void on_page_ready(int epoch, int offset, std::vector<AssetView> views);
    void on_page_failed(int epoch, int offset, const std::string& error);

    // Unsupported legacy entry points (kept explicit — TypeError parity).
    [[noreturn]] void set_assets(const std::vector<AssetHandle>&) const;
    [[noreturn]] void set_assets_filtered() const;
    [[noreturn]] void set_filtered_rows(const std::vector<int>&) const;

    int epoch() const { return epoch_; }
    int watermark() const { return watermark_; }
    int total() const { return total_; }
    std::size_t resident_pages() const { return pages_.size(); }
    std::size_t inflight_count() const { return inflight_.size(); }
    std::size_t demand_count() const { return demand_order_.size(); }

private:
    void request_page(int page_index, bool from_demand = false);
    void store_page(int offset, const std::vector<AssetView>& views);
    void advance_watermark();

    CatalogPageProvider* provider_;  // non-owning
    Hooks hooks_;

    int total_ = 0;
    // Page LRU — order list (front = oldest) + page map (OrderedDict).
    std::list<int> page_order_;
    std::unordered_map<int, std::vector<AssetView>> pages_;
    std::unordered_map<int, PagedQueryParams> inflight_;  // offset → params
    int epoch_ = 0;
    int watermark_ = 0;
    // seen_rows OrderedDict[(kind,id) → row], LRU-bounded.
    using RowKey = std::pair<std::string, std::string>;
    struct RowKeyHash {
        std::size_t operator()(const RowKey& k) const;
    };
    std::list<std::pair<RowKey, int>> seen_order_;
    std::unordered_map<RowKey, std::list<std::pair<RowKey, int>>::iterator,
                       RowKeyHash>
        seen_index_;
    // Demand queue — OrderedDict[int, None] FIFO.
    std::deque<int> demand_order_;
    std::set<int> demand_set_;
    // Per-page empty/failed attempt counts.
    std::unordered_map<int, int> attempts_;
    std::optional<std::pair<std::string, bool>> last_sort_;
};

}  // namespace pwb::ui_data_core
