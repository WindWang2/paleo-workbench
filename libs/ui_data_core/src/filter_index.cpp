// filter_index.py — see header for contract.

#include "pwb/ui_data_core/filter_index.hpp"

#include "pwb/catalog/entity_view.hpp"  // normalize_tag_name
#include "pwb/domain/text.hpp"          // lowercase_utf8 (#1391)
#include "pwb/ui_data_core/json_util.hpp"

#include <algorithm>
#include <deque>

namespace pwb::ui_data_core {

// ---------------------------------------------------------------------------
// Module vocabularies
// ---------------------------------------------------------------------------

const std::set<std::string>& issue_statuses() {
    static const std::set<std::string> set = {
        "missing", "warning", "failed", "error",
    };
    return set;
}

const std::set<std::string>& reference_types() {
    static const std::set<std::string> set = {
        "document", "image_reference", "reference_map", "well_reference",
    };
    return set;
}

const std::set<std::string>& auxiliary_types() {
    static const std::set<std::string> set = {
        "document", "image_reference", "reference_map", "tabular",
    };
    return set;
}

const std::vector<std::pair<std::string, std::optional<std::string>>>&
categories() {
    // CATEGORIES — declaration order; 全部 maps to no type (None).
    static const std::vector<std::pair<std::string, std::optional<std::string>>>
        map = {
            {"全部", std::nullopt},
            {"测井", "well_log"},
            {"地震", "seismic"},
            {"层位", "horizon"},
            {"井分层", "well_stratification"},
            {"时深", "time_depth"},
            {"表格", "tabular"},
            {"文档", "document"},
            {"影像", "image_reference"},
            {"参考图", "reference_map"},
            {"测井参考", "well_reference"},
            {"GeoJSON矢量", "geojson"},
            {"矢量", "vector"},
            {"未知", "unknown"},
        };
    return map;
}

const std::unordered_map<std::string, std::string>& status_labels() {
    static const std::unordered_map<std::string, std::string> map = {
        {"indexed", "已索引"},
        {"parsed", "已解析"},
        {"missing", "缺失"},
        {"warning", "警告"},   // STATUS_TEXT["warning"]
        {"failed", "异常"},    // STATUS_TEXT["failed"]
        {"error", "错误"},
        {"ready", "就绪"},     // STATUS_TEXT["ready"]
        {"generated", "已生成"},  // TASK_STATUS_LABELS["complete"]
    };
    return map;
}

namespace {

// #1391: Python folds search text with str.lower() — Unicode-aware, not
// ASCII-only — so an accented/Cyrillic/Greek asset name typed in any case
// still matches. lowercase_utf8 is the generated str.lower() table.
std::string lower_search_text(std::string_view value) {
    return pwb::domain::lowercase_utf8(value);
}

// str(getattr(raw, "id", "") or "") / legacy_resource_id pair per variant.
std::pair<std::string, std::string> raw_identity_fields(const AssetHandle& h) {
    std::string id;
    std::string legacy;
    if (!h) {
        return {id, legacy};
    }
    const AssetObjectData& raw = *h;
    if (const auto* res = std::get_if<ResourceItem>(&raw)) {
        id = res->id;
    } else if (const auto* art = std::get_if<ExportArtifact>(&raw)) {
        id = art->id;
    } else if (const auto* ref = std::get_if<SqlCatalogAssetRef>(&raw)) {
        id = ref->id;
    } else if (const auto* gen = std::get_if<GenericAsset>(&raw)) {
        const auto& attrs = gen->attrs;
        if (attrs.is_object()) {
            const auto iid = attrs.find("id");
            if (iid != attrs.end() && json_truthy(*iid)) {
                id = json_str(*iid);
            }
            const auto iled = attrs.find("legacy_resource_id");
            if (iled != attrs.end() && json_truthy(*iled)) {
                legacy = json_str(*iled);
            }
        }
    } else if (const auto* nested =
                   std::get_if<std::shared_ptr<AssetView>>(&raw)) {
        if (*nested) {
            id = (*nested)->id;
        }
    } else if (const auto* cat =
                   std::get_if<std::shared_ptr<const catalog::DataAsset>>(
                       &raw)) {
        if (*cat) {
            id = (*cat)->id.str();
            if ((*cat)->legacy_resource_id.has_value()) {
                legacy = *(*cat)->legacy_resource_id;
            }
        }
    }
    return {id, legacy};
}

}  // namespace

// ---------------------------------------------------------------------------
// FilterIndex::rebuild
// ---------------------------------------------------------------------------

AssetView FilterIndex::build_view(const AssetHandle& asset,
                                  const std::filesystem::path* project_root,
                                  const ViewEnricher* enricher) const {
    AssetView view = asset_view_from_object(asset, project_root);
    if (enricher != nullptr && enricher->fn) {
        view = enricher->fn(std::move(view));
    }
    return view;
}

void FilterIndex::rebuild(std::vector<AssetHandle> assets,
                          const std::filesystem::path* project_root,
                          const ViewEnricher* enricher,
                          const std::vector<AssetView>* views) {
    int builds = 0;
    auto build = [&](const AssetHandle& asset) {
        ++builds;
        return build_view(asset, project_root, enricher);
    };

    const auto token = std::make_pair(
        project_root != nullptr
            ? std::optional<std::filesystem::path>(*project_root)
            : std::nullopt,
        enricher != nullptr ? enricher->token : nullptr);

    std::vector<AssetHandle> new_assets = std::move(assets);
    if (views != nullptr && views->size() == new_assets.size()) {
        // Shared prebuilt views (#527) — verbatim, zero builds.
        views_ = *views;
        haystacks_.clear();
        haystacks_.reserve(views_.size());
        for (const auto& view : views_) {
            haystacks_.push_back(haystack(view));
        }
    } else if (view_build_token_.has_value() && *view_build_token_ == token &&
               !assets_.empty()) {
        // Recycle views+haystacks by identity (#1063).
        const auto matches = match_positions_by_identity(assets_, new_assets);
        std::vector<AssetView> old_views = std::move(views_);
        std::vector<std::string> old_haystacks = std::move(haystacks_);
        views_.clear();
        haystacks_.clear();
        views_.reserve(new_assets.size());
        haystacks_.reserve(new_assets.size());
        for (std::size_t i = 0; i < new_assets.size(); ++i) {
            const auto& m = matches[i];
            if (m.has_value() && *m < old_views.size()) {
                views_.push_back(std::move(old_views[*m]));
                haystacks_.push_back(std::move(old_haystacks[*m]));
            } else {
                AssetView view = build(new_assets[i]);
                haystacks_.push_back(haystack(view));
                views_.push_back(std::move(view));
            }
        }
    } else {
        views_.clear();
        haystacks_.clear();
        views_.reserve(new_assets.size());
        haystacks_.reserve(new_assets.size());
        for (const auto& asset : new_assets) {
            AssetView view = build(asset);
            haystacks_.push_back(haystack(view));
            views_.push_back(std::move(view));
        }
    }
    assets_ = std::move(new_assets);
    view_build_token_ = token;
    last_rebuild_view_builds = builds;
}

// ---------------------------------------------------------------------------
// filter / filter_query / _matches_query
// ---------------------------------------------------------------------------

std::vector<int> FilterIndex::filter(const std::string& category,
                                     const std::string& search_text) const {
    return filter_query(parse_legacy_category(category, search_text));
}

std::vector<int> FilterIndex::filter_query(const FilterQuery& query) const {
    const std::string needle = lower_search_text(strip_copy(query.search_text));
    std::vector<int> rows;
    for (std::size_t i = 0; i < views_.size(); ++i) {
        if (!matches_query(views_[i], query)) {
            continue;
        }
        if (!needle.empty() && haystacks_[i].find(needle) == std::string::npos) {
            continue;
        }
        rows.push_back(static_cast<int>(i));
    }
    return rows;
}

bool FilterIndex::matches_query(const AssetView& view,
                                const FilterQuery& query) const {
    // Trash separation: trashed rows only appear under node_type "trash".
    if (query.node_type == "trash") {
        if (!view.trashed) {
            return false;
        }
    } else if (view.trashed) {
        return false;
    }

    const std::string node_value = query.node_value.value_or("");
    const std::string stage_value = std::string(domain::to_string(view.stage));
    const std::string integrity_value =
        std::string(integrity_state_value(view.integrity_state));

    // `if query.node_value` — a present-but-empty value is FALSY (skips the
    // check entirely), not a match on "".
    const bool has_node_value =
        query.node_value.has_value() && !query.node_value->empty();
    if (query.node_type == "stage") {
        if (has_node_value && stage_value != node_value) {
            return false;
        }
    } else if (query.node_type == "stage_any") {
        std::set<std::string> stages;
        std::size_t pos = 0;
        while (pos <= node_value.size()) {
            const auto comma = node_value.find(',', pos);
            const std::string part = strip_copy(node_value.substr(
                pos, comma == std::string::npos ? std::string::npos
                                              : comma - pos));
            if (!part.empty()) {
                stages.insert(part);
            }
            if (comma == std::string::npos) {
                break;
            }
            pos = comma + 1;
        }
        if (stages.empty() || stages.count(stage_value) == 0) {
            return false;
        }
    } else if (query.node_type == "type") {
        if (has_node_value && view.type != node_value) {
            if (node_value == "other") {
                bool categorized = false;
                for (const auto& [label, type] : categories()) {
                    if (type.has_value() && *type == view.type) {
                        categorized = true;
                        break;
                    }
                }
                if (categorized) {
                    return false;
                }
            } else if (view.type != node_value) {
                return false;
            }
        }
    } else if (query.node_type == "auxiliary") {
        if (auxiliary_types().count(view.type) == 0) {
            return false;
        }
    } else if (query.node_type == "tag") {
        if (has_node_value) {
            const std::string target = catalog::normalize_tag_name(node_value);
            if (view.normalized_tags.count(target) == 0) {
                return false;
            }
        }
    } else if (query.node_type == "integrity") {
        if (has_node_value && integrity_value != node_value) {
            return false;
        }
    } else if (query.node_type == "review_status") {
        if (has_node_value &&
            view.governance_get("review_status") != node_value) {
            return false;
        }
    } else if (query.node_type == "legacy_category") {
        if (has_node_value && node_value != "全部") {
            if (view.raw_asset &&
                std::holds_alternative<ExportArtifact>(*view.raw_asset)) {
                return false;
            }
            // CATEGORIES.get(node_value) — miss → None → view.type != None
            // is always true → row excluded.
            std::optional<std::string> target;
            bool known = false;
            for (const auto& [label, type] : categories()) {
                if (label == node_value) {
                    target = type;
                    known = true;
                    break;
                }
            }
            if (!known) {
                return false;
            }
            if (!target.has_value() || view.type != *target) {
                return false;
            }
        }
    } else if (query.node_type == "entity" ||
               query.node_type == "entity_group") {
        if (!query.entity_asset_ids.has_value() ||
            query.entity_asset_ids->empty()) {
            return false;
        }
        const auto [id, legacy] = raw_identity_fields(view.raw_asset);
        bool hit = false;
        for (const std::string& row_id : {id, legacy}) {
            if (query.entity_asset_ids->count(row_id) != 0) {
                hit = true;
                break;
            }
        }
        if (!hit) {
            return false;
        }
    }

    // 2. Multi-dimensional secondary criteria — `if query.x` is truthiness:
    // a present-empty string skips the check.
    if (query.stage.has_value() && !query.stage->empty() &&
        stage_value != *query.stage) {
        return false;
    }
    if (query.data_type.has_value() && !query.data_type->empty() &&
        view.type != *query.data_type) {
        return false;
    }
    std::vector<std::string> tag_criteria;
    for (const auto& tag : query.tags) {
        // [t for t in tags if t and str(t).strip()]
        if (!tag.empty() && !strip_copy(tag).empty()) {
            tag_criteria.push_back(tag);
        }
    }
    if (query.tag.has_value()) {
        tag_criteria.push_back(*query.tag);
    }
    if (!tag_criteria.empty()) {
        std::set<std::string> targets;
        for (const auto& tag : tag_criteria) {
            if (!strip_copy(tag).empty()) {
                targets.insert(catalog::normalize_tag_name(tag));
            }
        }
        if (!targets.empty()) {
            if (query.tag_operator == "or") {
                bool any = false;
                for (const auto& t : targets) {
                    if (view.normalized_tags.count(t) != 0) {
                        any = true;
                        break;
                    }
                }
                if (!any) {
                    return false;
                }
            } else {
                for (const auto& t : targets) {
                    if (view.normalized_tags.count(t) == 0) {
                        return false;
                    }
                }
            }
        }
    }
    if (query.integrity.has_value() && !query.integrity->empty() &&
        integrity_value != *query.integrity) {
        return false;
    }
    if (query.review_status.has_value() && !query.review_status->empty() &&
        view.governance_get("review_status") != *query.review_status) {
        return false;
    }
    return true;
}

// ---------------------------------------------------------------------------
// _parse_legacy_category
// ---------------------------------------------------------------------------

FilterQuery FilterIndex::parse_legacy_category(
    const std::string& category, const std::string& search_text) {
    if (category.empty() || category == "全部") {
        FilterQuery q;
        q.node_type = "all";
        q.search_text = search_text;
        return q;
    }
    if (category == "回收站" || category == "trash" || category == "Trash") {
        FilterQuery q;
        q.node_type = "trash";
        q.search_text = search_text;
        return q;
    }
    struct StageAlias {
        const char* value;
        const char* label;
        const char* zh;
        const char* upper;
        const char* node_value;
    };
    static const StageAlias stage_aliases[] = {
        {"raw", "原始输入", "原始输入", "RAW", "raw"},
        {"derived", "派生数据", "派生数据", "DERIVED", "derived"},
        {"intermediate", "中间结果", "中间结果", "INTERMEDIATE", "intermediate"},
        {"output", "输出成果", "输出成果", "OUTPUT", "output"},
    };
    for (const auto& alias : stage_aliases) {
        if (category == alias.value || category == alias.label ||
            category == alias.upper) {
            FilterQuery q;
            q.node_type = "stage";
            q.node_value = alias.node_value;
            q.search_text = search_text;
            return q;
        }
    }
    if (category.rfind("tag:", 0) == 0 || category.rfind("#", 0) == 0) {
        // category.split(":", 1)[-1].lstrip("#")
        std::string tag_name = category;
        const auto colon = tag_name.find(':');
        if (colon != std::string::npos) {
            tag_name = tag_name.substr(colon + 1);
        }
        std::size_t first = tag_name.find_first_not_of('#');
        tag_name = first == std::string::npos ? "" : tag_name.substr(first);
        FilterQuery q;
        q.node_type = "tag";
        q.node_value = tag_name;
        q.search_text = search_text;
        return q;
    }
    for (const auto& [label, type] : categories()) {
        if (label == category) {
            FilterQuery q;
            q.node_type = "legacy_category";
            q.node_value = category;
            q.search_text = search_text;
            return q;
        }
    }
    FilterQuery q;
    q.node_type = "legacy_category";
    q.node_value = category;
    q.search_text = search_text;
    return q;
}

// ---------------------------------------------------------------------------
// _haystack
// ---------------------------------------------------------------------------

std::string FilterIndex::haystack(const AssetView& view) {
    const auto& labels = status_labels();
    const auto sit = labels.find(view.status);
    const std::string status_zh =
        sit != labels.end() ? sit->second : view.status;
    const std::string stage_zh = stage_label(view.stage);
    const std::string integrity_zh = integrity_state_label(view.integrity_state);
    const auto& res_labels = resource_type_labels();
    const auto rit = res_labels.find(view.type);
    const std::string res_type_zh =
        rit != res_labels.end() ? rit->second : view.type;

    std::vector<std::string> parts;
    parts.push_back(view.name);
    parts.push_back(view.type);
    parts.push_back(view.type_label);
    parts.push_back(res_type_zh);
    parts.push_back(view.format);
    parts.push_back(std::string(domain::to_string(view.stage)));
    parts.push_back(stage_zh);
    parts.push_back(view.current_version);
    {
        std::string joined;
        for (const auto& tag : view.tags) {
            if (!joined.empty()) joined += " ";
            joined += tag;
        }
        parts.push_back(joined);
    }
    parts.push_back(view.managed ? "受管" : "外部 external");
    parts.push_back(std::string(integrity_state_value(view.integrity_state)));
    parts.push_back(integrity_zh);
    parts.push_back(view.checksum.value_or(""));
    parts.push_back(view.status);
    parts.push_back(status_zh);
    parts.push_back(view.source);
    parts.push_back(view.path);
    parts.push_back(view.lineage_status);
    {
        std::string joined;
        for (const auto& [key, value] : view.governance) {
            if (!joined.empty()) joined += " ";
            joined += value;
        }
        parts.push_back(joined);
    }
    if (json_truthy(view.parsed_summary)) {
        parts.push_back(python_repr(view.parsed_summary));
    }
    // " ".join(str(p) for p in parts if p).lower()
    std::string out;
    for (const auto& part : parts) {
        if (part.empty()) {
            continue;
        }
        if (!out.empty()) {
            out += " ";
        }
        out += part;
    }
    return lower_search_text(out);
}

// ---------------------------------------------------------------------------
// compute_catalog_counts / compute_category_counts
// ---------------------------------------------------------------------------

CatalogCounts compute_catalog_counts(
    const std::vector<ResourceItem>& resources,
    const std::vector<ExportArtifact>& artifacts,
    const std::filesystem::path* project_root,
    const std::vector<AssetHandle>* extra_assets,
    const ViewEnricher* enricher,
    const std::vector<AssetView>* views) {
    const std::size_t asset_total =
        resources.size() + artifacts.size() +
        (extra_assets != nullptr ? extra_assets->size() : 0);
    std::vector<AssetView> use_views;
    if (views != nullptr && views->size() == asset_total) {
        use_views = *views;
    } else {
        use_views.reserve(asset_total);
        auto build = [&](const AssetHandle& handle) {
            AssetView view = asset_view_from_object(handle, project_root);
            if (enricher != nullptr && enricher->fn) {
                view = enricher->fn(std::move(view));
            }
            return view;
        };
        for (const auto& resource : resources) {
            use_views.push_back(build(make_asset_handle(resource)));
        }
        for (const auto& artifact : artifacts) {
            use_views.push_back(build(make_asset_handle(artifact)));
        }
        if (extra_assets != nullptr) {
            for (const auto& asset : *extra_assets) {
                use_views.push_back(build(asset));
            }
        }
    }

    CatalogCounts counts;
    counts.total = static_cast<int>(use_views.size());
    std::unordered_map<std::string, int> tag_counter;
    for (const auto& view : use_views) {
        counts.stages[std::string(domain::to_string(view.stage))] += 1;
        counts.types[view.type] += 1;
        counts.integrity[std::string(
            integrity_state_value(view.integrity_state))] += 1;
        const std::string review = view.governance_get("review_status");
        if (!review.empty()) {
            counts.review_status[review] += 1;
        }
        for (const auto& tag : view.tags) {
            tag_counter[strip_copy(tag)] += 1;
        }
    }
    counts.tags = std::move(tag_counter);

    // Legacy category counts (resources only for type leaves).
    std::unordered_map<std::string, int> legacy_type_counts;
    for (const auto& resource : resources) {
        legacy_type_counts[resource.type] += 1;
    }
    counts.categories["全部"] = counts.total;
    for (const auto& [label, rtype] : categories()) {
        if (label == "全部") {
            continue;
        }
        counts.categories[label] =
            rtype.has_value() ? legacy_type_counts[*rtype] : 0;
    }
    return counts;
}

std::unordered_map<std::string, int> compute_category_counts(
    const std::vector<ResourceItem>& resources,
    const std::vector<ExportArtifact>& artifacts) {
    return compute_catalog_counts(resources, artifacts).categories;
}

}  // namespace pwb::ui_data_core
