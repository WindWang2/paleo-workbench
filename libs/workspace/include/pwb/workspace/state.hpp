// MappingWorkspaceState codec — the typed projection of
// ProjectDocument.mapping_workspace (mapping_workspace/stage_state.py
// field-level parity, schema_version=1, V13 binding semantics).
#pragma once

#include "pwb/domain/diagnostics.hpp"
#include "pwb/domain/ids.hpp"
#include "pwb/domain/json.hpp"

#include <map>
#include <optional>
#include <string>
#include <vector>

namespace pwb::workspace {

// Stage vocabulary (stages.py STAGE_ORDER — value order matters).
inline constexpr std::string_view kStages[] = {
    "facies_calibration", "constraint_factor", "integrated_compilation"};

// Binding vocabulary (stage_state.py; empty string = UNKNOWN, never faked).
inline constexpr std::string_view kBindingCatalogVersion = "catalog_version";
inline constexpr std::string_view kBindingContentFingerprint =
    "content_fingerprint";

// Maturity ladder (MATURITY_ORDER); items outside the vocabulary are
// DROPPED on load — Python from_dict behavior.
inline constexpr std::string_view kMaturities[] = {"draft", "reviewed",
                                                   "frozen", "published"};

struct LayerBinding {
    std::string layer_id;
    std::string role = "legacy_unclassified";  // lenient fallback
    std::string factor_task_id;
    std::string constraint_kind;  // unknown vocab → "" (Python parity)
    std::string created_stage;
    std::string source_version_id;  // "" = UNKNOWN
    std::string created_at;
    std::string source_asset_id;    // "" = UNKNOWN (V13)
    std::string binding_kind;       // "" | catalog_version | content_fingerprint
    std::string bound_at;
};

struct StageViewState {
    std::string stage = "facies_calibration";
    std::map<std::string, std::optional<bool>> group_visibility;
    std::map<std::string, std::optional<bool>> group_locked;
    std::map<std::string, std::optional<bool>> layer_visibility;
    std::map<std::string, std::optional<double>> layer_opacity;
    std::optional<std::string> active_layer_id;
    std::optional<std::string> active_tool;
    bool customized = false;
};

struct MappingWorkspaceState {
    int schema_version = 1;
    std::string current_stage = "facies_calibration";  // lenient fallback
    std::map<std::string, StageViewState> stage_states;
    std::map<std::string, LayerBinding> memberships;
    domain::Json tree = domain::Json::object();          // verbatim carrier
    std::map<std::string, std::string> artifact_maturity;
    std::map<std::string, std::string> compilation_input_set;
    // Unknown keys at ANY level, preserved verbatim and re-emitted on
    // serialization (superset of Python, schema-map §7).
    domain::Json extra = domain::Json::object();

    // Codec: from/to the ProjectDocument.mapping_workspace dict. from_json
    // applies the Python fallback rules; diagnostics record every fallback.
    static MappingWorkspaceState from_json(
        const domain::Json& data, domain::DiagnosticList& diagnostics);
    domain::Json to_json() const;

    // All bindings pinned to a catalog version (kind == catalog_version).
    std::vector<LayerBinding> catalog_bindings() const;
};

// V13 interpretation rule (12-migration.md): a record with a pinned
// source_version_id and no explicit kind is READ as catalog_version —
// the pre-V13 writer's only meaning. Storage stays verbatim.
inline std::string_view effective_binding_kind(const LayerBinding& binding) {
    if (binding.binding_kind == "catalog_version" ||
        binding.binding_kind == "content_fingerprint") {
        return binding.binding_kind;
    }
    if (binding.source_version_id.empty()) return "";
    return "catalog_version";
}

// Normalizes (or creates) the mapping_workspace section on a project tree.
void ensure_mapping_workspace(domain::Json& document_root);

}  // namespace pwb::workspace
