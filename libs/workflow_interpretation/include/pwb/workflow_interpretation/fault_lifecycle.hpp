#pragma once
// Fault interpretation lifecycle (workflow/fault_lifecycle.py port,
// Stage 12): draft → immutable DERIVED artifact → reopen.
//
// Scientific authority is map-plane polylines (project CRS), not screen
// coordinates. ConstraintLine role=break remains a separate factor
// constraint path — draft_from_constraint_layers only LIFTS a copy.
//
// Seam mapping (Python duck-typed collaborators → C++):
//   ProjectDocument                → Json tree (fault_interpretations
//                                    array mutated in place)
//   catalog (get_catalog())        → workflow_runtime::CatalogRepository*
//                                    (null == Python None → DERIVED
//                                    registration honestly skipped, the
//                                    artifact + ref still land)
//   correlation_artifact module    → the write/read/fingerprint helpers
//                                    below (canonical JSON SHA-256 via
//                                    factor_host::stable_sha256 — byte
//                                    parity with the Python chain)
//   artifact_dir_for(project)/faults → supplied by the caller (the app
//                                    layer owns the project paths module)
//
// Failure compensation (H7, same contract as save_correlation_draft): a
// catalog registration failure deletes the just-written local artifact —
// no ghost files — and re-raises.
// Qt-free, Python-free.

#include <pwb/domain/json.hpp>
#include <pwb/workflow_runtime/catalog_seam.hpp>

#include <filesystem>
#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace pwb::workflow_interpretation {

using domain::Json;

// FaultTrace (stratigraphy_models.py): map-plane polyline + the optional
// seismic side (section picks ride verbatim as Json).
struct FaultTrace {
    std::string id;                  // "ftrace_<12hex>"
    std::string name;
    std::vector<std::pair<double, double>> polyline;
    std::string role = "fault";      // break | fault | other
    std::string vertical_domain;     // "" = map-plane only; "time" = TWT
    std::string notes;
    Json section_picks = Json::array();
    std::optional<std::string> map_fault_id;

    [[nodiscard]] Json to_dict() const;
    [[nodiscard]] static FaultTrace from_dict(const Json& data);
};

// The scientific payload of one interpretation (what gets fingerprinted).
struct FaultInterpretationPayload {
    int schema_version = 1;
    std::string interpretation_id;
    std::string name;
    std::vector<FaultTrace> traces;
    std::vector<std::string> source_version_ids;
    std::optional<std::string> parent_version_id;
    std::string crs;
    std::string notes;

    // scientific_dict parity: traces sorted by (name, id).
    [[nodiscard]] Json scientific_dict() const;
};

// The editing state (dirty tracking + last saved fingerprint).
struct FaultInterpretationDraft {
    std::string interpretation_id;   // "fault_<12hex>"
    std::string name = "断层解释";
    FaultInterpretationPayload payload;
    int generation = 0;
    bool dirty = true;
    std::string last_saved_fingerprint;
    Json display = Json::object();

    void bump() {
        ++generation;
        dirty = true;
    }
};

// project.fault_interpretations[] entry (models.py FaultInterpretationRef).
struct FaultInterpretationRef {
    std::string id;
    std::string name;
    std::string current_version_id;
    std::string artifact_path;       // relative to the project dir when possible
    std::optional<std::string> parent_version_id;
    std::string status = "clean";
    std::vector<std::string> source_version_ids;
    std::string scientific_fingerprint;
    std::string crs;
    Json display = Json::object();

    [[nodiscard]] Json to_dict() const;
    [[nodiscard]] static FaultInterpretationRef from_dict(const Json& data);
};

// _id parity: "fault_<12hex>" / caller prefix.
std::string fault_id(const std::string& prefix = "fault");

FaultInterpretationDraft new_fault_draft(
    const std::string& name = "断层解释",
    const std::vector<FaultTrace>& traces = {},
    const std::vector<std::string>& source_version_ids = {},
    const std::string& crs = "",
    const std::optional<std::string>& interpretation_id = std::nullopt,
    const std::optional<std::string>& parent_version_id = std::nullopt);

// Lift break/fault polylines of one ConstraintLayers group Json into a
// scientific fault draft (copy, never a mutation of the constraint side).
FaultInterpretationDraft draft_from_constraint_layers(
    const Json& layers, const std::string& name = "断层约束",
    const std::string& crs = "");

// Reopen a saved artifact as a clean draft (fingerprint precomputed).
std::optional<FaultInterpretationDraft> open_fault_draft_from_version(
    const std::filesystem::path& artifact_path,
    const std::optional<std::string>& interpretation_id = std::nullopt);

std::string draft_fingerprint(const FaultInterpretationDraft& draft);

// write_fault_artifact / read_fault_artifact parity ({kind, scientific,
// fingerprint, descriptor}; atomic tmp + rename).
std::filesystem::path write_fault_artifact(
    const FaultInterpretationPayload& payload,
    const std::filesystem::path& directory, const std::string& basename,
    const Json& extra_descriptor = Json::object());
std::optional<FaultInterpretationPayload> read_fault_artifact(
    const std::filesystem::path& artifact_path, Json* descriptor_out = nullptr);

// save_fault_draft: fingerprint-noop short-circuit → write artifact →
// register DERIVED + lineage run (fault-interp-v1) → upsert the project
// ref. Returns (ref, outcome) where outcome is "ok" | "noop_unchanged";
// nullopt ref only for the noop-without-existing-ref edge (Python returns
// (existing, ...) — here the caller sees outcome alone). `fault_dir` is
// artifact_dir_for(project_path) / "faults"; `project_dir` anchors the
// ref's relative artifact_path.
std::pair<std::optional<FaultInterpretationRef>, std::string>
save_fault_draft(FaultInterpretationDraft& draft, Json& project_root,
                 const std::filesystem::path& fault_dir,
                 const std::filesystem::path& project_dir,
                 workflow_runtime::CatalogRepository* catalog = nullptr,
                 bool force_new_version = false);

// restore_fault_draft_from_project: reopen the first (or requested)
// interpretation's artifact as a clean draft.
std::optional<FaultInterpretationDraft> restore_fault_draft_from_project(
    const Json& project_root, const std::filesystem::path& project_dir,
    const std::optional<std::string>& interpretation_id = std::nullopt);

std::optional<FaultInterpretationRef> find_fault_ref(
    const Json& project_root, const std::string& interpretation_id);

}  // namespace pwb::workflow_interpretation
