#pragma once

// UI-11 — impact_preview_dialog.py Qt-free semantics.
//
// TrashImpactSummary aggregates per-asset delete impact (catalog lineage +
// map-side usages); render_markdown() is the pure frozen surface — the
// fail-closed contract is that a failed computation COUNTS as downstream
// (computation_errors > 0 still forces explicit confirmation).
//
// The two domain lookups are seams:
//   * IDeleteImpact — catalog ImpactService.delete_impact per asset
//   * IMapUsageSource — mapping_workspace.source_usage.usages_of_asset
// Neither is reimplemented here: collect_trash_impact only orchestrates the
// bounded aggregation Python performs (the [:20]/[:30]/[:5] caps verbatim).

#include "pwb/catalog/impact.hpp"

#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace pwb::ui_review {

// catalog.delete_impact seam — one call per asset id. Throwing std::
// exception mirrors Python's bare ``except Exception`` (counted, never
// swallowed silently: it lands in computation_errors).
class IDeleteImpact {
public:
    virtual ~IDeleteImpact() = default;
    virtual catalog::DeleteImpact
    delete_impact(const std::string& asset_id) = 0;
};

// mapping_workspace.source_usage.usages_of_asset seam — returns
// (kind, label) pairs (kind "layer" vs everything else drives the
// two-block markdown split).
class IMapUsageSource {
public:
    virtual ~IMapUsageSource() = default;
    virtual std::vector<std::pair<std::string, std::string>>
    usages_of_asset(const std::string& asset_id) = 0;
};

// TrashImpactSummary (Python dataclass parity). descendant_names stays
// honest: Python reads ``getattr(item, "asset_name", "")`` off StaleItem —
// the catalog StaleItem has no asset_name member, so the guard filters
// EVERY item and the list is always empty. The C++ DeleteImpact has no
// name field either; the field is retained (always empty) so
// render_markdown() preserves the same output (no name bullets).
struct TrashImpactSummary {
    int descendant_count = 0;
    std::vector<std::string> descendant_names;  // always empty — see above
    std::vector<std::string> runs_consuming;
    std::vector<std::pair<std::string, std::string>> linked_entities;
    int broken_edges = 0;
    std::vector<std::string> cascade_advice;
    std::vector<std::pair<std::string, std::string>> map_usages;
    // Fail-closed evidence: >0 means callers must still confirm.
    int computation_errors = 0;

    bool has_downstream() const;
    std::string render_markdown() const;
};

// collect_trash_impact parity: per asset — one delete_impact hop (bounded
// fields appended with Python's [:20]/[:5] caps) then, only when
// map_usages is non-null, one usages_of_asset hop ([:30] cap). A throw
// from EITHER hop increments computation_errors and skips the rest of
// that asset (workspace hop failure skips to the next asset — the map
// usage hop is inside the same try in Python only per-workspace-hop; see
// the Python source: impact failure ``continue``s the whole asset, usage
// failure ``continue``s to the next asset as well).
TrashImpactSummary collect_trash_impact(
    IDeleteImpact& impact, IMapUsageSource* map_usages,
    const std::vector<std::string>& asset_ids);

}  // namespace pwb::ui_review
