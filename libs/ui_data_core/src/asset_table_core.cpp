// asset_table_model.py — Qt-free model state + formatting (see header).

#include "pwb/ui_data_core/asset_table_core.hpp"

#include "pwb/ui_data_core/data_table_columns.hpp"
#include "pwb/ui_data_core/governance.hpp"

#include <algorithm>
#include <cctype>
#include <stdexcept>

namespace pwb::ui_data_core {

// ---------------------------------------------------------------------------
// RESOURCE_TYPE_LABELS — {**RESOURCE_LABELS, <page overrides>}
// ---------------------------------------------------------------------------

const std::unordered_map<std::string, std::string>& resource_type_labels() {
    static const std::unordered_map<std::string, std::string> map = [] {
        std::unordered_map<std::string, std::string> merged =
            tokens::resource_labels();
        // Page-level overrides (later wins — "horizon" → 层位 here).
        for (const auto& [k, v] : std::vector<std::pair<std::string, std::string>>{
                 {"spreadsheet", "表格"},       {"tabular", "表格"},
                 {"time_depth", "时深"},        {"horizon", "层位"},
                 {"well_stratification", "井分层"}, {"document", "文档"},
                 {"image_reference", "影像"},   {"reference_map", "参考图"},
                 {"well_reference", "测井参考"}, {"geojson", "GeoJSON矢量"},
                 {"vector", "矢量"},            {"unknown", "未知"},
             }) {
            merged[k] = v;
        }
        return merged;
    }();
    return map;
}

std::string review_status_display(const AssetView& view) {
    const std::string value = view.governance_get("review_status");
    return value.empty() ? "—" : governance_display("review_status", value);
}

// ---------------------------------------------------------------------------
// _format_cell_display / _format_cell_tooltip
// ---------------------------------------------------------------------------

std::string format_cell_display(const AssetView& view, std::string_view key) {
    if (key == "name") return view.name;
    if (key == "type") return view.type_label;
    if (key == "stage")
        return stage_icon(view.stage) + " " + stage_label(view.stage);
    if (key == "version") return view.current_version;
    if (key == "tags") {
        if (view.tags.empty()) return "—";
        std::string out;
        for (const auto& tag : view.tags) {
            if (!out.empty()) out += ", ";
            out += tag;
        }
        return out;
    }
    if (key == "managed") return view.managed ? "受管" : "外部";
    if (key == "integrity")
        return integrity_state_icon(view.integrity_state) + " " +
               integrity_state_label(view.integrity_state);
    if (key == "lineage")
        return view.lineage_status.empty() ? "—" : view.lineage_status;
    if (key == "review_status") return review_status_display(view);
    if (key == "format") return view.format;
    if (key == "status")
        return view.trashed ? view.trashed_label() : view.status;
    if (key == "role") {
        if (view.raw_asset) {
            const AssetObjectData& raw = *view.raw_asset;
            if (std::holds_alternative<ExportArtifact>(raw)) {
                return "成果";
            }
            if (const auto* res = std::get_if<ResourceItem>(&raw)) {
                const std::string role =
                    res->artifact_role.has_value() && !res->artifact_role->empty()
                        ? *res->artifact_role
                        : "input";
                if (role == "input") return "输入";
                if (role == "derived" || role == "export") return "成果";
                return role;
            }
        }
        return stage_label(view.stage);
    }
    if (key == "size") return view.size_formatted;
    if (key == "modified") return view.modified_at;
    if (key == "source") return view.source;
    if (key == "path") return view.path;
    return "";
}

std::string format_cell_tooltip(const AssetView& view, std::string_view key) {
    if (key == "stage")
        return "生命周期: " + stage_label(view.stage) + " (" +
               std::string(domain::to_string(view.stage)) + ")";
    if (key == "integrity")
        return "完整性: " + integrity_state_label(view.integrity_state) +
               "\n校验和: " + view.checksum_display();
    if (key == "lineage")
        return !view.lineage_status.empty()
                   ? "血缘: " + view.lineage_status
                   : "血缘: 未连接数据目录";
    if (key == "review_status") return "审核状态 (治理元数据)";
    if (key == "path") return view.path;
    if (key == "tags") {
        std::string joined;
        for (const auto& tag : view.tags) {
            if (!joined.empty()) joined += ", ";
            joined += tag;
        }
        return "标签: " + (joined.empty() ? std::string("无") : joined);
    }
    return format_cell_display(view, key);
}

// ---------------------------------------------------------------------------
// _sort_tuple
// ---------------------------------------------------------------------------

namespace {

// findall(r"\d+") → tuple(int(n) for n in ...) — digit runs in order.
std::vector<long long> digit_runs(const std::string& text) {
    std::vector<long long> out;
    std::size_t i = 0;
    while (i < text.size()) {
        if (!std::isdigit(static_cast<unsigned char>(text[i]))) {
            ++i;
            continue;
        }
        std::size_t j = i;
        while (j < text.size() &&
               std::isdigit(static_cast<unsigned char>(text[j]))) {
            ++j;
        }
        out.push_back(std::stoll(text.substr(i, j - i)));
        i = j;
    }
    return out;
}

}  // namespace

AssetSortKey asset_sort_key(const AssetView& view, std::string_view key) {
    AssetSortKey sk;
    if (key == "size") {
        if (!view.size_bytes.has_value()) {
            sk.missing = 1;
        } else {
            sk.kind = AssetSortKey::Kind::Nums;
            sk.nums = {*view.size_bytes};
        }
        return sk;
    }
    if (key == "version") {
        const std::string& text = view.current_version;
        if (text.empty() || text == "—") {
            sk.missing = 1;
            sk.kind = AssetSortKey::Kind::Nums;  // (1, (), "")
            return sk;
        }
        sk.kind = AssetSortKey::Kind::Nums;
        sk.nums = digit_runs(text);
        sk.text = text;
        return sk;
    }
    if (key == "type") {
        sk.text = !view.type_label.empty() ? view.type_label : view.type;
        return sk;
    }
    if (key == "modified") {
        if (view.modified_at.empty() || view.modified_at == "—") {
            sk.missing = 1;
        } else {
            sk.text = view.modified_at;
        }
        return sk;
    }
    // val = getattr(view, key, format_cell(view, key)); enum → .value;
    // None → "". The attribute-bearing keys land here; every other column
    // key falls back to the formatted display string.
    if (key == "managed") {
        sk.kind = AssetSortKey::Kind::Bool;
        sk.bool_value = view.managed;
        return sk;
    }
    if (key == "trashed") {
        sk.kind = AssetSortKey::Kind::Bool;
        sk.bool_value = view.trashed;
        return sk;
    }
    if (key == "tags") {
        sk.kind = AssetSortKey::Kind::StrList;
        sk.strs = view.tags;
        return sk;
    }
    if (key == "stage") {
        sk.text = std::string(domain::to_string(view.stage));
        return sk;
    }
    if (key == "integrity_state") {
        sk.text = std::string(integrity_state_value(view.integrity_state));
        return sk;
    }
    // Unorderable Python objects: LineageView / dicts / sets / raw objects —
    // tuple comparison between two of these raises TypeError.
    if (key == "lineage" || key == "versions" || key == "governance" ||
        key == "parsed_summary" || key == "catalog_metadata" ||
        key == "normalized_tags" || key == "raw_asset") {
        sk.kind = AssetSortKey::Kind::NonComparable;
        return sk;
    }
    if (key == "id") sk.text = view.id;
    else if (key == "name") sk.text = view.name;
    else if (key == "type_label") sk.text = view.type_label;
    else if (key == "format") sk.text = view.format;
    else if (key == "current_version") sk.text = view.current_version;
    else if (key == "status") sk.text = view.status;
    else if (key == "source") sk.text = view.source;
    else if (key == "path") sk.text = view.path;
    else if (key == "created_at") sk.text = view.created_at;
    else if (key == "modified_at") sk.text = view.modified_at;
    else if (key == "lineage_status") sk.text = view.lineage_status;
    else if (key == "crs") sk.text = view.crs.value_or("");
    else if (key == "checksum") sk.text = view.checksum.value_or("");
    else if (key == "trashed_at") sk.text = view.trashed_at.value_or("");
    else if (key == "size_formatted") sk.text = view.size_formatted;
    else {
        // getattr miss → the formatted display string.
        sk.text = format_cell_display(view, key);
    }
    return sk;
}

int asset_sort_key_compare(const AssetSortKey& a, const AssetSortKey& b) {
    if (a.missing != b.missing) {
        return a.missing < b.missing ? -1 : 1;
    }
    switch (a.kind) {
        case AssetSortKey::Kind::Bool:
            if (a.bool_value != b.bool_value) return a.bool_value ? 1 : -1;
            return 0;
        case AssetSortKey::Kind::Nums:
            if (a.nums != b.nums) return a.nums < b.nums ? -1 : 1;
            if (a.text != b.text) return a.text < b.text ? -1 : 1;
            return 0;
        case AssetSortKey::Kind::StrList:
            if (a.strs != b.strs) return a.strs < b.strs ? -1 : 1;
            return 0;
        case AssetSortKey::Kind::NonComparable:
            throw std::logic_error(
                "asset sort: unorderable column values (TypeError parity)");
        case AssetSortKey::Kind::Text:
        default:
            if (a.text != b.text) return a.text < b.text ? -1 : 1;
            return 0;
    }
}

// ---------------------------------------------------------------------------
// _match_positions_by_identity / _recycle_views
// ---------------------------------------------------------------------------

std::vector<std::optional<std::size_t>> match_positions_by_identity(
    const std::vector<AssetHandle>& old_assets,
    const std::vector<AssetHandle>& new_assets) {
    std::vector<std::optional<std::size_t>> matches;
    if (old_assets.empty()) {
        matches.assign(new_assets.size(), std::nullopt);
        return matches;
    }
    std::unordered_map<const void*, std::deque<std::size_t>> positions;
    for (std::size_t i = 0; i < old_assets.size(); ++i) {
        positions[asset_handle_identity(old_assets[i])].push_back(i);
    }
    matches.reserve(new_assets.size());
    for (const auto& asset : new_assets) {
        auto& bucket = positions[asset_handle_identity(asset)];
        if (!bucket.empty()) {
            matches.push_back(bucket.front());
            bucket.pop_front();
        } else {
            matches.push_back(std::nullopt);
        }
    }
    return matches;
}

std::vector<AssetView> recycle_views(
    const std::vector<AssetHandle>& old_assets,
    const std::vector<AssetView>& old_views,
    const std::vector<AssetHandle>& new_assets,
    const std::function<AssetView(const AssetHandle&)>& build_view) {
    const auto matches = match_positions_by_identity(old_assets, new_assets);
    std::vector<AssetView> out;
    out.reserve(new_assets.size());
    for (std::size_t i = 0; i < new_assets.size(); ++i) {
        if (matches[i].has_value() && *matches[i] < old_views.size()) {
            out.push_back(old_views[*matches[i]]);
        } else {
            out.push_back(build_view(new_assets[i]));
        }
    }
    return out;
}

// ---------------------------------------------------------------------------
// AssetTableCore
// ---------------------------------------------------------------------------

void AssetTableCore::set_project_root(const std::filesystem::path* root) {
    if (root != nullptr) {
        project_root_ = *root;
    } else {
        project_root_ = std::nullopt;
    }
}

void AssetTableCore::set_view_enricher(const ViewEnricher* enricher) {
    enricher_ = enricher;
}

void AssetTableCore::set_column_keys(std::vector<std::string> keys) {
    column_keys_ = std::move(keys);
    last_sort_ = std::nullopt;
}

bool AssetTableCore::view_inputs_unchanged() const {
    const auto token =
        std::make_pair(project_root_,
                       enricher_ != nullptr ? enricher_->token : nullptr);
    return view_build_token_.has_value() && *view_build_token_ == token;
}

AssetView AssetTableCore::build_view(const AssetHandle& asset) const {
    AssetView view = asset_view_from_object(
        asset, project_root_.has_value() ? &*project_root_ : nullptr);
    if (enricher_ != nullptr && enricher_->fn) {
        view = enricher_->fn(std::move(view));
    }
    return view;
}

void AssetTableCore::set_assets(std::vector<AssetHandle> assets) {
    int builds = 0;
    const bool can_reuse = view_inputs_unchanged();
    std::vector<AssetView> new_views;
    if (can_reuse) {
        new_views = recycle_views(
            raw_assets_, views_, assets,
            [&](const AssetHandle& a) {
                ++builds;
                return build_view(a);
            });
    } else {
        new_views.reserve(assets.size());
        for (const auto& asset : assets) {
            ++builds;
            new_views.push_back(build_view(asset));
        }
    }
    raw_assets_ = std::move(assets);
    views_ = std::move(new_views);
    view_build_token_ =
        std::make_pair(project_root_,
                       enricher_ != nullptr ? enricher_->token : nullptr);
    filtered_rows_.resize(raw_assets_.size());
    for (std::size_t i = 0; i < filtered_rows_.size(); ++i) {
        filtered_rows_[i] = static_cast<int>(i);
    }
    last_rebuild_view_builds_ = builds;
    apply_last_sort();
}

void AssetTableCore::set_filtered_rows(std::vector<int> rows) {
    filtered_rows_ = std::move(rows);
    apply_last_sort();
}

void AssetTableCore::set_assets_filtered(
    std::vector<AssetHandle> assets, std::vector<int> rows,
    const std::vector<std::string>* column_keys,
    const std::vector<AssetView>* views) {
    int builds = 0;
    std::vector<AssetView> new_views;
    if (views != nullptr && views->size() == assets.size()) {
        new_views = *views;  // caller-provided views win verbatim (#527)
    } else if (view_inputs_unchanged()) {
        new_views = recycle_views(
            raw_assets_, views_, assets,
            [&](const AssetHandle& a) {
                ++builds;
                return build_view(a);
            });
    } else {
        new_views.reserve(assets.size());
        for (const auto& asset : assets) {
            ++builds;
            new_views.push_back(build_view(asset));
        }
    }
    if (column_keys != nullptr) {
        column_keys_ = *column_keys;
    }
    raw_assets_ = std::move(assets);
    views_ = std::move(new_views);
    view_build_token_ =
        std::make_pair(project_root_,
                       enricher_ != nullptr ? enricher_->token : nullptr);
    filtered_rows_ = std::move(rows);
    last_rebuild_view_builds_ = builds;
    apply_last_sort();
}

void AssetTableCore::apply_last_sort() {
    if (!last_sort_.has_value()) {
        return;
    }
    const auto [column, descending] = *last_sort_;
    if (column < 0 || column >= static_cast<int>(column_keys_.size())) {
        return;
    }
    const std::string key = column_keys_[static_cast<std::size_t>(column)];
    std::stable_sort(filtered_rows_.begin(), filtered_rows_.end(),
                     [&](int lhs, int rhs) {
                         const AssetSortKey ka =
                             asset_sort_key(views_[static_cast<std::size_t>(lhs)], key);
                         const AssetSortKey kb =
                             asset_sort_key(views_[static_cast<std::size_t>(rhs)], key);
                         const int cmp = asset_sort_key_compare(ka, kb);
                         return descending ? cmp > 0 : cmp < 0;
                     });
}

void AssetTableCore::sort(int column, bool descending) {
    if (column < 0 || column >= static_cast<int>(column_keys_.size())) {
        return;
    }
    last_sort_ = std::make_pair(column, descending);
    apply_last_sort();
}

const AssetHandle* AssetTableCore::asset_at(int view_row) const {
    if (view_row < 0 || view_row >= static_cast<int>(filtered_rows_.size())) {
        return nullptr;
    }
    const int idx = filtered_rows_[static_cast<std::size_t>(view_row)];
    if (idx < 0 || idx >= static_cast<int>(raw_assets_.size())) {
        return nullptr;
    }
    return &raw_assets_[static_cast<std::size_t>(idx)];
}

const AssetView* AssetTableCore::view_at(int view_row) const {
    if (view_row < 0 || view_row >= static_cast<int>(filtered_rows_.size())) {
        return nullptr;
    }
    const int idx = filtered_rows_[static_cast<std::size_t>(view_row)];
    if (idx < 0 || idx >= static_cast<int>(views_.size())) {
        return nullptr;
    }
    return &views_[static_cast<std::size_t>(idx)];
}

std::string AssetTableCore::cell_display(int view_row, int column) const {
    const AssetView* view = view_at(view_row);
    if (view == nullptr || column < 0 ||
        column >= static_cast<int>(column_keys_.size())) {
        return "";
    }
    return format_cell_display(*view, column_keys_[static_cast<std::size_t>(column)]);
}

std::string AssetTableCore::cell_tooltip(int view_row, int column) const {
    const AssetView* view = view_at(view_row);
    if (view == nullptr || column < 0 ||
        column >= static_cast<int>(column_keys_.size())) {
        return "";
    }
    return format_cell_tooltip(*view, column_keys_[static_cast<std::size_t>(column)]);
}

std::string AssetTableCore::header_display(int section) const {
    if (section < 0 || section >= static_cast<int>(column_keys_.size())) {
        return "";
    }
    const ColumnDefinition* def =
        column_by_key(column_keys_[static_cast<std::size_t>(section)]);
    if (def == nullptr) {
        throw std::out_of_range("unknown column key (KeyError parity)");
    }
    return def->label;
}

std::string AssetTableCore::header_tooltip(int section) const {
    if (section < 0 || section >= static_cast<int>(column_keys_.size())) {
        return "";
    }
    const std::string& key = column_keys_[static_cast<std::size_t>(section)];
    const ColumnDefinition* def = column_by_key(key);
    if (def == nullptr) {
        throw std::out_of_range("unknown column key (KeyError parity)");
    }
    const auto& tooltips = column_tooltips();
    const auto it = tooltips.find(key);
    return it != tooltips.end() ? it->second : def->label;
}

}  // namespace pwb::ui_data_core
