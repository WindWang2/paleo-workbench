#include "pwb/workspace/state.hpp"

#include <algorithm>

namespace pwb::workspace {

using pwb::domain::Diagnostic;
using pwb::domain::Json;

namespace {

bool stage_known(std::string_view value) {
    for (auto stage : kStages) {
        if (stage == value) return true;
    }
    return false;
}

bool maturity_known(std::string_view value) {
    for (auto maturity : kMaturities) {
        if (maturity == value) return true;
    }
    return false;
}

std::string get_string(const Json& object, const char* key) {
    const auto it = object.find(key);
    if (it == object.end() || it->is_null()) return "";
    if (it->is_string()) return it->get<std::string>();
    if (it->is_boolean()) return it->get<bool>() ? "true" : "false";
    if (it->is_number_integer()) return std::to_string(it->get<long long>());
    return "";
}

// Python `str(data.get(...) or "")` semantics: falsy → "".
LayerBinding binding_from_dict(const Json& data) {
    LayerBinding binding;
    binding.layer_id = get_string(data, "layer_id");
    binding.role = get_string(data, "role");
    if (binding.role.empty()) binding.role = "legacy_unclassified";
    binding.factor_task_id = get_string(data, "factor_task_id");
    binding.constraint_kind = get_string(data, "constraint_kind");
    binding.created_stage = get_string(data, "created_stage");
    binding.source_version_id = get_string(data, "source_version_id");
    binding.created_at = get_string(data, "created_at");
    binding.source_asset_id = get_string(data, "source_asset_id");
    const std::string kind = get_string(data, "binding_kind");
    // Stored value is kept verbatim ("" when absent/unknown). The
    // "old record with a pinned version reads as catalog_version" rule is
    // INTERPRETATION, not storage — see effective_binding_kind(); writing a
    // fabricated kind back would diverge from Python round-trip.
    if (kind == "catalog_version" || kind == "content_fingerprint") {
        binding.binding_kind = kind;
    } else {
        binding.binding_kind = "";
    }
    binding.bound_at = get_string(data, "bound_at");
    return binding;
}

Json binding_to_dict(const LayerBinding& binding) {
    Json out = Json::object();
    out["layer_id"] = binding.layer_id;
    out["role"] = binding.role;
    out["factor_task_id"] = binding.factor_task_id;
    out["constraint_kind"] = binding.constraint_kind;
    out["created_stage"] = binding.created_stage;
    out["source_version_id"] = binding.source_version_id;
    out["created_at"] = binding.created_at;
    out["source_asset_id"] = binding.source_asset_id;
    out["binding_kind"] = binding.binding_kind;
    out["bound_at"] = binding.bound_at;
    return out;
}

std::map<std::string, std::optional<bool>> read_bool_tristate_map(
    const Json& data, const char* key) {
    std::map<std::string, std::optional<bool>> out;
    const auto it = data.find(key);
    if (it == data.end() || !it->is_object()) return out;
    for (auto member = it->begin(); member != it->end(); ++member) {
        if (member->is_null()) {
            out[member.key()] = std::nullopt;
        } else if (member->is_boolean()) {
            out[member.key()] = member->get<bool>();
        }
    }
    return out;
}

std::optional<std::string> get_optional_string(const Json& data,
                                               const char* key) {
    const auto it = data.find(key);
    if (it == data.end() || it->is_null() || !it->is_string()) return std::nullopt;
    const std::string value = it->get<std::string>();
    return value.empty() ? std::nullopt : std::optional<std::string>(value);
}

StageViewState stage_view_from_dict(const Json& data,
                                    domain::DiagnosticList& diagnostics) {
    StageViewState state;
    state.stage = get_string(data, "stage");
    if (!stage_known(state.stage)) {
        diagnostics.push_back(Diagnostic::warning(
            "workspace_unknown_stage",
            "unknown stage '" + state.stage + "' — fell back to "
            "facies_calibration"));
        state.stage = "facies_calibration";
    }
    state.group_visibility = read_bool_tristate_map(data, "group_visibility");
    state.group_locked = read_bool_tristate_map(data, "group_locked");
    state.layer_visibility = read_bool_tristate_map(data, "layer_visibility");
    {
        const auto it = data.find("layer_opacity");
        if (it != data.end() && it->is_object()) {
            for (auto member = it->begin(); member != it->end(); ++member) {
                if (member->is_number()) {
                    state.layer_opacity[member.key()] =
                        member->get<double>();
                } else if (member->is_null()) {
                    state.layer_opacity[member.key()] = std::nullopt;
                }
            }
        }
    }
    state.active_layer_id = get_optional_string(data, "active_layer_id");
    state.active_tool = get_optional_string(data, "active_tool");
    const auto customized = data.find("customized");
    state.customized =
        customized != data.end() && customized->is_boolean()
            ? customized->get<bool>()
            : false;
    return state;
}

Json stage_view_to_dict(const StageViewState& state) {
    Json out = Json::object();
    out["stage"] = state.stage;
    Json visibility = Json::object();
    for (const auto& [key, value] : state.group_visibility) {
        visibility[key] = value.has_value() ? Json(*value) : Json(nullptr);
    }
    out["group_visibility"] = std::move(visibility);
    Json locked = Json::object();
    for (const auto& [key, value] : state.group_locked) {
        locked[key] = value.has_value() ? Json(*value) : Json(nullptr);
    }
    out["group_locked"] = std::move(locked);
    Json layers = Json::object();
    for (const auto& [key, value] : state.layer_visibility) {
        layers[key] = value.has_value() ? Json(*value) : Json(nullptr);
    }
    out["layer_visibility"] = std::move(layers);
    Json opacity = Json::object();
    for (const auto& [key, value] : state.layer_opacity) {
        // Python to_dict drops null entries — the override "not set" state
        // never reaches the file.
        if (value.has_value()) opacity[key] = *value;
    }
    out["layer_opacity"] = std::move(opacity);
    out["active_layer_id"] = state.active_layer_id.has_value()
                                 ? Json(*state.active_layer_id)
                                 : Json(nullptr);
    out["active_tool"] = state.active_tool.has_value()
                             ? Json(*state.active_tool)
                             : Json(nullptr);
    out["customized"] = state.customized;
    return out;
}

}  // namespace

MappingWorkspaceState MappingWorkspaceState::from_json(
    const Json& data, domain::DiagnosticList& diagnostics) {
    MappingWorkspaceState state;
    if (!data.is_object()) return state;

    // Unknown top-level keys ride along (superset of Python §7).
    for (auto it = data.begin(); it != data.end(); ++it) {
        if (it.key() != "schema_version" && it.key() != "current_stage" &&
            it.key() != "stage_states" && it.key() != "memberships" &&
            it.key() != "tree" && it.key() != "qgis_project_file" &&
            it.key() != "artifact_maturity" &&
            it.key() != "compilation_input_set") {
            state.extra[it.key()] = it.value();
        }
    }

    const auto schema = data.find("schema_version");
    if (schema != data.end() && schema->is_number_integer()) {
        state.schema_version = schema->get<int>();
    }
    state.current_stage = get_string(data, "current_stage");
    if (!stage_known(state.current_stage)) {
        state.current_stage = "facies_calibration";
    }
    const auto states = data.find("stage_states");
    if (states != data.end() && states->is_object()) {
        for (auto stage : kStages) {
            const auto raw = states->find(std::string(stage));
            if (raw != states->end() && raw->is_object()) {
                state.stage_states[std::string(stage)] =
                    stage_view_from_dict(*raw, diagnostics);
            }
        }
    }
    // Python __post_init__ seeds every STAGE_ORDER stage with defaults —
    // from_dict therefore ALWAYS returns three stage_states; mirror that.
    for (auto stage : kStages) {
        state.stage_states.try_emplace(std::string(stage),
                                       StageViewState{std::string(stage)});
    }
    const auto memberships = data.find("memberships");
    if (memberships != data.end() && memberships->is_object()) {
        for (auto member = memberships->begin(); member != memberships->end();
             ++member) {
            if (!member->is_object()) continue;
            LayerBinding binding = binding_from_dict(*member);
            binding.layer_id = member.key();  // identity from the map key
            state.memberships[member.key()] = std::move(binding);
        }
    }
    const auto tree = data.find("tree");
    if (tree != data.end() && tree->is_object()) {
        state.tree = *tree;
    }
    state.qgis_project_file = get_string(data, "qgis_project_file");
    const auto maturity = data.find("artifact_maturity");
    if (maturity != data.end() && maturity->is_object()) {
        for (auto member = maturity->begin(); member != maturity->end();
             ++member) {
            if (member->is_string() && maturity_known(member->get<std::string>())) {
                state.artifact_maturity[member.key()] =
                    member->get<std::string>();
            } else if (member->is_string()) {
                diagnostics.push_back(Diagnostic::warning(
                    "workspace_unknown_maturity",
                    "artifact_maturity['" + member.key() + "'] = '" +
                        member->get<std::string>() +
                        "' outside vocabulary — dropped (Python parity)"));
            }
        }
    }
    const auto input_set = data.find("compilation_input_set");
    if (input_set != data.end() && input_set->is_object()) {
        for (auto member = input_set->begin(); member != input_set->end();
             ++member) {
            if (member->is_string()) {
                state.compilation_input_set[member.key()] =
                    member->get<std::string>();
            }
        }
    }
    return state;
}

Json MappingWorkspaceState::to_json() const {
    Json out = Json::object();
    out["schema_version"] = schema_version;
    out["current_stage"] = current_stage;
    Json states = Json::object();
    // STAGE_ORDER key order (Python dict iteration inserts in stage order).
    for (auto stage : kStages) {
        const auto it = stage_states.find(std::string(stage));
        if (it != stage_states.end()) {
            states[std::string(stage)] = stage_view_to_dict(it->second);
        }
    }
    out["stage_states"] = std::move(states);
    Json members_json = Json::object();
    for (const auto& [layer_id, binding] : memberships) {
        members_json[layer_id] = binding_to_dict(binding);
    }
    out["memberships"] = std::move(members_json);
    // QGIS-native handoff: once the sibling .qgs file owns the GIS tree,
    // this section stops persisting a second copy of the structure — the
    // tree is written empty (the in-memory desired tree keeps driving the
    // session; a reopen restores structure from the QGIS project and
    // re-observes it into this state).
    out["tree"] = qgis_project_file.empty() ? tree : Json::object();
    out["qgis_project_file"] = qgis_project_file;
    Json maturity = Json::object();
    for (const auto& [key, value] : artifact_maturity) {
        maturity[key] = value;
    }
    out["artifact_maturity"] = std::move(maturity);
    Json input_set = Json::object();
    for (const auto& [key, value] : compilation_input_set) {
        input_set[key] = value;
    }
    out["compilation_input_set"] = std::move(input_set);
    for (auto it = extra.begin(); it != extra.end(); ++it) {
        out[it.key()] = it.value();
    }
    return out;
}

std::vector<LayerBinding> MappingWorkspaceState::catalog_bindings() const {
    std::vector<LayerBinding> out;
    for (const auto& [layer_id, binding] : memberships) {
        if (effective_binding_kind(binding) == "catalog_version") {
            out.push_back(binding);
        }
    }
    return out;
}

void ensure_mapping_workspace(domain::Json& document_root) {
    auto it = document_root.find("mapping_workspace");
    if (it == document_root.end() || !it->is_object()) {
        document_root["mapping_workspace"] =
            MappingWorkspaceState{}.to_json();
    }
}

}  // namespace pwb::workspace
