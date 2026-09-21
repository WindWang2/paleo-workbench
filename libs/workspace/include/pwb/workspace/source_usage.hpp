// V14 source usage reverse query — version -> mapping usage
// (V13 W-I / W-M). 1:1 port of
// paleo_workbench/mapping_workspace/source_usage.py.
//
// Answers "which map content references this DataVersion?" as a derived
// projection over existing authorities — no new storage:
//
// * MappingWorkspaceState.memberships: layer-level bindings
//   (source_version_id; source_asset_id since V13);
// * ProjectDocument.factor_map_tasks: factor task product grids
//   (grid_artifact_version_id) — factor sublayers bind via their task;
// * ProjectDocument.compilation_input_sets: pinned versions of
//   compilation inputs (pinned_version_id / resolved_asset_id);
// * ProjectDocument.map_products: product output versions and run inputs;
// * optional catalog: runs consuming the version (bounded).
//
// The forward direction (layer -> version) is answered by the membership
// record itself; this module closes the reverse loop. The project
// sections arrive as the verbatim Json of the ProjectDocument root (the
// Python side duck-types the same fields); catalog access is a seam so
// workspace keeps no catalog link dependency — callers bind it to the
// catalog service facade (never a private-SQLite shortcut).
#pragma once

#include "pwb/workspace/state.hpp"

#include <map>
#include <optional>
#include <string>
#include <vector>

namespace pwb::workspace {

// Hard cap for run-level usage entries (run inputs can be very wide,
// e.g. 53-well predictions).
inline constexpr std::size_t kMaxRunUsageEntries = 100;

// Usage kind vocabulary (stable strings consumed by UI/agent directly).
inline constexpr std::string_view kUsageLayer = "layer";
inline constexpr std::string_view kUsageFactorGrid = "factor_grid";
inline constexpr std::string_view kUsageCompilationInput =
    "compilation_input";
inline constexpr std::string_view kUsageMapProductOutput =
    "map_product_output";
inline constexpr std::string_view kUsageMapProductInput =
    "map_product_input";
inline constexpr std::string_view kUsageRunInput = "run_input";

// One "who uses this version" record (pure derivation, never persisted).
struct VersionUsage {
    std::string kind;
    std::string ref_id;
    std::string label;
    // Matched version id (asset-level queries mark which version was
    // referenced).
    std::string version_id;
    std::string stage;
    std::string role;
    std::string status;
};

struct VersionUsageReport {
    std::vector<VersionUsage> usages;
    bool truncated = false;
};

// Catalog seam (Python's duck-typed optional catalog). Implementations
// must be total: errors degrade to empty/false, never throw (Python
// caught every exception around catalog calls).
struct RunSummary {
    std::string id;
    std::string operation;
    std::string status;
};

class UsageCatalog {
public:
    virtual ~UsageCatalog() = default;
    // Input version ids of a run; nullopt = run unknown.
    virtual std::optional<std::vector<std::string>> run_input_version_ids(
        const std::string& run_id) const = 0;
    // Runs consuming the version (unbounded; caller caps).
    virtual std::vector<RunSummary> runs_consuming(
        const std::string& version_id) const = 0;
    // All version ids of an asset.
    virtual std::vector<std::string> versions_of_asset(
        const std::string& asset_id) const = 0;
};

// All map-side references of a DataVersion (bounded; truncated flag is
// honest). Null pointers degrade to "section absent" — the query never
// fabricates what it was not given.
VersionUsageReport usages_of_version(
    const std::string& version_id,
    const MappingWorkspaceState* workspace,
    const domain::Json* project_root,
    const UsageCatalog* catalog = nullptr,
    bool include_runs = true);

// All map-side references of a DataAsset (aggregated over its versions +
// asset-level direct bindings). With a catalog: per-version reverse
// lookup. Without: asset-level bindings only (memberships'
// source_asset_id, input-set resolved_asset_id) — honest degradation,
// never a fabricated version-level conclusion.
VersionUsageReport usages_of_asset(const std::string& asset_id,
                                   const MappingWorkspaceState* workspace,
                                   const domain::Json* project_root,
                                   const UsageCatalog* catalog = nullptr);

// Per-kind counts (status-bar / inspector summary).
std::map<std::string, std::size_t> usage_counts(
    const VersionUsageReport& report);

}  // namespace pwb::workspace
