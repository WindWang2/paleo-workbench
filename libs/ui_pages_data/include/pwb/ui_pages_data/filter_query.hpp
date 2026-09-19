// UI-06 — FilterQuery / CatalogCounts value types.
//
// Stand-ins for UI-03's pages/filter_index.py dataclasses (not yet ported).
// Field-for-field POD replicas; when UI-03 lands these should be replaced
// by its types — the layout below mirrors the Python source 1:1 so the swap
// is mechanical. Every consumer in this library already only touches the
// same fields the Python files touch.
#pragma once

#include <map>
#include <optional>
#include <set>
#include <string>
#include <vector>

namespace pwb::ui_pages_data {

// pages/filter_index.py :: FilterQuery (dataclass, 14 fields).
struct FilterQuery {
    // Vocabulary: "all", "stage", "type", "tag", "integrity",
    // "review_status", "trash", "legacy_category", plus domain nodes
    // "entity" / "entity_group" / "overview" / "auxiliary" / "stage_any".
    std::string node_type = "all";
    std::optional<std::string> node_value;
    std::string search_text;
    std::optional<std::string> stage;
    std::optional<std::string> data_type;
    // Legacy singular tag field — unioned into `tags` at match time.
    std::optional<std::string> tag;
    std::optional<std::string> integrity;
    // Multi-tag secondary criteria combined with tag_operator.
    std::vector<std::string> tags;
    std::string tag_operator = "and";
    std::optional<std::string> review_status;
    // Entity-node membership set; nullopt disables entity matching.
    std::optional<std::set<std::string>> entity_asset_ids;
    std::optional<std::string> entity_role;
    // Single-asset refinement for entity file leaves.
    std::optional<std::string> asset_id;
};

// pages/filter_index.py :: CatalogCounts (dataclass).
struct CatalogCounts {
    int total = 0;
    std::map<std::string, int> stages;
    std::map<std::string, int> types;
    std::map<std::string, int> tags;
    std::map<std::string, int> integrity;
    std::map<std::string, int> categories;
    std::map<std::string, int> review_status;
    // C-P0-1: false when the aggregate source lacks integrity probing —
    // the overview panel must show "—" rather than fabricate 0.
    bool integrity_known = true;
};

}  // namespace pwb::ui_pages_data
