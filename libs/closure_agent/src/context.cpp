// context.cpp — ActionContext behaviour (context.py port). The session-id
// generator is an injectable seam so runs stay deterministic in tests;
// production installs a random hex generator at startup.
#include <pwb/closure_agent/context.hpp>

#include <pwb/providers/errors.hpp>
#include <pwb/providers/schema.hpp>

#include <cstdint>
#include <filesystem>

namespace pwb::closure_agent {

std::function<std::string()> ActionContext::session_id_generator;

std::set<ActionRisk> default_permissions() {
    return {ActionRisk::Read, ActionRisk::Compute};
}

namespace {

Json opt_string(const std::optional<std::string>& value) {
    return value ? Json(*value) : Json(nullptr);
}

template <typename Array>
Json opt_array(const std::optional<Array>& value) {
    if (!value) return Json(nullptr);
    Json array = Json::array();
    for (const auto& entry : *value) array.push_back(entry);
    return array;
}

}  // namespace

Json SelectionSnapshot::to_dict() const {
    Json dict = Json::object();
    dict["active_well_id"] = opt_string(active_well_id);
    dict["selected_well_ids"] = selected_well_ids;
    dict["seismic_cursor"] = opt_array(seismic_cursor);
    dict["depth_range"] = opt_array(depth_range);
    dict["target_horizon"] = opt_string(target_horizon);
    dict["active_fault_id"] = opt_string(active_fault_id);
    dict["active_interpretation_id"] = opt_string(active_interpretation_id);
    dict["active_layer_id"] = opt_string(active_layer_id);
    dict["selected_layer_id"] = opt_string(selected_layer_id);
    dict["selected_asset_id"] = opt_string(selected_asset_id);
    dict["map_extent"] = opt_array(map_extent);
    dict["map_crs"] = opt_string(map_crs);
    dict["selected_feature_refs"] = selected_feature_refs;
    dict["active_version_id"] = opt_string(active_version_id);
    dict["spatial_cursor"] = opt_array(spatial_cursor);
    dict["depth_cursor"] = opt_array(depth_cursor);
    return dict;
}

ActionContext::ActionContext() {
    session_id = session_id_generator ? session_id_generator() : "session000000";
}

bool ActionContext::has(const std::string& attr) const {
    if (attr == "catalog") return catalog != nullptr;
    if (attr == "project") return project != nullptr;
    if (attr == "active_volume") return active_volume.has_value();
    if (attr == "current_map_id") return current_map_id.has_value();
    if (attr == "active_well_id") return active_well_id.has_value();
    if (attr == "active_survey_id") return active_survey_id.has_value();
    if (attr == "workspace_id") return workspace_id.has_value();
    if (attr == "project_path") return project_path.has_value();
    if (attr == "session_id") return !session_id.empty();
    if (attr == "cancel") return cancel != nullptr;
    if (attr == "progress") return static_cast<bool>(progress);
    return false;  // unknown attrs read as absent (fail-closed)
}

void ActionContext::require(const std::string& attr) const {
    if (!has(attr)) {
        // Python LookupError message (executor maps it to `rejected`).
        throw ActionContextError(
            "action context is missing " + pwb::providers::python_repr(attr) +
            " (open the relevant workspace/survey/map first, or pass it "
            "explicitly)");
    }
}

ActionContext ActionContext::derived() const {
    ActionContext clone;
    clone.session_id = session_id;
    clone.workspace_id = workspace_id;
    clone.project_path = project_path;
    clone.catalog = catalog;
    clone.project = project;
    clone.selection = selection;
    clone.active_survey_id = active_survey_id;
    clone.active_well_id = active_well_id;
    clone.active_volume = active_volume;
    clone.current_map_id = current_map_id;
    clone.permissions = permissions;
    clone.progress = progress;
    clone.cancel = cancel;
    // A host/foreign-token probe must survive derivation, or a derived
    // subtree silently loses cancellation (the workflow adapter relies on
    // this seam).
    clone.cancel_probe = cancel_probe;
    clone.extras = Json::object();
    if (extras.is_object()) {
        for (auto it = extras.begin(); it != extras.end(); ++it) {
            if (it.key() == "admission_lease") continue;  // per-execution slot
            clone.extras[it.key()] = it.value();
        }
    }
    return clone;
}

providers::ProviderContext ActionContext::provider_context() const {
    providers::ProviderContext provider_context;
    provider_context.catalog = catalog;
    if (project_path) {
        const std::filesystem::path path(*project_path);
        provider_context.workspace_root = path.parent_path().string();
    } else {
        provider_context.workspace_root = std::filesystem::current_path().string();
    }
    provider_context.session_id = session_id;
    provider_context.emit_progress = progress;
    provider_context.cancel = cancel;
    if (extras.is_object()) {
        const auto work_dir = extras.find("work_dir");
        if (work_dir != extras.end() && work_dir->is_string()) {
            provider_context.work_dir = work_dir->get<std::string>();
        }
        // The executor parks the raw lease pointer under extras as
        // {"ptr": <intptr>} while an action runs; a nested provider
        // execution inherits it instead of double-admitting (#1146).
        const auto lease = extras.find("admission_lease");
        if (lease != extras.end() && lease->is_object()) {
            const auto ptr = lease->find("ptr");
            if (ptr != lease->end() && ptr->is_number_integer()) {
                provider_context.admission_lease =
                    reinterpret_cast<providers::IAdmissionLease*>(
                        static_cast<std::intptr_t>(ptr->get<long long>()));
            }
        }
    }
    return provider_context;
}

Json ActionContext::snapshot_description() const {
    Json dict = Json::object();
    dict["session_id"] = session_id;
    dict["workspace_id"] = opt_string(workspace_id);
    dict["project_path"] = opt_string(project_path);
    dict["selection"] = selection.to_dict();
    dict["active_survey_id"] = opt_string(active_survey_id);
    dict["active_well_id"] = opt_string(active_well_id);
    dict["active_volume"] =
        active_volume ? Json(active_volume->payload) : Json(nullptr);
    dict["current_map_id"] = opt_string(current_map_id);
    Json run_id = Json(nullptr);
    if (extras.is_object()) {
        const auto entry = extras.find("workflow_run_id");
        if (entry != extras.end()) run_id = *entry;
    }
    dict["current_workflow_run_id"] = run_id;
    return dict;
}

}  // namespace pwb::closure_agent
