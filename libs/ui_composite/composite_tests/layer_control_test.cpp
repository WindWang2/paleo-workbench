// V14 composite.layer_control — LayerGroupController /
// LayerStageController / LayerTargets / presentation over a recording
// fake stack. Asserts the V14 contracts (docs/development/
// qgis-v14-layer-control/03-contracts.md §3/§4/§5/§6/§8) with
// CALL-COUNT evidence: batched tree transactions, minimal diff ops,
// honest degradation, fail-closed targets and stage-switch order
// preservation.

#include "pwb/ui_composite/layer_group_controller.hpp"
#include "pwb/ui_composite/layer_presentation.hpp"
#include "pwb/ui_composite/layer_stage_controller.hpp"
#include "pwb/ui_composite/layer_targets.hpp"
#include "pwb/workspace/mutations.hpp"
#include "pwb/workspace/state_ops.hpp"

#include <algorithm>
#include <cstdio>
#include <functional>
#include <optional>
#include <set>
#include <string>
#include <vector>

namespace {

int g_failures = 0;

void check(bool condition, const char* what) {
    if (!condition) {
        ++g_failures;
        std::fprintf(stderr, "FAIL: %s\n", what);
    }
}

using pwb::ui_composite::ILayerTreeStack;
using pwb::ui_composite::LayerGroupController;
using pwb::ui_composite::LayerSnapshotInput;
using pwb::ui_composite::LayerStageController;
using pwb::ui_composite::LayerTargets;
using pwb::ui_composite::PlacementOp;
using pwb::ui_composite::PlacementReport;
using pwb::ui_composite::TreeUpdateResult;
using pwb::workspace::MappingWorkspaceState;

// Recording fake: counts every seam call (the call-count contract
// carrier) and simulates a QGIS-side tree well enough for reconcile
// semantics (groups exist; placements apply).
class FakeStack : public ILayerTreeStack {
public:
    struct Counts {
        int upsert_group = 0;
        int rename_group = 0;
        int remove_groups_except = 0;
        int move_layer = 0;
        int move_group = 0;
        int apply_placements = 0;
        int set_group_visibility = 0;
        int set_group_expanded = 0;
        int begin_tree_update = 0;
        int end_tree_update = 0;
    };
    Counts counts;
    int open_windows = 0;  // >0 between begin and end
    std::vector<std::string> groups;
    int skipped_placements = 0;  // injectable failure
    bool available = true;
    bool throw_on_upsert = false;
    std::uint64_t revision = 0;
    std::map<std::string, bool> visibility;

    bool groups_available() const override { return available; }

    void upsert_group(const std::string& group_id, const std::string&,
                      const std::string&) override {
        if (throw_on_upsert) throw std::runtime_error("bridge upsert failed");
        ++counts.upsert_group;
        if (std::find(groups.begin(), groups.end(), group_id) ==
            groups.end()) {
            groups.push_back(group_id);
            ++revision;
        }
    }
    void rename_group(const std::string&, const std::string&) override {
        ++counts.rename_group;
    }
    void remove_groups_except(
        const std::vector<std::string>& keep_ids) override {
        ++counts.remove_groups_except;
        std::vector<std::string> kept;
        for (const std::string& gid : groups) {
            if (std::find(keep_ids.begin(), keep_ids.end(), gid) !=
                keep_ids.end()) {
                kept.push_back(gid);
            }
        }
        if (kept.size() != groups.size()) ++revision;
        groups = std::move(kept);
    }
    void move_layer_to_group(const std::string&, const std::string&,
                             int) override {
        ++counts.move_layer;
        ++revision;
    }
    void move_group(const std::string&, const std::string&, int) override {
        ++counts.move_group;
        ++revision;
    }
    PlacementReport apply_tree_placements(
        const std::vector<PlacementOp>& ops) override {
        ++counts.apply_placements;
        PlacementReport report;
        for (const PlacementOp& op : ops) {
            (void)op;
            if (skipped_placements > 0) {
                --skipped_placements;
                ++report.skipped;
                continue;
            }
            ++report.applied;
        }
        ++revision;
        report.revision = revision;
        return report;
    }
    void set_group_visibility(const std::string& group_id,
                              bool visible) override {
        ++counts.set_group_visibility;
        visibility[group_id] = visible;
    }
    void set_group_expanded(const std::string&, bool) override {
        ++counts.set_group_expanded;
    }
    std::optional<std::int64_t> begin_tree_update() override {
        ++counts.begin_tree_update;
        ++open_windows;
        return 42;
    }
    TreeUpdateResult end_tree_update(std::int64_t token) override {
        if (token != 42) {
            throw std::runtime_error("token mismatch (fake contract)");
        }
        ++counts.end_tree_update;
        --open_windows;
        TreeUpdateResult result;
        result.revision = ++revision;
        result.deferred_sync = true;
        return result;
    }
};

LayerSnapshotInput snap(const std::string& id) {
    LayerSnapshotInput input;
    input.id = id;
    return input;
}

MappingWorkspaceState sample_state() {
    pwb::domain::Json doc = pwb::domain::Json::parse(R"({
        "schema_version": 1,
        "current_stage": "facies_calibration",
        "memberships": {
            "draft1": {"role": "initial_facies_draft",
                       "created_stage": "facies_calibration"},
            "prov1": {"role": "provenance_line",
                      "created_stage": "constraint_factor"},
            "base1": {"role": "base_reference"}
        }
    })");
    pwb::domain::DiagnosticList diagnostics;
    return MappingWorkspaceState::from_json(doc, diagnostics);
}


void check_keys_stable(const std::map<std::string, std::string>& now,
                       const std::map<std::string, std::string>& before,
                       const std::set<std::string>& layer_ids,
                       const char* rewrite_label,
                       const char* drop_label) {
    for (const auto& entry : before) {
        auto it = now.find(entry.first);
        const bool is_layer = layer_ids.count(entry.first) != 0;
        if (it == now.end()) {
            // Only empty-group de-materialization may drop a key, and
            // only for groups.
            check(!is_layer, drop_label);
            continue;
        }
        check(it->second == entry.second, rewrite_label);
    }
}

void test_reconcile_batches_into_single_transaction() {
    MappingWorkspaceState state = sample_state();
    FakeStack stack;
    LayerGroupController controller(state);
    controller.attach_stack(&stack);

    const std::vector<LayerSnapshotInput> snapshots = {
        snap("draft1"), snap("prov1"), snap("base1")};
    controller.reconcile(snapshots);

    // Contract 03 §8: one transaction window per reconcile, exactly one
    // keep-set sweep, at most one batched placement call, zero per-move
    // calls.
    check(stack.counts.begin_tree_update == 1, "one begin_tree_update");
    check(stack.counts.end_tree_update == 1, "one end_tree_update");
    check(stack.counts.remove_groups_except == 1, "one remove_groups_except");
    check(stack.counts.apply_placements == 1,
          "exactly one placements batch (all layers move into fresh groups)");
    check(stack.counts.move_layer == 0, "no per-move layer calls");
    check(stack.counts.move_group == 0, "no per-move group calls");
    check(stack.open_windows == 0, "window closed");
    check(state.tree.is_object() && state.tree.contains("children"),
          "desired tree persisted into workspace state");
    check(controller.last_applied() != nullptr, "baseline recorded");
    check(!stack.groups.empty(), "system groups materialized");

    const FakeStack::Counts before = stack.counts;
    controller.reconcile(snapshots);
    check(stack.counts.upsert_group == before.upsert_group,
          "idempotent reconcile: no re-upsert");
    check(stack.counts.apply_placements == before.apply_placements,
          "idempotent reconcile: no placements");
    check(stack.counts.remove_groups_except ==
              before.remove_groups_except + 1,
          "keep-set sweep still runs (idempotent)");
}

void test_reconcile_skipped_placements_abort_keeps_baseline() {
    MappingWorkspaceState state = sample_state();
    FakeStack stack;
    LayerGroupController controller(state);
    controller.attach_stack(&stack);
    const std::vector<LayerSnapshotInput> snapshots = {
        snap("draft1"), snap("prov1")};
    controller.reconcile(snapshots);
    const auto* baseline = controller.last_applied();
    check(baseline != nullptr, "baseline exists");
    const std::size_t baseline_ops = baseline->iter_layers().size();

    stack.skipped_placements = 100;
    std::vector<LayerSnapshotInput> changed = snapshots;
    changed.push_back(snap("new_layer"));
    bool threw = false;
    try {
        controller.reconcile(changed);
    } catch (const std::runtime_error&) {
        threw = true;
    }
    check(threw, "skipped placements abort the reconcile (R2-P0)");
    check(controller.last_applied() == baseline, "baseline unchanged");
    check(controller.last_applied()->iter_layers().size() == baseline_ops,
          "baseline ops unchanged");
    check(stack.open_windows == 0, "window still closed on abort");
}

void test_bridge_failure_keeps_baseline_and_window_closed() {
    MappingWorkspaceState state = sample_state();
    FakeStack stack;
    stack.throw_on_upsert = true;
    LayerGroupController controller(state);
    controller.attach_stack(&stack);
    bool threw = false;
    try {
        controller.reconcile({snap("draft1")});
    } catch (const std::runtime_error&) {
        threw = true;
    }
    check(threw, "bridge failure propagates");
    check(controller.last_applied() == nullptr, "no baseline on failure");
    check(stack.open_windows == 0, "window closed on failure");
    check(!controller.reconciling(), "reconciling flag reset");
}

void test_degraded_stack_is_honest_noop() {
    MappingWorkspaceState state = sample_state();
    FakeStack stack;
    stack.available = false;
    LayerGroupController controller(state);
    controller.attach_stack(&stack);
    check(controller.degraded(), "old bridge degrades");
    check(!controller.layer_groups_enabled(), "group publish disabled");
    controller.reconcile({snap("draft1")});
    check(stack.counts.begin_tree_update == 0, "no window while degraded");
    check(controller.last_applied() == nullptr, "no baseline while degraded");
    const auto effective = controller.apply_stage_visibility(
        pwb::tool_policy::MappingStage::ConstraintFactor);
    check(effective.empty(), "degraded visibility returns empty");
    check(controller.last_degraded_reason().has_value(),
          "degraded reason recorded (persistent, host must show)");
}

void test_no_stack_full_fallback() {
    MappingWorkspaceState state = sample_state();
    LayerGroupController controller(state);
    controller.attach_stack(nullptr);
    check(controller.degraded(), "no stack = fully degraded");
    controller.reconcile({snap("draft1")});
    check(controller.last_applied() == nullptr, "no baseline without stack");
    check(!controller.placement_of("draft1").empty(),
          "placement queries still route while degraded");
}

void test_register_layer_binds_version_with_default_kind() {
    MappingWorkspaceState state = sample_state();
    LayerGroupController controller(state);

    controller.register_layer("new_layer", "facies_boundary", "", "", "ver_1",
                              "asset_1");
    const pwb::workspace::LayerBinding* binding =
        pwb::workspace::membership(state, "new_layer");
    check(binding != nullptr, "registered");
    check(binding->source_version_id == "ver_1", "version pinned");
    check(binding->source_asset_id == "asset_1", "asset recorded");
    check(binding->binding_kind == "catalog_version",
          "default kind catalog_version (V13 W-I)");
    check(!binding->bound_at.empty(), "bound_at stamped at pin time");
    check(binding->created_stage == "facies_calibration",
          "created at current stage");

    controller.register_layer("new_layer", "facies_boundary", "", "", "ver_2",
                              "asset_1");
    binding = pwb::workspace::membership(state, "new_layer");
    check(binding != nullptr && binding->source_version_id == "ver_2",
          "re-register re-pins");

    controller.register_layer("fault1", "fault_constraint", "", "fault", "",
                              "", "content_fingerprint");
    binding = pwb::workspace::membership(state, "fault1");
    check(binding != nullptr &&
              binding->binding_kind == "content_fingerprint",
          "explicit fingerprint kind preserved");

    pwb::workspace::record_layer_visibility(
        pwb::workspace::view_state(state, "facies_calibration"), "new_layer",
        false);
    controller.unregister_layer("new_layer");
    check(pwb::workspace::membership(state, "new_layer") == nullptr,
          "unregister clears binding");
    check(pwb::workspace::view_state(state, "facies_calibration")
                  .layer_visibility.count("new_layer") == 0,
          "unregister purges view-state overlays");
}

void test_observe_tree_nodes_validates_and_rekeys() {
    MappingWorkspaceState state = sample_state();
    FakeStack stack;
    LayerGroupController controller(state);
    controller.attach_stack(&stack);

    const std::string draft_home =
        pwb::ui_composite::effective_home_group("initial_facies_draft");
    check(!draft_home.empty(), "draft home group resolves");

    std::string rejected_layer, rejected_group;
    controller.on_invalid_move = [&](const std::string& layer,
                                     const std::string& group) {
        rejected_layer = layer;
        rejected_group = group;
    };
    // Illegal: a provenance line dragged into the phase1 draft system
    // group (role routing conflict) — rejected with the pair.
    const std::string bad_json =
        std::string(R"([{"type":"group","id":")") + draft_home +
        R"(","name":"draft","children":[{"type":"layer","id":"prov1"}]}])";
    check(!controller.observe_tree_nodes(pwb::domain::Json::parse(bad_json)),
          "illegal placement rejected");
    check(controller.last_observe_rejected, "rejection flag set");
    check(rejected_layer == "prov1", "rejected layer reported");
    check(rejected_group == draft_home, "rejected group reported");

    // Legal: user drags layers into a user group; observed order becomes
    // stable keys.
    bool structure_changed = false;
    controller.on_structure_changed = [&] { structure_changed = true; };
    check(controller.observe_tree_nodes(pwb::domain::Json::parse(R"([
        {"type":"group","id":"user.1","name":"我的组",
         "children":[{"type":"layer","id":"prov1"},
                     {"type":"layer","id":"draft1"}]},
        {"type":"layer","id":"base1"}
    ])")),
          "legal observation accepted");
    check(!controller.last_observe_rejected, "no rejection on legal tree");
    check(structure_changed, "structure notification fired");
    check(controller.order_keys().count("prov1") == 1, "prov1 keyed");
    check(controller.order_keys().count("draft1") == 1, "draft1 keyed");
    check(controller.order_keys().at("prov1") <
              controller.order_keys().at("draft1"),
          "observed order encoded in keys");
    check(controller.placement_of("prov1") == "user.1", "prov1 in user group");
    check(controller.placement_of("base1").empty(), "base1 at root");
}

void test_stage_switch_preserves_order_and_reassigns_target() {
    MappingWorkspaceState state = sample_state();
    FakeStack stack;
    LayerGroupController controller(state);
    controller.attach_stack(&stack);
    const std::vector<LayerSnapshotInput> snapshots = {
        snap("draft1"), snap("prov1"), snap("base1")};
    controller.reconcile(snapshots);
    const auto keys_before = controller.order_keys();
    const std::size_t visibility_before = stack.counts.set_group_visibility;

    LayerStageController stage_controller(state, controller);
    std::optional<std::string> active_target_seen;
    stage_controller.active_target_changed =
        [&](const std::optional<std::string>& id) { active_target_seen = id; };
    stage_controller.set_target_resolver([](const std::string& role) {
        (void)role;
        return std::optional<std::string>("draft1");
    });

    check(stage_controller.set_stage(
              pwb::tool_policy::MappingStage::ConstraintFactor),
          "stage switch accepted");
    check(state.current_stage == "constraint_factor", "stage written");
    check(stack.counts.set_group_visibility > visibility_before,
          "visibility pushed (group count, not layer count)");
    check_keys_stable(controller.order_keys(), keys_before,
                      {"draft1", "prov1", "base1"},
                      "stage switch never rewrites an existing order key",
                      "stage switch never drops a LAYER key");
    check(active_target_seen.has_value() && *active_target_seen == "draft1",
          "target reassigned via profile roles");
    check(state.stage_states.count("constraint_factor") != 0,
          "stage view state exists");

    stage_controller.set_active_target("prov1");
    check(stage_controller.active_target_layer_id().has_value() &&
              *stage_controller.active_target_layer_id() == "prov1",
          "explicit user target recorded");
    check(pwb::workspace::view_state(state, "constraint_factor")
                  .active_layer_id ==
              std::optional<std::string>("prov1"),
          "target persisted per-stage (V13 W-P)");

    const auto visibility_after = stack.counts.set_group_visibility;
    check(!stage_controller.set_stage(
              pwb::tool_policy::MappingStage::ConstraintFactor),
          "duplicate stage request is a no-op");
    check(stack.counts.set_group_visibility == visibility_after,
          "no visibility churn on no-op");

    check(stage_controller.set_stage(
              pwb::tool_policy::MappingStage::FaciesCalibration),
          "switch back accepted");
    check_keys_stable(controller.order_keys(), keys_before,
                      {"draft1", "prov1", "base1"},
                      "round-trip switch preserves existing keys",
                      "round-trip switch never drops a LAYER key");
    check(pwb::workspace::view_state(state, "facies_calibration")
                  .active_layer_id ==
              std::optional<std::string>("draft1"),
          "stage-1 stored target restored (no cross-stage inheritance)");
}

void test_stage_switch_survives_rematerize_failure() {
    MappingWorkspaceState state = sample_state();
    FakeStack stack;
    LayerGroupController controller(state);
    controller.attach_stack(&stack);
    // Establish a composition baseline first so rematerialize_for_stage
    // actually runs (it early-returns false without one); then make the
    // bridge throw mid-rematerialize.
    controller.reconcile({snap("draft1"), snap("base1")});
    stack.throw_on_upsert = true;
    LayerStageController stage_controller(state, controller);
    check(stage_controller.set_stage(
              pwb::tool_policy::MappingStage::IntegratedCompilation),
          "stage switch survives rematerialize failure (R2-P1)");
    check(state.current_stage == "integrated_compilation",
          "stage still switched");
}

void test_user_group_lifecycle_hoists_children() {
    MappingWorkspaceState state = sample_state();
    FakeStack stack;
    LayerGroupController controller(state);
    controller.attach_stack(&stack);
    controller.reconcile({snap("draft1"), snap("prov1"), snap("base1")});

    const std::string gid = controller.create_user_group("调研组");
    check(gid.rfind("user.", 0) == 0, "user group id minted");
    const std::string nodes_json =
        std::string(R"([{"type":"group","id":")") + gid +
        R"(","name":"调研组","children":[{"type":"layer","id":"prov1"}]},
           {"type":"layer","id":"draft1"}])";
    check(controller.observe_tree_nodes(pwb::domain::Json::parse(nodes_json)),
          "user group observation accepted");
    controller.remove_user_group(gid);
    check(pwb::workspace::membership(state, "prov1") != nullptr,
          "removing a group never deletes layers");
    check(controller.placement_of("prov1").empty(),
          "child hoisted to root");
}

void test_place_copy_adjacent_puts_copy_above_source() {
    MappingWorkspaceState state = sample_state();
    LayerGroupController controller(state);
    check(controller.observe_tree_nodes(pwb::domain::Json::parse(
              R"([{"type":"layer","id":"draft1"},
                  {"type":"layer","id":"prov1"}])")),
          "root observation accepted");
    const std::string home =
        controller.place_copy_adjacent("draft1", "draft_copy");
    check(home.empty(), "copy placed at root (source's container)");
    pwb::workspace::LayerBinding copy_binding;
    copy_binding.layer_id = "draft_copy";
    copy_binding.role = "initial_facies_draft";
    pwb::workspace::set_membership(state, copy_binding);
    const auto desired = controller.build_desired_tree(
        {snap("draft1"), snap("prov1"), snap("draft_copy")});
    const std::vector<std::string> ids = desired.layer_ids_top_first();
    auto pos_copy = std::find(ids.begin(), ids.end(), "draft_copy");
    auto pos_source = std::find(ids.begin(), ids.end(), "draft1");
    check(pos_copy != ids.end() && pos_source != ids.end(),
          "copy and source in desired tree");
    // Domain root list tail renders on top: copy one slot after the
    // source in the list = directly above it on screen.
    check(pos_copy == pos_source + 1, "copy sits directly above source");
}

void test_targets_invariants_fail_closed() {
    LayerTargets targets;
    std::set<std::string> live{"A", "B"};
    targets.set_probes(
        [&](const std::string& id) { return live.count(id) != 0; },
        [&](const std::string& id) { return id == "A"; },
        [&]() { return std::optional<std::string>("A"); });

    auto arm = targets.arm_edit_tool("A");
    check(arm.result == pwb::ui_composite::ToolArmResult::kRejectedNotEditing,
          "arming outside the edit set fails closed");
    check(!arm.reason.empty(), "rejection carries a user-facing reason");

    check(targets.start_editing("A"), "start editing");
    arm = targets.arm_edit_tool("A");
    check(arm.result == pwb::ui_composite::ToolArmResult::kArmed,
          "arming inside the edit set succeeds");
    check(targets.invariant_tool_target_in_editing_set(),
          "tool target invariant holds");

    targets.note_selection("B");
    check(*targets.tool_target_id() == "A",
          "selection never moves the write target");
    check(targets.selection_mismatch(),
          "selection mismatch surfaced (03 §5.5)");

    live.erase("A");
    const auto report = targets.revalidate();
    check(report.dropped_editing.size() == 1, "deleted layer dropped");
    check(report.dropped_dirty_editing.size() == 1,
          "dirty session reported for fail/close");
    check(report.tool_disarmed, "tool disarmed");
    check(!targets.tool_target_id().has_value(), "tool target cleared");
    check(report.native_drift, "native drift reported, not papered over");

    check(targets.start_editing("B"), "start editing B");
    check(targets.arm_edit_tool("B").result ==
              pwb::ui_composite::ToolArmResult::kArmed,
          "re-arm on B");
    check(targets.stop_editing("B"), "stop editing clears");
    check(!targets.tool_target_id().has_value(),
          "stopping the last edit disarms the tool");
}

void test_presentation_flags_and_summary() {
    pwb::workspace::LayerBinding binding;
    binding.layer_id = "raw1";
    binding.role = "well_facies_prediction";
    binding.source_version_id = "v1";
    binding.binding_kind = "catalog_version";

    pwb::ui_composite::LayerRowInputs inputs;
    inputs.layer_id = "raw1";
    inputs.binding = &binding;
    inputs.is_active = true;
    inputs.freshness = pwb::ui_composite::LayerFreshness::Stale;
    const auto status = pwb::ui_composite::build_layer_row_status(inputs);
    check(status.raw_protected, "RAW role detected");
    check(status.has_flag("active"), "active flag");
    check(status.has_flag("raw"), "raw flag");
    check(status.has_flag("stale"), "stale flag");
    check(status.bound_to_version, "version-bound");
    check(!status.has_flag("editing"), "not editing");

    pwb::ui_composite::LayerRowInputs missing = inputs;
    missing.freshness = pwb::ui_composite::LayerFreshness::SourceMissing;
    missing.is_editing = true;
    missing.is_dirty = true;
    const auto missing_status =
        pwb::ui_composite::build_layer_row_status(missing);
    check(missing_status.has_flag("source_missing"), "source missing flag");
    check(missing_status.has_flag("dirty"), "dirty flag");

    const std::string summary =
        pwb::ui_composite::layer_row_summary(missing);
    check(summary.find("v1") != std::string::npos, "summary names version");
    check(summary.find("数据源缺失") != std::string::npos,
          "summary names missing source");
    check(summary.find("未提交") != std::string::npos,
          "summary names uncommitted edits");
}

void test_scale_reconcile_thousand_layers_call_counts() {
    // 1000 layers across 20 factor containers: one window, one keep-set
    // sweep, at most one batched placement call (contract 03 §8).
    pwb::domain::Json doc = pwb::domain::Json::object();
    doc["schema_version"] = 1;
    doc["current_stage"] = "constraint_factor";
    pwb::domain::Json memberships = pwb::domain::Json::object();
    std::vector<LayerSnapshotInput> snapshots;
    for (int i = 0; i < 1000; ++i) {
        const std::string role = i % 3 == 0   ? "factor_grid"
                                 : i % 3 == 1 ? "factor_contour"
                                              : "factor_input";
        const std::string task = "task_" + std::to_string(i % 20);
        const std::string id = "fl_" + std::to_string(i);
        pwb::domain::Json record = pwb::domain::Json::object();
        record["role"] = role;
        record["factor_task_id"] = task;
        record["created_stage"] = "constraint_factor";
        memberships[id] = record;
        snapshots.push_back(snap(id));
    }
    doc["memberships"] = memberships;
    pwb::domain::DiagnosticList diagnostics;
    MappingWorkspaceState state =
        MappingWorkspaceState::from_json(doc, diagnostics);

    FakeStack stack;
    LayerGroupController controller(state);
    controller.attach_stack(&stack);
    controller.reconcile(snapshots);
    check(stack.counts.begin_tree_update == 1, "1000 layers: one window");
    check(stack.counts.end_tree_update == 1, "1000 layers: one close");
    check(stack.counts.remove_groups_except == 1,
          "1000 layers: one keep-set sweep");
    check(stack.counts.apply_placements <= 1,
          "1000 layers: at most one placement batch");
    check(stack.counts.move_layer == 0, "1000 layers: no per-move calls");
    check(stack.counts.move_group == 0, "1000 layers: no group per-moves");
    check(stack.groups.size() >= 20, "20 factor containers materialized");

    const auto keys = controller.order_keys();
    LayerStageController stage_controller(state, controller);
    for (int i = 0; i < 10; ++i) {
        stage_controller.set_stage(
            i % 2 == 0
                ? pwb::tool_policy::MappingStage::ConstraintFactor
                : pwb::tool_policy::MappingStage::FaciesCalibration);
    }
    // LAYER keys (fl_*) may never drop or change; group keys follow the
    // empty-group materialization semantics (stable when present).
    std::set<std::string> layer_ids;
    for (int i = 0; i < 1000; ++i) {
        layer_ids.insert("fl_" + std::to_string(i));
    }
    check_keys_stable(controller.order_keys(), keys, layer_ids,
                      "10 stage switches never rewrite an existing key",
                      "10 stage switches never drop a LAYER key");
    for (const std::string& layer_id : layer_ids) {
        check(controller.order_keys().count(layer_id) == 1,
              "all 1000 layer keys survive stage switches");
    }
}

}  // namespace

int main() {
    test_reconcile_batches_into_single_transaction();
    test_reconcile_skipped_placements_abort_keeps_baseline();
    test_bridge_failure_keeps_baseline_and_window_closed();
    test_degraded_stack_is_honest_noop();
    test_no_stack_full_fallback();
    test_register_layer_binds_version_with_default_kind();
    test_observe_tree_nodes_validates_and_rekeys();
    test_stage_switch_preserves_order_and_reassigns_target();
    test_stage_switch_survives_rematerize_failure();
    test_user_group_lifecycle_hoists_children();
    test_place_copy_adjacent_puts_copy_above_source();
    test_targets_invariants_fail_closed();
    test_presentation_flags_and_summary();
    test_scale_reconcile_thousand_layers_call_counts();
    if (g_failures == 0) {
        std::printf("composite.layer_control: all checks passed\n");
        return 0;
    }
    std::printf("composite.layer_control: %d failures\n", g_failures);
    return 1;
}
