#pragma once

// C++ port of paleo_workbench/workflow/constraint_versions.py (CONV-26) —
// constraint lifecycle: authoritative document content → catalog DERIVED
// DataVersions. One asset per constraint group, one immutable version per
// commit, one run per commit with provenance; the project document stays
// the live editing surface. Content-unchanged commits are no-ops; version
// identity is the content hash (canonical sha256, same rounding as the
// sync-back fingerprint); honest UNKNOWN when a pin has no version binding.
//
// This is the RUNTIME service, not a parser: commit writes through the
// CatalogRepository seam (register_run → register_result_asset /
// register_version → update_run_status, run poisoned "failed" on error),
// pins resolve lazily by content hash, staleness adjudicates
// current/stale_content/stale_version/unknown/unpinned/missing per group.
//
// Document seam: constraint groups / factor tasks are Json views of the
// project document:
//   group  = {"id", "name", "target_horizon", "crs", "lines": [line…]}
//   line   = {"id", "name", "role", "active", "target_horizon",
//             "coordinates": [[x, y], …],
//             "azimuth_deg"?, "semi_major"?, "semi_minor"?, "properties"?}
//   task   = {"target_horizon", "parameters": {"constraint_pins": [pin…]}}
//   pin    = {"group_id", "group_name", "content_hash", "line_count",
//             "version_id"?: string}
//
// Divergence (documented): Python transports the payload through a temp
// file path; the C++ seam carries the payload text (payload identity is
// its bytes). compare_constraint_versions loads payloads through the
// repository, not the filesystem.

#include <pwb/domain/json.hpp>
#include <pwb/workflow_runtime/catalog_seam.hpp>

#include <optional>
#include <string>
#include <vector>

namespace pwb::workflow_runtime {

using pwb::domain::Json;

inline constexpr const char* CONSTRAINT_ASSET_TYPE = "constraints";
inline constexpr const char* CONSTRAINT_COMMIT_OPERATION = "constraint_commit";

// Python ValueError — payload-unreachable / malformed-ref raise parity.
struct ConstraintValueError : std::invalid_argument {
    using std::invalid_argument::invalid_argument;
    const char* python_class() const { return "ValueError"; }
};

struct ConstraintCommitReport {
    std::string group_id;
    std::string group_name;
    bool committed = false;  // a NEW version was created
    std::string reason;      // "changed" | "unchanged" | "no_content"
    std::optional<std::string> asset_id;
    std::optional<std::string> version_id;  // new version or unchanged match
    std::optional<std::string> previous_version_id;
    std::optional<std::string> run_id;
    std::optional<std::string> content_hash;
    int line_count = 0;

    Json to_dict() const;
};

// Content hash over the group's GEOMETRIC content (active digitized lines).
// ID-free and order-free: identical content → identical hash regardless of
// line ordering or object identity. Lines without coordinates never count.
// Returns {hash, content_line_count}.
std::pair<std::string, int> constraint_group_content_hash(const Json& group);

// Commit one group's authoritative content as a DERIVED version.
// Content-unchanged commits return the matching version without creating
// anything. First commit creates the group asset atomically; later commits
// append immutable versions to that one asset.
[[nodiscard]] ConstraintCommitReport commit_constraint_group(
    CatalogRepository& repository, const Json& group,
    const std::string& actor = "", const std::string& notes = "");

// Commit every group of {"constraint_layers": [group, …]}.
std::vector<ConstraintCommitReport> commit_all_constraints(
    CatalogRepository& repository, const Json& project,
    const std::string& actor = "", const std::string& notes = "");

// Latest committed version for a group (nullopt = never committed).
std::optional<VersionRecord> current_constraint_version(
    CatalogRepository& repository, const std::string& group_id);

// Pin the constraint state a factor task is computed against (interpolation
// time). Groups matching the task's target horizon (or project-wide) pin
// their current content hash + latest matching committed version id — the
// version binding may be null (content known, version absent → UNKNOWN).
Json constraint_pins_for_task(const Json& task, const Json& project,
                              CatalogRepository* repository = nullptr);

// Recover the pins recorded on a task (empty array = none recorded).
std::vector<Json> pinned_constraint_pins(const Json& task);

// Per-group freshness of a task's pinned constraints:
//   {"state": <aggregate>, "groups": [{"group_id", "state", "detail",
//     "pinned_version_id"?, "line_count"?}]}
// Per-group states: current | stale_content | stale_version | unknown |
// unpinned | missing. Aggregate = worst by rank; never fabricates.
Json constraint_pins_staleness(const Json& task, const Json& project,
                               CatalogRepository* repository = nullptr);

// Line-level diff between two committed constraint versions (lines matched
// by line_id; per-line change attribution over the fixed key set).
Json compare_constraint_versions(CatalogRepository& repository,
                                 const std::string& version_a,
                                 const std::string& version_b);

// Resolve a compilation-input constraint ref to its freshness verdict:
//   "constraints:current"                 — live document vs latest commit
//   "constraints:<group_id>:<version_id>" — pinned commit vs latest commit
// Returns {"status", "detail"} with statuses current | stale | superseded |
// unknown (plain strings — callers map to their own vocabulary).
Json resolve_constraint_ref(const Json& project,
                            CatalogRepository* repository,
                            const std::string& ref);

}  // namespace pwb::workflow_runtime
