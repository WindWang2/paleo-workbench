// filter_index.py port — FilterQuery / CatalogCounts / FilterIndex +
// compute_catalog_counts / compute_category_counts. Qt-free; works over
// AssetHandle inputs and AssetView rows.
#pragma once

#include "pwb/ui_data_core/asset_table_core.hpp"
#include "pwb/ui_data_core/asset_view.hpp"

#include <filesystem>
#include <optional>
#include <set>
#include <string>
#include <unordered_map>
#include <vector>

namespace pwb::ui_data_core {

// Module vocabularies.
const std::set<std::string>& issue_statuses();      // missing/warning/failed/error
const std::set<std::string>& reference_types();     // document/image_reference/...
const std::set<std::string>& auxiliary_types();     // document/image_reference/reference_map/tabular
// CATEGORIES — 全部 maps to no type (Python None).
const std::vector<std::pair<std::string, std::optional<std::string>>>&
categories();
const std::unordered_map<std::string, std::string>& status_labels();

struct FilterQuery {
    std::string node_type = "all";
    std::optional<std::string> node_value;
    std::string search_text;
    std::optional<std::string> stage;
    std::optional<std::string> data_type;
    std::optional<std::string> tag;
    std::optional<std::string> integrity;
    std::vector<std::string> tags;
    std::string tag_operator = "and";
    std::optional<std::string> review_status;
    std::optional<std::set<std::string>> entity_asset_ids;
    std::optional<std::string> entity_role;
    std::optional<std::string> asset_id;
};

struct CatalogCounts {
    int total = 0;
    std::unordered_map<std::string, int> stages;
    std::unordered_map<std::string, int> types;
    std::unordered_map<std::string, int> tags;
    std::unordered_map<std::string, int> integrity;
    std::unordered_map<std::string, int> categories;
    std::unordered_map<std::string, int> review_status;
    bool integrity_known = true;
};

class FilterIndex {
public:
    // rebuild(assets, project_root=None, enricher=None, views=None):
    // identical objects keep views+haystacks (#1063); caller views win (#527).
    void rebuild(std::vector<AssetHandle> assets,
                 const std::filesystem::path* project_root = nullptr,
                 const ViewEnricher* enricher = nullptr,
                 const std::vector<AssetView>* views = nullptr);

    const std::vector<AssetView>& views() const { return views_; }
    int last_rebuild_view_builds = 0;  // mirrors the Python attribute

    // Legacy filter(category, search_text) → row indices.
    std::vector<int> filter(const std::string& category,
                            const std::string& search_text) const;
    std::vector<int> filter_query(const FilterQuery& query) const;

    // _haystack(view) — the lowercased search corpus (public for tests).
    static std::string haystack(const AssetView& view);

private:
    bool matches_query(const AssetView& view, const FilterQuery& query) const;
    static FilterQuery parse_legacy_category(const std::string& category,
                                             const std::string& search_text);
    AssetView build_view(const AssetHandle& asset,
                         const std::filesystem::path* project_root,
                         const ViewEnricher* enricher) const;

    std::vector<AssetHandle> assets_;
    std::vector<AssetView> views_;
    std::vector<std::string> haystacks_;
    // (project_root, enricher-token) — the Python build token tuple.
    std::optional<
        std::pair<std::optional<std::filesystem::path>, const void*>>
        view_build_token_;
};

// compute_catalog_counts(resources, artifacts, project_root=None,
//                        extra_assets=None, enricher=None, views=None)
CatalogCounts compute_catalog_counts(
    const std::vector<ResourceItem>& resources,
    const std::vector<ExportArtifact>& artifacts,
    const std::filesystem::path* project_root = nullptr,
    const std::vector<AssetHandle>* extra_assets = nullptr,
    const ViewEnricher* enricher = nullptr,
    const std::vector<AssetView>* views = nullptr);

// compute_category_counts(resources, artifacts) → the .categories map only.
std::unordered_map<std::string, int> compute_category_counts(
    const std::vector<ResourceItem>& resources,
    const std::vector<ExportArtifact>& artifacts);

}  // namespace pwb::ui_data_core
