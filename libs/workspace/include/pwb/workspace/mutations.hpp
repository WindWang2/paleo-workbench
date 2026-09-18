// Workspace membership write operations (conv-26; the mutation surface
// above the MappingWorkspaceState codec): layer add/remove, pinned-version
// rebind (catalog_version / content_fingerprint), and stale-reference
// repair for bindings whose pinned version no longer exists in the
// catalog. Mutations are in-memory; persistence goes through
// write_mapping_workspace + the project save path.
#pragma once

#include "pwb/workspace/state.hpp"

#include <functional>
#include <string>
#include <vector>

namespace pwb::workspace {

struct MembershipChange {
    bool changed = false;
    bool created = false;
};

// Upsert the membership record for binding.layer_id (creates the record
// when absent). Role stays the lenient fallback vocabulary; created_at /
// bound_at are refreshed on change.
MembershipChange set_layer_binding(MappingWorkspaceState& state,
                                   LayerBinding binding);

// Remove the membership record; a no-op change when the layer is absent.
MembershipChange remove_layer_binding(MappingWorkspaceState& state,
                                      const std::string& layer_id);

// Pin a layer onto (asset, version). binding_kind "" keeps the V13 read
// rule (pinned + no explicit kind ⇒ read as catalog_version); an explicit
// "catalog_version" / "content_fingerprint" is stored verbatim.
MembershipChange rebind_to_version(MappingWorkspaceState& state,
                                   const std::string& layer_id,
                                   const std::string& asset_id,
                                   const std::string& version_id,
                                   const std::string& binding_kind = "");

// Stale-reference repair: bindings whose pinned source_version_id no
// longer exists are moved to the asset's live current version (or reset to
// UNKNOWN when the asset is gone). Never silently deletes a membership.
struct StaleRepairReport {
    int inspected = 0;
    int repaired_to_current = 0;
    int reset_to_unknown = 0;
    std::vector<std::string> repaired_layers;
};

// version_exists(version_id) → liveness of the pinned version;
// current_version_of(asset_id) → the asset's current version ("" = none).
StaleRepairReport repair_stale_bindings(
    MappingWorkspaceState& state,
    const std::function<bool(const std::string&)>& version_exists,
    const std::function<std::string(const std::string&)>& current_version_of);

// Serialize the state back into the project tree's mapping_workspace
// section (round-trips through the codec's own to_json).
void write_mapping_workspace(domain::Json& document_root,
                             const MappingWorkspaceState& state);

}  // namespace pwb::workspace
