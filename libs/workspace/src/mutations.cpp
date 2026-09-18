// Workspace membership mutations (conv-26) — see mutations.hpp.
#include "pwb/workspace/mutations.hpp"

#include "pwb/domain/diagnostics.hpp"

#include <utility>

namespace pwb::workspace {

MembershipChange set_layer_binding(MappingWorkspaceState& state,
                                   LayerBinding binding) {
    MembershipChange change;
    auto it = state.memberships.find(binding.layer_id);
    if (it == state.memberships.end()) {
        // Honest timestamps: an unknown creation time stays "" (Python
        // keeps `existing.created_at or ""`); only bound_at records when
        // THIS pin happened.
        if (!binding.bound_at.empty() && !binding.source_version_id.empty()) {
            // caller-supplied bound_at kept verbatim
        } else if (!binding.source_version_id.empty()) {
            binding.bound_at = domain::now_iso8601();
        }
        const std::string layer_id = binding.layer_id;
        state.memberships[layer_id] = std::move(binding);
        change.changed = true;
        change.created = true;
        return change;
    }
    if (it->second.role != binding.role ||
        it->second.factor_task_id != binding.factor_task_id ||
        it->second.constraint_kind != binding.constraint_kind ||
        it->second.created_stage != binding.created_stage ||
        it->second.source_version_id != binding.source_version_id ||
        it->second.source_asset_id != binding.source_asset_id ||
        it->second.binding_kind != binding.binding_kind) {
        binding.created_at = it->second.created_at;  // verbatim (may be "")
        binding.bound_at = domain::now_iso8601();
        it->second = std::move(binding);
        change.changed = true;
    }
    return change;
}

MembershipChange remove_layer_binding(MappingWorkspaceState& state,
                                      const std::string& layer_id) {
    MembershipChange change;
    change.changed = state.memberships.erase(layer_id) > 0;
    if (!change.changed) return change;
    // Python drop_membership also purges the per-stage view-state
    // overrides so orphaned visibility/opacity entries cannot accumulate.
    for (auto& [stage, view] : state.stage_states) {
        (void)stage;
        view.layer_visibility.erase(layer_id);
        view.layer_opacity.erase(layer_id);
        if (view.active_layer_id == layer_id) view.active_layer_id.reset();
    }
    return change;
}

MembershipChange rebind_to_version(MappingWorkspaceState& state,
                                   const std::string& layer_id,
                                   const std::string& asset_id,
                                   const std::string& version_id,
                                   const std::string& binding_kind) {
    LayerBinding binding;
    auto it = state.memberships.find(layer_id);
    if (it != state.memberships.end()) {
        binding = it->second;
    }
    binding.layer_id = layer_id;
    binding.source_asset_id = asset_id;
    binding.source_version_id = version_id;
    // Write-time coercion (Python register_layer parity): a pinned record
    // without an explicit kind is STORED as catalog_version so readers on
    // either side of the language line see the same kind — the V13
    // read-side rule remains as the legacy-document compensation.
    if (binding_kind.empty()) {
        binding.binding_kind =
            version_id.empty() ? std::string() : "catalog_version";
    } else {
        binding.binding_kind = binding_kind;
    }
    return set_layer_binding(state, std::move(binding));
}

StaleRepairReport repair_stale_bindings(
    MappingWorkspaceState& state,
    const std::function<bool(const std::string&)>& version_exists,
    const std::function<std::string(const std::string&)>& current_version_of) {
    StaleRepairReport report;
    for (auto& [layer_id, binding] : state.memberships) {
        ++report.inspected;
        if (binding.source_version_id.empty()) continue;
        if (version_exists && version_exists(binding.source_version_id)) {
            continue;
        }
        const std::string current =
            current_version_of ? current_version_of(binding.source_asset_id)
                               : std::string();
        if (!current.empty()) {
            binding.source_version_id = current;
            binding.binding_kind = "catalog_version";
            binding.bound_at = domain::now_iso8601();
            ++report.repaired_to_current;
        } else {
            binding.source_version_id = "";
            binding.source_asset_id = "";
            binding.binding_kind = "";
            binding.bound_at = domain::now_iso8601();
            ++report.reset_to_unknown;
        }
        report.repaired_layers.push_back(layer_id);
    }
    return report;
}

void write_mapping_workspace(domain::Json& document_root,
                             const MappingWorkspaceState& state) {
    document_root["mapping_workspace"] = state.to_json();
}

}  // namespace pwb::workspace
