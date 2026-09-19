#include "pwb/ui_data_core/paged_asset_core.hpp"

#include "pwb/ui_data_core/json_util.hpp"

#include <algorithm>
#include <stdexcept>
#include <utility>

namespace pwb::ui_data_core {
namespace {

// _COLUMN_TO_ORDER
const std::unordered_map<std::string, std::string>& column_order_map() {
    static const std::unordered_map<std::string, std::string> map = {
        {"name", "name"},       {"type", "type"},     {"stage", "stage"},
        {"size", "size"},       {"modified", "modified"},
        {"version", "version"},
    };
    return map;
}

// Truthiness of an optional<string> (Python `if value:`).
bool opt_truthy(const std::optional<std::string>& value) {
    return value.has_value() && !value->empty();
}

// views[-1].raw_asset.id — the SqlCatalogAssetRef id.
std::string last_raw_id(const AssetView& view) {
    if (view.raw_asset) {
        if (const auto* ref =
                std::get_if<SqlCatalogAssetRef>(view.raw_asset.get())) {
            return ref->id;
        }
    }
    return {};
}

}  // namespace

const std::set<std::string>& unmappable_node_types() {
    static const std::set<std::string> types = {"integrity", "auxiliary"};
    return types;
}

std::optional<std::string> column_to_order(std::string_view column_key) {
    const auto it = column_order_map().find(std::string(column_key));
    if (it == column_order_map().end()) {
        return std::nullopt;
    }
    return it->second;
}

// ---------------------------------------------------------------------------
// CatalogPageSource
// ---------------------------------------------------------------------------

std::optional<domain::Json> CatalogPageSource::cached_catalog_aggregates() {
    return std::nullopt;  // raw-index source: no cheap freshness probe
}

// ---------------------------------------------------------------------------
// CatalogPageProvider
// ---------------------------------------------------------------------------

CatalogPageProvider::CatalogPageProvider(
    CatalogPageSource* source, std::optional<std::filesystem::path> project_root)
    : source_(source), project_root_(std::move(project_root)) {}

domain::Json CatalogPageProvider::total_source_aggregates() {
    try {
        domain::Json value = source_->catalog_aggregates();
        return json_truthy(value) ? value : domain::Json::object();
    } catch (...) {
        return domain::Json::object();
    }
}

std::optional<domain::Json>
CatalogPageProvider::total_source_aggregates_cached() {
    try {
        return source_->cached_catalog_aggregates();
    } catch (...) {
        return std::nullopt;
    }
}

bool CatalogPageProvider::apply_filter_query(const FilterQuery& query) {
    const std::string node_type =
        query.node_type.empty() ? "all" : query.node_type;
    if (unmappable_node_types().count(node_type) != 0) {
        return false;
    }
    const auto& stage = query.stage;
    const auto& data_type = query.data_type;
    std::vector<std::string> tags = query.tags;
    if (opt_truthy(query.tag)) {
        tags.push_back(*query.tag);
    }
    if (opt_truthy(query.review_status)) {
        // review_status filters through the metadata JSON path; the paged
        // path keeps it simple by refusing (rare smart view).
        return false;
    }
    if (node_type == "entity" || node_type == "entity_group") {
        std::vector<std::string> ids;
        if (query.entity_asset_ids.has_value()) {
            ids.assign(query.entity_asset_ids->begin(),
                       query.entity_asset_ids->end());
            std::sort(ids.begin(), ids.end());
        }
        if (ids.empty() ||
            static_cast<int>(ids.size()) > kMaxSqlAssetIdSet) {
            return false;
        }
        asset_ids_ = std::move(ids);
    } else {
        asset_ids_ = std::nullopt;
    }
    text_ = [&]() -> std::optional<std::string> {
        const std::string stripped = strip_copy(query.search_text);
        return stripped.empty() ? std::nullopt
                                : std::optional<std::string>(stripped);
    }();
    stage_ = stage;
    type_ = data_type;
    tags_ = tags;
    tag_op_ = query.tag_operator.empty() ? "and" : query.tag_operator;
    asset_id_ = query.asset_id;
    include_trashed_ = false;
    trashed_only_ = node_type == "trash";
    generation_ += 1;
    page_cursors_.clear();  // a new result set invalidates every cursor
    if (node_type == "stage") {
        stage_ = opt_truthy(query.node_value) ? query.node_value : stage;
    } else if (node_type == "type") {
        type_ = opt_truthy(query.node_value) ? query.node_value : data_type;
    } else if (node_type == "tag") {
        if (opt_truthy(query.node_value)) {
            std::vector<std::string> merged{*query.node_value};
            merged.insert(merged.end(), tags.begin(), tags.end());
            tags_ = std::move(merged);
        }
    } else if (node_type == "legacy_category") {
        // Legacy categories map onto resource types; the caller keeps the
        // resource-side view, the SQL side stays unfiltered here.
        type_ = query.data_type;
    }
    return true;
}

PagedQueryParams CatalogPageProvider::snapshot_params() const {
    PagedQueryParams params;
    params.text = text_;
    params.stage = stage_;
    params.tags = tags_;
    params.tag_op = tag_op_;
    params.type = type_;
    params.asset_id = asset_id_;
    params.asset_ids = asset_ids_.value_or(std::vector<std::string>{});
    params.include_trashed = include_trashed_;
    params.trashed_only = trashed_only_;
    params.order_by = order_by_;
    params.generation = generation_;
    return params;
}

PagedQueryParams CatalogPageProvider::count_params() const {
    PagedQueryParams params;
    params.text = text_;
    params.stage = stage_;
    params.tags = tags_;
    params.tag_op = tag_op_;
    params.type = type_;
    params.asset_id = asset_id_;
    if (asset_ids_.has_value()) {
        params.asset_ids = *asset_ids_;
    }
    params.include_trashed = include_trashed_ || trashed_only_;
    params.trashed_only = trashed_only_;
    return params;
}

long long CatalogPageProvider::total() const {
    return source_->count_assets(count_params());
}

std::vector<AssetView> CatalogPageProvider::page(
    int offset, std::optional<int> limit) {
    return page_with(snapshot_params(), offset, limit);
}

std::vector<AssetView> CatalogPageProvider::page_with(
    const PagedQueryParams& params, int offset, std::optional<int> limit) {
    const int lim = limit.value_or(kPagedPageSize);
    std::optional<PagedKeyset> keyset;
    const std::string order_by =
        params.order_by.empty() ? "name" : params.order_by;
    if (order_by == "name" && offset > 0) {
        // The cursor is the last row of the previous sequential page —
        // cached so repeated fetchMore calls do not re-read it.
        keyset = cursor_for_offset(offset);
    }
    PagedQueryParams fetch = params;
    fetch.order_by = order_by;
    const std::vector<domain::Json> rows = source_->search_assets_page(
        fetch, keyset.has_value() ? 0 : offset, keyset);
    std::vector<AssetView> views;
    views.reserve(rows.size());
    const std::filesystem::path* root =
        project_root_.has_value() ? &*project_root_ : nullptr;
    for (const auto& row : rows) {
        views.push_back(asset_view_from_sql_row(row, root));
    }
    if (order_by == "name" && params.generation == generation_) {
        // Stale-epoch fetches (query changed mid-flight) must not seed the
        // NEW query's cursor map with their own boundary.
        const int next_offset = offset + static_cast<int>(views.size());
        if (views.empty()) {
            page_cursors_[next_offset] = std::nullopt;
        } else {
            page_cursors_[next_offset] =
                PagedKeyset{views.back().name, last_raw_id(views.back())};
        }
    }
    return views;
}

std::optional<PagedKeyset> CatalogPageProvider::cursor_for_offset(
    int offset) const {
    // Exact page boundary; a miss degrades to OFFSET paging for one call.
    const auto it = page_cursors_.find(offset);
    if (it == page_cursors_.end()) {
        return std::nullopt;
    }
    return it->second;  // may itself be a stored nullopt marker
}

bool CatalogPageProvider::set_order(
    const std::optional<std::string>& column_key, bool descending) {
    if (column_key.has_value() && *column_key == "name" && descending) {
        order_by_ = "name_desc";
        generation_ += 1;
        page_cursors_.clear();
        return true;
    }
    const auto order = column_to_order(column_key.value_or(""));
    if (!order.has_value()) {
        return false;
    }
    order_by_ = *order;
    generation_ += 1;
    page_cursors_.clear();
    return true;
}

// ---------------------------------------------------------------------------
// PagedAssetCore
// ---------------------------------------------------------------------------

std::size_t PagedAssetCore::RowKeyHash::operator()(const RowKey& k) const {
    return std::hash<std::string>{}(k.first) ^
           (std::hash<std::string>{}(k.second) << 1U);
}

PagedAssetCore::PagedAssetCore(CatalogPageProvider* provider, Hooks hooks)
    : provider_(provider), hooks_(std::move(hooks)) {}

void PagedAssetCore::refresh() {
    epoch_ += 1;
    pages_.clear();
    page_order_.clear();
    inflight_.clear();
    demand_order_.clear();
    demand_set_.clear();
    attempts_.clear();
    seen_order_.clear();
    seen_index_.clear();
    total_ = static_cast<int>(provider_->total());
    if (hooks_.reset_begin) {
        hooks_.reset_begin();
    }
    std::vector<AssetView> first = provider_->page(0);
    if (!first.empty()) {
        store_page(0, first);
    }
    if (hooks_.reset_end) {
        hooks_.reset_end();
    }
    watermark_ = !first.empty() ? 1 : 0;
    if (watermark_ * kPagedPageSize < total_) {
        request_page(watermark_);
    }
}

std::vector<AssetView> PagedAssetCore::provider_page(int offset) {
    try {
        return provider_->page(offset);
    } catch (...) {
        return {};
    }
}

bool PagedAssetCore::apply_query(const FilterQuery& query) {
    if (!provider_->apply_filter_query(query)) {
        return false;
    }
    refresh();
    return true;
}

bool PagedAssetCore::can_fetch_more() const {
    return watermark_ * kPagedPageSize < total_;
}

void PagedAssetCore::fetch_more() {
    request_page(watermark_);
}

const AssetView* PagedAssetCore::view_at(int view_row) {
    if (view_row < 0 || view_row >= total_) {
        return nullptr;
    }
    const int page_index = view_row / kPagedPageSize;
    const auto it = pages_.find(page_index);
    if (it == pages_.end()) {
        return nullptr;
    }
    const int within = view_row % kPagedPageSize;
    if (within >= static_cast<int>(it->second.size())) {
        return nullptr;
    }
    // move_to_end — LRU touch.
    page_order_.remove(page_index);
    page_order_.push_back(page_index);
    return &it->second[within];
}

const AssetView* PagedAssetCore::view_or_schedule(int view_row) {
    if (const AssetView* view = view_at(view_row)) {
        return view;
    }
    if (view_row >= 0 && view_row < total_) {
        // Uncached row: serve the placeholder AND schedule its page.
        request_page(view_row / kPagedPageSize, /*from_demand=*/true);
    }
    return nullptr;
}

AssetHandle PagedAssetCore::asset_at(int view_row) {
    const AssetView* view = view_at(view_row);
    return view != nullptr ? view->raw_asset : nullptr;
}

std::vector<AssetHandle> PagedAssetCore::assets() {
    // OrderedDict.values() order — page_order_ front → back.
    std::vector<AssetHandle> out;
    for (const int page_index : page_order_) {
        for (const auto& view : pages_.at(page_index)) {
            out.push_back(view.raw_asset);
        }
    }
    return out;
}

std::optional<int> PagedAssetCore::row_for_key(
    const std::optional<RowKey>& key) {
    if (!key.has_value()) {
        return std::nullopt;
    }
    const auto it = seen_index_.find(*key);
    if (it == seen_index_.end()) {
        return std::nullopt;
    }
    const int row = it->second->second;
    // move_to_end — LRU touch.
    seen_order_.splice(seen_order_.end(), seen_order_, it->second);
    return row;
}

bool PagedAssetCore::sort(std::string_view column_key, bool descending) {
    if (!provider_->set_order(std::string(column_key), descending)) {
        return false;
    }
    last_sort_ = {std::string(column_key), descending};
    refresh();
    return true;
}

void PagedAssetCore::on_page_ready(int epoch, int offset,
                                   std::vector<AssetView> views) {
    inflight_.erase(offset);
    if (epoch != epoch_) {
        return;  // stale query: latest-only, drop on arrival
    }
    if (views.empty() && offset * kPagedPageSize < total_) {
        // An EMPTY page BEFORE the reported total is suspicious — retry a
        // bounded number of times instead of truncating the table.
        const int attempts = attempts_[offset] + 1;
        attempts_[offset] = attempts;
        if (attempts < 3) {
            request_page(offset, /*from_demand=*/true);
            return;
        }
        // Honest degradation: rowCount is about to change, so wrap the
        // shrink in reset signals (Qt contract).
        if (hooks_.reset_begin) {
            hooks_.reset_begin();
        }
        total_ = std::min(total_, offset * kPagedPageSize);
        if (hooks_.reset_end) {
            hooks_.reset_end();
        }
    }
    attempts_.erase(offset);
    if (views.empty()) {
        if (offset == watermark_) {
            advance_watermark();
        }
        return;
    }
    store_page(offset, views);
    const int top = offset * kPagedPageSize;
    int bottom = top + static_cast<int>(views.size()) - 1;
    if (bottom >= total_) {
        bottom = total_ - 1;
    }
    if (bottom >= top && hooks_.rows_changed) {
        hooks_.rows_changed(top, bottom);
    }
    if (offset == watermark_) {
        advance_watermark();
    }
    // One-page lookahead keeps sequential scrolling smooth.
    request_page(watermark_);
    // Saturated demand first, then the next sequential page.
    while (!demand_order_.empty() &&
           static_cast<int>(inflight_.size()) < kMaxInflight) {
        const int demanded = demand_order_.front();
        demand_order_.pop_front();
        demand_set_.erase(demanded);
        request_page(demanded, /*from_demand=*/true);
    }
}

void PagedAssetCore::on_page_failed(int epoch, int offset,
                                    const std::string& /*error*/) {
    inflight_.erase(offset);
    if (epoch != epoch_) {
        return;
    }
    attempts_[offset] += 1;
    if (attempts_[offset] < 3) {
        request_page(offset, /*from_demand=*/true);
    }
}

void PagedAssetCore::request_page(int page_index, bool from_demand) {
    if (page_index * kPagedPageSize >= total_) {
        return;
    }
    if (pages_.count(page_index) != 0 || inflight_.count(page_index) != 0) {
        if (demand_set_.erase(page_index) != 0) {
            demand_order_.erase(
                std::remove(demand_order_.begin(), demand_order_.end(),
                            page_index),
                demand_order_.end());
        }
        return;
    }
    if (static_cast<int>(inflight_.size()) >= kMaxInflight) {
        // Saturated: remember the demand and re-issue on the next
        // completion — a scrollbar jump must recover by itself.
        if (from_demand) {
            if (demand_set_.insert(page_index).second) {
                demand_order_.push_back(page_index);
            } else {
                // move_to_end
                demand_order_.erase(
                    std::remove(demand_order_.begin(), demand_order_.end(),
                                page_index),
                    demand_order_.end());
                demand_order_.push_back(page_index);
            }
        }
        return;
    }
    if (demand_set_.erase(page_index) != 0) {
        demand_order_.erase(
            std::remove(demand_order_.begin(), demand_order_.end(),
                        page_index),
            demand_order_.end());
    }
    PagedQueryParams params = provider_->snapshot_params();
    inflight_[page_index] = params;
    if (hooks_.start_fetch) {
        hooks_.start_fetch(epoch_, page_index, params);
    }
}

void PagedAssetCore::store_page(int offset,
                                const std::vector<AssetView>& views) {
    const bool existed = pages_.count(offset) != 0;
    pages_[offset] = views;
    if (existed) {
        page_order_.remove(offset);
    }
    page_order_.push_back(offset);
    while (static_cast<int>(pages_.size()) > kPageCacheLimit) {
        const int oldest = page_order_.front();
        page_order_.pop_front();
        pages_.erase(oldest);
    }
    for (std::size_t within = 0; within < views.size(); ++within) {
        const RowKey key = {"resource", views[within].id};
        const int row = offset * kPagedPageSize + static_cast<int>(within);
        const auto it = seen_index_.find(key);
        if (it != seen_index_.end()) {
            it->second->second = row;
            seen_order_.splice(seen_order_.end(), seen_order_, it->second);
        } else {
            seen_order_.emplace_back(key, row);
            auto map_it = seen_order_.end();
            --map_it;
            seen_index_[key] = map_it;
        }
    }
    while (static_cast<int>(seen_order_.size()) > kSeenKeysLimit) {
        seen_index_.erase(seen_order_.front().first);
        seen_order_.pop_front();
    }
}

void PagedAssetCore::advance_watermark() {
    while (watermark_ * kPagedPageSize < total_ &&
           pages_.count(watermark_) != 0) {
        watermark_ += 1;
    }
}

void PagedAssetCore::set_assets(const std::vector<AssetHandle>&) const {
    throw std::logic_error(
        "PagedAssetTableModel is provider-backed; use refresh()");
}

void PagedAssetCore::set_assets_filtered() const {
    throw std::logic_error(
        "PagedAssetTableModel is provider-backed; use apply_query()");
}

void PagedAssetCore::set_filtered_rows(const std::vector<int>&) const {
    throw std::logic_error(
        "PagedAssetTableModel is provider-backed; use apply_query()");
}

}  // namespace pwb::ui_data_core
