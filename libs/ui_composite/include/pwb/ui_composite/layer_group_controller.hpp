// Layer group/membership policy — Qt-free domain half of the layer
// control plane.
//
// AUTHORITY MODEL (QGIS-native convergence, successor of the V14
// reconcile plane): the real QgsLayerTree of the session QgsProject is
// the single runtime authority for structure/order/visibility. This
// controller owns NO tree state — no desired tree, no order keys, no
// placements cache, no reconcile loop. What remains is pure policy over
// the domain workspace state:
//   * membership lifecycle (classification, ghost cleanup, registration);
//   * per-stage view-state policy (effective group visibility = stage
//     profile defaults + user overlay; event recorders);
//   * role routing vocabulary (home groups, placement legality).
// Execution against the real QGIS tree lives in
// pwb::qgis::LayerTreeComposer (libs/qgis); the host wires the two.
#pragma once

#include "pwb/ui_composite/layer_groups.hpp"
#include "pwb/workspace/state.hpp"

#include <map>
#include <optional>
#include <string>
#include <vector>

namespace pwb::ui_composite {

// Composition snapshot input (the fields routing needs from the host's
// layer facts; Python duck-types .id / .metadata / .template).
struct LayerSnapshotInput {
    std::string id;
    std::string template_key;  // metadata["template"] or UserVectorLayer.template
    std::string geometry_type;  // snapshot geometry type ("facies_polygon" ...)
    std::map<std::string, std::string> metadata;
};

class LayerGroupController {
public:
    // The state reference is the single workspace state authority — the
    // controller never copies it.
    explicit LayerGroupController(pwb::workspace::MappingWorkspaceState& state)
        : state_(state) {}

    // -- membership & migration ---------------------------------------------
    // Conservative classification for layers without a membership (legacy
    // migration / new layers). Returns the added layer ids. V11 D13-ws:
    // memberships of layers gone from the composition are cleaned here
    // (only with a non-empty composition — an empty one means "loading",
    // never bulk-delete). Descriptor-only roles (factor grid/uncertainty,
    // non-composite analysis aids) are exempt from the ghost cleanup.
    //
    // full_composition: the snapshots cover EVERY layer of the workspace
    // (Python's canvas composition). Hosts that can only materialize a
    // subset (e.g. the C++ shell's catalog-bound working copies) must
    // pass false — the ghost cleanup is then skipped entirely, because a
    // membership absent from a PARTIAL composition is not evidence of
    // deletion (destructive-purge guard; contracts 03 §7).
    std::vector<std::string> ensure_memberships(
        const std::vector<LayerSnapshotInput>& snapshots,
        bool full_composition = true);

    // Explicit registration (RAW->DERIVED drafting / constraint creation
    // / factor runs). V13 W-I: a non-empty source_version_id without an
    // explicit kind defaults to catalog_version; constraint layers pass
    // content_fingerprint explicitly. Re-registering re-pins (overwrite).
    void register_layer(const std::string& layer_id, const std::string& role,
                        const std::string& factor_task_id = "",
                        const std::string& constraint_kind = "",
                        const std::string& source_version_id = "",
                        const std::string& source_asset_id = "",
                        const std::string& binding_kind = "",
                        const std::string& bound_at = "");
    void unregister_layer(const std::string& layer_id);

    // -- stage view-state policy ----------------------------------------------
    // Effective group visibility for the stage (profile defaults + user
    // overrides) — POLICY ONLY; the host applies the result to the real
    // QGIS tree (pwb::qgis::LayerTreeComposer::apply_group_visibility).
    // Also seeds the evidence-lock defaults into the stage view state
    // (locked groups stay locked until the user unlocks).
    std::map<std::string, bool> effective_stage_visibility(MappingStage stage);

    // User gesture recorders (ONLY from user echo entry points —
    // programmatic stage pushes must never freeze defaults into
    // overrides).
    void record_group_visibility_event(const std::string& group_id,
                                       bool visible);
    void record_layer_visibility_event(const std::string& layer_id,
                                       bool visible);
    void record_layer_opacity_event(const std::string& layer_id,
                                    double opacity);

    // -- routing queries ---------------------------------------------------------
    // Home group of a layer by membership routing (no live tree access;
    // runtime placement is read from the real QGIS tree via the composer).
    std::string home_group_of(const std::string& layer_id) const;
    // Drag-drop legality: may a layer with this role enter the target
    // system group (user groups always allow — visual organization only).
    bool placement_allowed(const std::string& layer_id,
                           const std::string& group_id) const;
    // factor task titles (host syncs from the project document; the
    // composer reads them when creating factor groups).
    std::map<std::string, std::string> factor_titles;

    pwb::workspace::MappingWorkspaceState& state() const { return state_; }

private:
    pwb::workspace::MappingWorkspaceState& state_;
};

}  // namespace pwb::ui_composite
