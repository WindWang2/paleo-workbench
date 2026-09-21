// V14 LayerGroupController — incremental reconcile between the domain
// group state and the QGIS layer tree. Port of
// paleo_workbench/mapping_workspace/layer_group_controller.py (V5 §76 /
// V11 / V13 W-I registration entry).
//
// Responsibilities: ensure system groups, layer membership assignment,
// QGIS tree reconcile, group visibility, group ordering, legacy-project
// migration. NOT responsible for geometry editing / science / QGIS
// rendering.
//
// Authority boundary (V5 §9): the QGIS layer tree is the RUNTIME
// authority for display/order/group structure; this controller owns the
// domain-side DESIRED tree (templates + memberships + user placements)
// applied incrementally through the stack seam, with user tree events
// written back — the two sides never fight (programmatic changes
// suppress echoes; user changes land in the desired tree first and wait
// for the next reconcile).
//
// Incremental guarantee (V5 §68): diff the desired tree against the
// last applied tree; only differences cross the seam
// (upsert_group / move / set_group_visibility / remove_groups_except),
// never a full rebuild. The stack is the explicit form of Python's
// duck-typed bridge surface — implementations: QgsLayerTreeStack
// (libs/qgis), the recording fake (tests), the existing Python bridge.
// Qt-free.
#pragma once

#include "pwb/ui_composite/layer_tree_plan.hpp"
#include "pwb/workspace/layer_tree.hpp"
#include "pwb/workspace/state.hpp"

#include <functional>
#include <map>
#include <optional>
#include <string>
#include <vector>

namespace pwb::ui_composite {

// Result of end_tree_update (Python end_tree_update JSON payload).
struct TreeUpdateResult {
    std::uint64_t revision = 0;
    bool deferred_sync = false;
};

// One batched placement (node = layer id or "group:<gid>").
struct PlacementOp {
    std::string node;
    std::string parent;  // "" = root
    int index = 0;       // top-first index inside parent
};

struct PlacementReport {
    int applied = 0;
    int skipped = 0;
    std::uint64_t revision = 0;
};

// The stack seam (Python's duck-typed layer-tree bridge surface).
// Implementations must be total: unsupported operations throw
// std::runtime_error with a diagnostic message (the controller's
// degraded paths key off groups_available()).
class ILayerTreeStack {
public:
    virtual ~ILayerTreeStack() = default;
    // False = old bridge / no bridge: grouping unavailable, the
    // controller degrades honestly (flat tree, never pretends).
    virtual bool groups_available() const = 0;

    virtual void upsert_group(const std::string& group_id,
                              const std::string& name,
                              const std::string& parent) = 0;
    virtual void rename_group(const std::string& group_id,
                              const std::string& name) = 0;
    virtual void remove_groups_except(
        const std::vector<std::string>& keep_ids) = 0;
    virtual void move_layer_to_group(const std::string& layer_id,
                                     const std::string& parent,
                                     int index) = 0;
    virtual void move_group(const std::string& group_id,
                            const std::string& parent, int index) = 0;
    // Batched placements; returns per-op counts. skipped > 0 aborts the
    // reconcile (R2-P0: silent drift would blind later diffs).
    virtual PlacementReport apply_tree_placements(
        const std::vector<PlacementOp>& ops) = 0;
    virtual void set_group_visibility(const std::string& group_id,
                                      bool visible) = 0;
    virtual void set_group_expanded(const std::string& group_id,
                                    bool expanded) = 0;

    // Transaction window: nullopt = unsupported (degraded per-call
    // semantics — behavior unchanged, batching lost). end_tree_update
    // always closes (applied changes stay on partial failure; the host
    // reconciles via revision/diff).
    virtual std::optional<std::int64_t> begin_tree_update() = 0;
    virtual TreeUpdateResult end_tree_update(std::int64_t token) = 0;
};

// RAII transaction window over the stack (Python tree_transaction).
// Closes exactly once, even on exceptions; degraded stacks are a no-op.
class TreeTransactionWindow {
public:
    TreeTransactionWindow() = default;
    explicit TreeTransactionWindow(ILayerTreeStack& stack);
    ~TreeTransactionWindow();
    TreeTransactionWindow(const TreeTransactionWindow&) = delete;
    TreeTransactionWindow& operator=(const TreeTransactionWindow&) = delete;
    TreeTransactionWindow(TreeTransactionWindow&& other) noexcept;
    TreeTransactionWindow& operator=(TreeTransactionWindow&& other) noexcept;

    bool degraded() const { return token_ < 0; }
    const TreeUpdateResult& result() const { return result_; }
    // Close explicitly (idempotent; the destructor closes too). The
    // result is only meaningful after close.
    void close();

private:
    ILayerTreeStack* stack_ = nullptr;
    std::int64_t token_ = -1;
    TreeUpdateResult result_;
};

// Composition snapshot input (the fields the controller needs from the
// host's layer facts; Python duck-types .id / .metadata / .template).
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
    explicit LayerGroupController(pwb::workspace::MappingWorkspaceState& state);

    // -- assembly ---------------------------------------------------------
    // Bind a stack (nullopt handling: a null stack = fully degraded,
    // mark_fallback is not needed). idempotent.
    void attach_stack(ILayerTreeStack* stack);
    ILayerTreeStack* stack() const { return stack_; }
    bool groups_available() const;
    bool degraded() const;  // fallback canvas OR old bridge
    // Group-mode hint for canvas publishing (mirror publish skips the
    // root flat order when groups drive structure).
    bool layer_groups_enabled() const;

    // Host notifications after a project state reload: re-read placement
    // tables and invalidate the incremental baseline.
    void reload_from_state();

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
    // V12 duplicate contract: place the copy right above its source when
    // the role is compatible; otherwise no override (home routing).
    std::string place_copy_adjacent(const std::string& source_id,
                                    const std::string& copy_id);

    // -- desired tree & reconcile -------------------------------------------
    pwb::workspace::LayerTreeSnapshot build_desired_tree(
        const std::vector<LayerSnapshotInput>& snapshots) const;
    // Apply the desired tree incrementally inside one transaction window
    // (zero intermediate canvas syncs; one closing sync). Throws on
    // apply failures (the baseline stays; the next reconcile retries —
    // V5 §78); a no-op with no stack / groups capability.
    void reconcile(const std::vector<LayerSnapshotInput>& snapshots,
                   bool force = false);
    // V11 D11-ws: rematerialize the empty system groups of the CURRENT
    // stage (minimal diff: empty-group creation only). Honest false when
    // there is no composition baseline yet; bridge throws must not break
    // the caller's stage switch.
    bool rematerialize_for_stage();

    const pwb::workspace::LayerTreeSnapshot* last_applied() const {
        return last_applied_ ? &*last_applied_ : nullptr;
    }
    // Echo staleness (semantic second line of defense beyond the
    // suppress guard): programmatic applies carry a revision; user
    // echoes with revision <= applied are stale.
    void note_applied_tree_revision(std::uint64_t revision);
    bool echo_is_stale(std::uint64_t revision) const;
    std::uint64_t applied_tree_revision() const {
        return applied_tree_revision_;
    }
    // True while a programmatic apply window is open (selection jumps
    // during reconcile are reorder noise, not user layer switches).
    bool reconciling() const { return reconciling_; }
    std::optional<std::string> last_degraded_reason() const {
        return last_degraded_reason_;
    }

    // -- group visibility (stage profile + user overlay) --------------------
    // Effective group visibility for the stage (profile defaults + user
    // overrides); full push, never "changed only" (drift rationale,
    // Python R6). Degraded: {} + persistent reason for the host to show.
    std::map<std::string, bool> apply_stage_visibility(MappingStage stage);
    // Programmatic group visibility (recorded to the current stage view
    // state).
    void set_group_visible(const std::string& group_id, bool visible,
                           bool record = true);
    // Restore expand states (UI preference side; defaults every system
    // group + base to expanded).
    void apply_group_expanded(const std::map<std::string, bool>& expanded);
    std::map<std::string, std::map<std::string, bool>> expand_states;

    // -- user group management ------------------------------------------------
    // Create a user group (parent must be a user group or root; system /
    // factor groups cannot host user subgroups — invalid parents fall
    // back to root, never throws). Returns the new group id.
    std::string create_user_group(const std::string& name,
                                  const std::string& parent_group_id = "");
    void rename_user_group(const std::string& group_id, const std::string& name);
    // Remove a user group; child layers and nested user groups hoist one
    // level up (never deletes layers or group contents).
    void remove_user_group(const std::string& group_id);

    // -- user tree event write-back --------------------------------------------
    // Structural change (drag / create group / remove group) observed
    // from the tree. Returns true when accepted; false when an illegal
    // placement existed (role routing conflict — the desired tree stays,
    // the next reconcile pulls the QGIS tree back; the (layer, group)
    // pair is reported through on_invalid_move). The observed order
    // becomes stable order keys (LIS keep + midpoint inserts).
    bool observe_tree_nodes(const pwb::domain::Json& nodes);
    bool last_observe_rejected = false;
    std::function<void()> on_structure_changed;
    std::function<void(const std::string&, const std::string&)> on_invalid_move;

    // User gesture recorders (ONLY from user echo entry points —
    // programmatic stage pushes must never freeze defaults into
    // overrides).
    void record_group_visibility_event(const std::string& group_id,
                                       bool visible);
    void record_layer_visibility_event(const std::string& layer_id,
                                       bool visible);
    void record_layer_opacity_event(const std::string& layer_id,
                                    double opacity);

    // -- queries ------------------------------------------------------------------
    // Home group of a layer (runtime placement table -> membership
    // routing fallback; valid while degraded too).
    std::string placement_of(const std::string& layer_id) const;
    const std::map<std::string, std::string>& order_keys() const {
        return order_keys_;
    }
    // factor task titles (host syncs from the project document).
    std::map<std::string, std::string> factor_titles;

private:
    void load_placements_from_state();
    void collect_group(const pwb::workspace::TreeNode& group,
                       const std::string& group_id);
    void collect_keys(const pwb::workspace::LayerTreeSnapshot& snapshot);
    void apply_tree(const pwb::workspace::LayerTreeSnapshot& desired,
                    bool force);
    std::map<std::string, PlanUserGroup> plan_user_groups() const;

    pwb::workspace::MappingWorkspaceState& state_;
    ILayerTreeStack* stack_ = nullptr;
    bool fallback_canvas_ = false;
    std::optional<pwb::workspace::LayerTreeSnapshot> last_applied_;
    std::map<std::string, bool> last_group_visibility_;
    std::map<std::string, std::string> placements_;   // layer -> group ("" root)
    std::map<std::string, std::vector<std::string>> group_orders_;
    std::vector<std::string> root_order_;
    std::map<std::string, std::string> order_keys_;   // node -> key
    std::map<std::string, pwb::workspace::TreeNode> user_groups_;
    // Persisted expand flags (group -> expanded) from the state tree;
    // restore defaults for apply_group_expanded.
    std::map<std::string, bool> persisted_expanded_;
    std::uint64_t applied_tree_revision_ = 0;
    bool reconciling_ = false;
    std::optional<std::string> last_degraded_reason_;
    std::vector<LayerSnapshotInput> last_snapshots_;
};

}  // namespace pwb::ui_composite
