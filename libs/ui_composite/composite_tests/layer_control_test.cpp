// ui_composite.layer_control — QGIS-native convergence policy battery.
//
// The V14 fake-stack/reconcile battery retired with the second layer
// tree (the real QgsLayerTree is exercised by platform.layer_tree_
// composer). What remains Qt-free here is the POLICY half: membership
// lifecycle, stage view-state policy (defaults + overlay + evidence
// locks), stage switching through execution hooks (ordering, no
// cross-stage target inheritance), user gesture recorders, and the
// routing vocabulary (role bands / home groups / placement legality).
#include <pwb/ui_composite/layer_group_controller.hpp>
#include <pwb/ui_composite/layer_ordering.hpp>
#include <pwb/ui_composite/layer_stage_controller.hpp>
#include <pwb/ui_composite/stage_profiles.hpp>
#include <pwb/workspace/mutations.hpp>
#include <pwb/workspace/state_ops.hpp>

#include <cmath>
#include <cstdio>
#include <map>
#include <optional>
#include <string>
#include <vector>

namespace {

int failures = 0;

void check(bool ok, const char* what) {
    if (!ok) {
        ++failures;
        std::fprintf(stderr, "FAIL: %s\n", what);
    }
}

pwb::ui_composite::LayerSnapshotInput snapshot(const std::string& id,
                                               const std::string& role = "",
                                               const std::string& geometry = "") {
    pwb::ui_composite::LayerSnapshotInput input;
    input.id = id;
    if (!role.empty()) input.metadata["role"] = role;
    input.geometry_type = geometry;
    return input;
}

}  // namespace

int main() {
    using namespace pwb::ui_composite;
    using MS = MappingStage;
    using pwb::workspace::MappingWorkspaceState;

    // --- membership lifecycle ---------------------------------------------
    {
        MappingWorkspaceState state;
        LayerGroupController groups(state);
        const std::vector<LayerSnapshotInput> snapshots = {
            snapshot("well:1", "base_reference"),
            snapshot("draft:1", "initial_facies_draft", "facies_polygon"),
        };
        const std::vector<std::string> added =
            groups.ensure_memberships(snapshots, /*full_composition=*/false);
        check(added.size() == 2, "first admission adds both");
        check(groups.ensure_memberships(snapshots, false).empty(),
              "admission idempotent");
        const pwb::workspace::LayerBinding* first =
            pwb::workspace::membership(state, "well:1");
        check(first != nullptr && first->role == "base_reference",
          "explicit role kept verbatim");
    }
    {
        MappingWorkspaceState state;
        LayerGroupController groups(state);
        groups.register_layer("old:1", "initial_facies_draft");
        // Partial composition (working-copy subset): absent != deleted.
        groups.ensure_memberships({snapshot("new:1", "analysis_aid")}, false);
        check(pwb::workspace::membership(state, "old:1") != nullptr,
              "partial composition never cleans ghosts");
        // Full composition without the layer IS evidence: ghost dropped,
        // descriptor-only roles exempt.
        groups.register_layer("grid:1", "factor_grid");
        groups.ensure_memberships({snapshot("new:1", "analysis_aid")}, true);
        check(pwb::workspace::membership(state, "old:1") == nullptr,
              "full composition drops ghosts");
        check(pwb::workspace::membership(state, "grid:1") != nullptr,
              "descriptor-only roles survive ghost cleanup");
    }
    {
        MappingWorkspaceState state;
        LayerGroupController groups(state);
        // V13 W-I: pinned version without explicit kind -> catalog_version.
        groups.register_layer("c:1", "distribution_line", "", "", "ver-9");
        const pwb::workspace::LayerBinding* binding =
            pwb::workspace::membership(state, "c:1");
        check(binding != nullptr &&
                  binding->binding_kind ==
                      std::string(pwb::workspace::kBindingCatalogVersion),
              "version kind defaults to catalog_version");
        check(binding != nullptr && binding->source_version_id == "ver-9",
              "pinned version kept");
        groups.register_layer("c:1", "paleo_shoreline");
        binding = pwb::workspace::membership(state, "c:1");
        check(binding != nullptr && binding->role == "paleo_shoreline",
              "re-register re-pins");
        groups.unregister_layer("c:1");
        check(pwb::workspace::membership(state, "c:1") == nullptr,
              "unregister drops membership");
    }

    // --- stage view-state policy -------------------------------------------
    {
        MappingWorkspaceState state;
        LayerGroupController groups(state);
        const std::map<std::string, bool> effective =
            groups.effective_stage_visibility(MS::ConstraintFactor);
        const StageProfile& profile = stage_profile(MS::ConstraintFactor);
        bool defaults_hold = !effective.empty();
        for (const auto& [group_id, visible] : profile.group_visibility) {
            const auto it = effective.find(group_id);
            if (it == effective.end() || it->second != visible) {
                defaults_hold = false;
            }
        }
        check(defaults_hold, "profile defaults drive effective visibility");
        // Evidence-lock defaults seeded into the stage view state.
        const pwb::workspace::StageViewState& view =
            pwb::workspace::view_state(state, "constraint_factor");
        bool locks_seeded = true;
        for (const std::string& group_id : profile.locked_groups) {
            const auto locked = view.group_locked.find(group_id);
            if (locked == view.group_locked.end() || !locked->second.has_value() ||
                !*locked->second) {
                locks_seeded = false;
            }
        }
        check(locks_seeded, "evidence locks seeded into view state");
        // User overlay wins over the profile default (recorded into the
        // stage the policy will read).
        state.current_stage = "constraint_factor";
        groups.record_group_visibility_event(kBaseReferenceGroupId, false);
        const std::map<std::string, bool> after =
            groups.effective_stage_visibility(MS::ConstraintFactor);
        const auto flipped = after.find(kBaseReferenceGroupId);
        check(flipped != after.end() && !flipped->second,
              "user overlay flips group visibility");
    }
    {
        MappingWorkspaceState state;
        LayerGroupController groups(state);
        groups.record_layer_visibility_event("lay:1", false);
        groups.record_layer_opacity_event("lay:1", 0.35);
        const pwb::workspace::StageViewState& view =
            pwb::workspace::view_state(state, state.current_stage);
        const auto vis = view.layer_visibility.find("lay:1");
        check(vis != view.layer_visibility.end() && vis->second.has_value() &&
                  !*vis->second,
              "layer visibility recorded per stage");
        const auto opa = view.layer_opacity.find("lay:1");
        check(opa != view.layer_opacity.end() && opa->second.has_value() &&
                  std::abs(*opa->second - 0.35) < 1e-9,
              "layer opacity recorded per stage");
    }

    // --- stage controller: hooks, ordering, target policy --------------------
    {
        MappingWorkspaceState state;
        LayerGroupController groups(state);
        LayerStageController stages(state, groups);
        std::vector<std::string> calls;
        std::size_t pushed_entries = 0;
        stages.set_target_resolver(
            [](const std::string&) -> std::optional<std::string> {
                return "layer:constraint";
            });
        stages.set_tree_execution(
            [&]() { calls.push_back("ensure"); },
            [&](const std::map<std::string, bool>& visibility) {
                calls.push_back("visibility");
                pushed_entries = visibility.size();
            });
        stages.active_target_changed =
            [&](const std::optional<std::string>& target) {
                calls.push_back("target:" + target.value_or("<none>"));
            };
        check(stages.set_stage(MS::ConstraintFactor), "stage switch accepted");
        check(calls.size() >= 3, "hooks fired");
        check(calls.size() >= 1 && calls[0] == "ensure",
              "ensure groups first");
        check(calls.size() >= 2 && calls[1] == "visibility",
              "visibility push second");
        check(calls.size() >= 3 &&
                  calls[2].rfind("target:", 0) == 0,
              "target reassignment last");
        check(pushed_entries > 0, "visibility map non-empty");
        const std::size_t calls_before = calls.size();
        check(!stages.set_stage(MS::ConstraintFactor),
              "duplicate switch refused");
        check(calls.size() == calls_before, "no re-push on duplicate");
    }
    {
        MappingWorkspaceState state;
        LayerGroupController groups(state);
        LayerStageController stages(state, groups);
        stages.set_target_resolver([](const std::string&)
                                       -> std::optional<std::string> {
            return "layer:constraint";
        });
        stages.set_stage(MS::ConstraintFactor);
        check(stages.active_target_layer_id().has_value() &&
                  *stages.active_target_layer_id() == "layer:constraint",
              "role resolver picks the target");
        // Switching without a resolver hit: target resets — NEVER
        // inherited across stages (V5 §88).
        stages.set_target_resolver(
            [](const std::string&) -> std::optional<std::string> {
                return std::nullopt;
            });
        check(stages.set_stage(MS::IntegratedCompilation),
              "second switch accepted");
        check(!stages.active_target_layer_id().has_value(),
              "target never inherited across stages");
        stages.set_active_target("layer:comp");
        check(stages.active_target_layer_id().has_value() &&
                  *stages.active_target_layer_id() == "layer:comp",
              "explicit target recorded");
        const pwb::workspace::StageViewState& view =
            pwb::workspace::view_state(state, "integrated_compilation");
        check(view.active_layer_id.has_value() &&
                  *view.active_layer_id == "layer:comp",
              "explicit target persisted per stage");
    }
    {
        MappingWorkspaceState state;
        LayerGroupController groups(state);
        LayerStageController stages(state, groups);
        state.current_stage = "integrated_compilation";
        pwb::workspace::view_state(state, "integrated_compilation")
            .active_layer_id = "layer:live";
        int validates = 0;
        stages.set_target_validator([&](const std::string& layer_id) {
            ++validates;
            return layer_id == "layer:live";
        });
        stages.restore_stage_view();
        check(stages.active_target_layer_id().has_value() &&
                  *stages.active_target_layer_id() == "layer:live",
              "persisted target restored when layer exists");
        check(validates > 0, "validator probed");
        // Persisted target pointing at a GONE layer: fail-closed.
        pwb::workspace::view_state(state, "integrated_compilation")
            .active_layer_id = "layer:gone";
        state.current_stage = "integrated_compilation";
        LayerStageController fresh(state, groups);
        fresh.set_target_validator([](const std::string& layer_id) {
            return layer_id == "layer:live";
        });
        fresh.restore_stage_view();
        check(!fresh.active_target_layer_id().has_value(),
              "gone target fails closed");
    }

    // --- routing vocabulary ----------------------------------------------------
    {
        // Scientific band vocabulary moved verbatim from the retired
        // workspace::layer_order (spot checks over the oracle table).
        check(role_band("qc_warning") == 20, "band qc_warning");
        check(role_band("integrated_facies") == 50, "band integrated_facies");
        check(role_band("factor_input") == 90, "band factor_input");
        check(role_band("factor_qc") == 100, "band factor_qc");
        check(role_band("base_reference") == 150, "band base_reference");
        check(role_band("no_such_role") == 150, "unknown role -> reference band");
        check(!role_bands().empty(), "band table non-empty");
        check(factor_role_rank("factor_contour") == 2, "factor rank contour");
        check(factor_role_rank("unknown") == 99, "unknown factor rank tail");
    }
    {
        MappingWorkspaceState state;
        LayerGroupController groups(state);
        groups.register_layer("con:1", "distribution_line");
        check(groups.home_group_of("con:1") == "phase2.constraints",
              "membership routing to constraint group");
        check(groups.home_group_of("unknown:1") == kLegacyGroupId,
              "unknown role to legacy fallback");
        groups.register_layer("fgrid:1", "factor_grid", "task-7");
        check(groups.home_group_of("fgrid:1") == "factor.task-7",
              "factor roles route to per-task subgroup");
        check(groups.placement_allowed("con:1", "phase2.constraints"),
              "role-compatible system group accepts");
        check(!groups.placement_allowed("con:1", "phase3.integrated"),
              "role-incompatible system group refuses");
        check(groups.placement_allowed("con:1", "user_whatever"),
              "user groups always allow");
    }
    {
        // The controller is constructible/destructible purely around the
        // state reference (no stack, no canvas, no Qt) — the compile-time
        // contract that no second tree lives on the domain side.
        MappingWorkspaceState state;
        {
            LayerGroupController groups(state);
            check(&groups.state() == &state, "state reference held, not copied");
        }
    }

    if (failures > 0) {
        std::fprintf(stderr, "layer_control policy: %d failure(s)\n", failures);
        return 1;
    }
    std::printf("layer_control policy: all checks passed\n");
    return 0;
}
