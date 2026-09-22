#pragma once

// Port of paleo_workbench/mapping_workspace/dependencies.py —
// MappingDependencyService.evaluate: cross-stage artifact freshness over
// the catalog's version/run/lineage authority (V5 §32 — pure domain
// query, never a second dependency DB, never a catalog write).
//
// Artifact keys (mapping_workspace/artifact_keys.py — the ONLY
// construction site in Python, mirrored here):
//   phase1_draft:<layer_id>   — Phase-1 interpretation draft pins the
//                               RAW initial-facies version (membership
//                               source_version_id);
//   factor:<task_id>          — factor task pins its producing DataRun's
//                               input versions (grid_artifact_version_id
//                               → run → inputs);
//   integrated:<layer_id>     — integrated interpretation pins the
//                               Compilation Input Set (evidence_view);
//   mapproduct:<record_id>    — product pins its assembly run's inputs.
//
// Verdicts (V5 §31/§32): a pinned input version missing → MISSING_INPUT;
// the input's asset has a newer version (pinned ≠ current) → STALE; the
// artifact's own output is no longer the asset tip → SUPERSEDED;
// fingerprint-class inputs (constraint content) mismatching current →
// STALE; else CURRENT; unverifiable → UNKNOWN. STALE is a marker, never
// an automatic delete/overwrite.
//
// The workspace state is consumed as the mapping_workspace Json section
// (MappingWorkspaceState::to_json() shape — memberships dict +
// compilation_input_set), matching evidence_view's seam.
//
// Qt-free, Python-free.

#include <pwb/domain/json.hpp>
#include <pwb/workflow_runtime/catalog_seam.hpp>

#include <string>
#include <utility>
#include <vector>

namespace pwb::workflow_interpretation {

using pwb::domain::Json;

// FreshnessStatus value strings (dependencies.py enum values verbatim).
namespace freshness_status {
inline constexpr const char* kCurrent = "current";
inline constexpr const char* kStale = "stale";
inline constexpr const char* kMissingInput = "missing_input";
inline constexpr const char* kSuperseded = "superseded";
inline constexpr const char* kUnknown = "unknown";
}  // namespace freshness_status

// Artifact types (ArtifactFreshness.artifact_type verbatim).
namespace artifact_type {
inline constexpr const char* kPhase1Draft = "phase1_draft";
inline constexpr const char* kFactor = "factor";
inline constexpr const char* kIntegrated = "integrated";
inline constexpr const char* kMapProduct = "mapproduct";
}  // namespace artifact_type

// MappingStage value strings the artifacts belong to.
namespace freshness_stage {
inline constexpr const char* kFaciesCalibration = "facies_calibration";
inline constexpr const char* kConstraintFactor = "constraint_factor";
inline constexpr const char* kIntegratedCompilation =
    "integrated_compilation";
}  // namespace freshness_stage

// artifact_keys.py — single construction site.
std::string factor_key(const std::string& task_id);
std::string phase1_draft_key(const std::string& layer_id);
std::string integrated_key(const std::string& layer_id);
std::string mapproduct_key(const std::string& record_id);

// _STATUS_LABELS parity (Chinese display labels).
std::string freshness_status_label(const std::string& status);

struct ArtifactFreshness {
    std::string artifact_key;
    std::string type;    // artifact_type::* values
    std::string stage;   // freshness_stage::* values
    std::string status = freshness_status::kUnknown;
    std::string detail;
    // (ref_key, pinned value) pairs — selector ref → pinned version/ref.
    std::vector<std::pair<std::string, std::string>> pinned_inputs;
    std::vector<std::string> upstream_culprits;

    // Python is_problem: status in {stale, missing_input, superseded}.
    [[nodiscard]] bool is_problem() const;
    [[nodiscard]] std::string status_label() const {
        return freshness_status_label(status);
    }
    // Wire shape consumed by the cartographic QA stale_input rule and
    // stage surfaces: artifact_key/type/stage/status/status_label/detail/
    // is_problem/pinned_inputs/upstream_culprits.
    [[nodiscard]] Json to_dict() const;
};

// MappingDependencyService.evaluate: one freshness pass over the whole
// workspace. `document` is the project root Json; `workspace_state` is
// the mapping_workspace section Json (nullptr == Python
// workspace_state=None — draft/integrated entries are skipped, factors
// and products still evaluate); `catalog` may be nullptr (Python
// catalog=None — verifiable checks degrade to UNKNOWN, never fabricated
// CURRENT/MISSING).
[[nodiscard]] std::vector<ArtifactFreshness> evaluate_workspace_freshness(
    const Json& document, const Json* workspace_state,
    workflow_runtime::CatalogRepository* catalog);

// The StaleSummary wire shape: {"artifacts": [entry.to_dict(), ...]}.
// Callers needing only problems filter on is_problem (Python's
// stale_entries property).
[[nodiscard]] Json stale_summary_json(
    const std::vector<ArtifactFreshness>& entries);

// StaleSummary.stale_entries parity.
[[nodiscard]] std::vector<ArtifactFreshness> stale_entries(
    const std::vector<ArtifactFreshness>& entries);

// StaleSummary.headline parity ("N 项输入成果已过期", "" when clean).
[[nodiscard]] std::string stale_headline(
    const std::vector<ArtifactFreshness>& entries);

// _looks_like_version_id parity — distinguish version ids from content
// fingerprints ("ver_"/"dver_" prefix, or ≥32 chars containing '-' and
// not a "sha:" fingerprint).
[[nodiscard]] bool looks_like_version_id(const std::string& value);

}  // namespace pwb::workflow_interpretation
