// V14 layer group controller — port of layer_group_controller.py (see
// layer_group_controller.hpp).
#include "pwb/ui_composite/layer_group_controller.hpp"

#include "pwb/ui_composite/layer_groups.hpp"
#include "pwb/ui_composite/stage_profiles.hpp"
#include "pwb/workspace/layer_order.hpp"
#include "pwb/workspace/layer_tree_diff.hpp"
#include "pwb/workspace/mutations.hpp"
#include "pwb/workspace/state_ops.hpp"

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <functional>
#include <set>
#include <stdexcept>

namespace pwb::ui_composite {

namespace {

using pwb::workspace::LayerTreeSnapshot;
using pwb::workspace::TreeNode;

std::string node_key(const TreeNode& node) {
    return node.order_key;
}

}  // namespace

// -- TreeTransactionWindow --------------------------------------------------

TreeTransactionWindow::TreeTransactionWindow(ILayerTreeStack& stack) {
    const std::optional<std::int64_t> token = stack.begin_tree_update();
    if (token.has_value()) {
        stack_ = &stack;
        token_ = *token;
    } else {
        token_ = -1;  // degraded: per-call semantics, behavior unchanged
    }
}

TreeTransactionWindow::~TreeTransactionWindow() {
    close();
}

void TreeTransactionWindow::close() {
    if (stack_ != nullptr && token_ >= 0) {
        // Always closes (including after an in-window exception): applied
        // changes stay; partial failure is reconciled by the host via
        // revision/diff. The closing result must not mask the original
        // exception (R2-P2).
        try {
            result_ = stack_->end_tree_update(token_);
        } catch (...) {
        }
        stack_ = nullptr;
        token_ = -1;
    }
}

TreeTransactionWindow::TreeTransactionWindow(
    TreeTransactionWindow&& other) noexcept
    : stack_(other.stack_), token_(other.token_), result_(other.result_) {
    other.stack_ = nullptr;
    other.token_ = -1;
}

TreeTransactionWindow& TreeTransactionWindow::operator=(
    TreeTransactionWindow&& other) noexcept {
    if (this != &other) {
        close();  // an open window is never silently dropped (Round-2 P3-2)
        stack_ = other.stack_;
        token_ = other.token_;
        result_ = other.result_;
        other.stack_ = nullptr;
        other.token_ = -1;
    }
    return *this;
}

// -- LayerGroupController ----------------------------------------------------

LayerGroupController::LayerGroupController(
    pwb::workspace::MappingWorkspaceState& state)
    : state_(state) {
    load_placements_from_state();
}

bool LayerGroupController::groups_available() const {
    return stack_ != nullptr && stack_->groups_available();
}

bool LayerGroupController::degraded() const {
    if (fallback_canvas_) return true;
    return stack_ != nullptr && !stack_->groups_available();
}

bool LayerGroupController::layer_groups_enabled() const {
    return groups_available();
}

void LayerGroupController::attach_stack(ILayerTreeStack* stack) {
    stack_ = stack;
    if (stack_ == nullptr) {
        fallback_canvas_ = true;  // fully degraded canvas (no native stack)
        return;
    }
    fallback_canvas_ = false;
}

void LayerGroupController::reload_from_state() {
    load_placements_from_state();
    last_applied_.reset();
    last_group_visibility_.clear();
}

void LayerGroupController::load_placements_from_state() {
    placements_.clear();
    group_orders_.clear();
    root_order_.clear();
    order_keys_.clear();
    user_groups_.clear();
    persisted_expanded_.clear();
    if (!state_.tree.is_object() || state_.tree.empty()) return;
    LayerTreeSnapshot snapshot = LayerTreeSnapshot::from_json(state_.tree);
    // Persisted expand flags (per-group, stage-agnostic in the tree
    // carrier) become the restore defaults for apply_group_expanded —
    // without them every reopen resets collapsed groups (Round-2 P2-3).
    for (const TreeNode* group : snapshot.iter_groups()) {
        persisted_expanded_[group->group_id] = group->expanded;
    }
    for (const TreeNode& child : snapshot.children) {
        if (!child.is_group) {
            placements_[child.layer_id] = "";
            root_order_.push_back(child.layer_id);
        } else {
            if (child.kind == "user") {
                user_groups_[child.group_id] = child;
            }
            collect_group(child, child.group_id);
        }
    }
    collect_keys(snapshot);
}

void LayerGroupController::collect_keys(
    const LayerTreeSnapshot& snapshot) {
    // All node keys in the snapshot (layer/group shared namespace).
    std::function<void(const std::vector<TreeNode>&)> walk =
        [&](const std::vector<TreeNode>& children) {
            for (const TreeNode& child : children) {
                if (!child.order_key.empty()) {
                    order_keys_[child.is_group ? child.group_id
                                               : child.layer_id] =
                        child.order_key;
                }
                if (child.is_group) walk(child.children);
            }
        };
    walk(snapshot.children);
}

void LayerGroupController::collect_group(const TreeNode& group,
                                         const std::string& group_id) {
    std::vector<std::string> order;
    for (const TreeNode& child : group.children) {
        if (!child.is_group) {
            placements_[child.layer_id] = group_id;
            order.push_back(child.layer_id);
        } else {
            // V11: nested user groups join the parent's mixed child order
            // (system/factor groups never nest).
            if (child.kind == "user") {
                user_groups_[child.group_id] = child;
                order.push_back(child.group_id);
            }
            collect_group(child, child.group_id);
        }
    }
    group_orders_[group_id] = std::move(order);
}

// -- membership & migration ----------------------------------------------------

std::vector<std::string> LayerGroupController::ensure_memberships(
    const std::vector<LayerSnapshotInput>& snapshots,
    bool full_composition) {
    std::vector<std::string> added;
    if (full_composition && !snapshots.empty()) {
        std::set<std::string> live_ids;
        for (const LayerSnapshotInput& layer : snapshots) {
            if (!layer.id.empty()) live_ids.insert(layer.id);
        }
        // Ghost cleanup targets only "real layers gone from the
        // composition" — descriptor-only members (factor grids /
        // uncertainty, non-composite analysis aids) must survive or their
        // registrations would be dropped on the next create_layer pass.
        std::vector<std::string> stale;
        for (const auto& [layer_id, record] : state_.memberships) {
            if (layer_id.empty() || live_ids.count(layer_id) != 0) continue;
            if (record.role == "factor_grid" ||
                record.role == "factor_uncertainty") {
                continue;
            }
            if (record.role == "analysis_aid" &&
                layer_id.rfind("composite:", 0) != 0) {
                continue;
            }
            stale.push_back(layer_id);
        }
        for (const std::string& layer_id : stale) {
            pwb::workspace::drop_membership(state_, layer_id);
            placements_.erase(layer_id);
            order_keys_.erase(layer_id);
            root_order_.erase(std::remove(root_order_.begin(),
                                          root_order_.end(), layer_id),
                              root_order_.end());
            for (auto& [gid, order] : group_orders_) {
                (void)gid;
                order.erase(std::remove(order.begin(), order.end(), layer_id),
                            order.end());
            }
        }
    }
    for (const LayerSnapshotInput& layer : snapshots) {
        if (layer.id.empty() ||
            pwb::workspace::membership(state_, layer.id) != nullptr) {
            continue;
        }
        const LayerClassification classified =
            classify_layer_for_migration(layer.id, layer.metadata,
                                         layer.template_key,
                                         layer.geometry_type);
        pwb::workspace::LayerBinding binding;
        binding.layer_id = layer.id;
        binding.role = classified.role;
        binding.constraint_kind = classified.constraint_kind;
        binding.created_stage = state_.current_stage;
        pwb::workspace::set_membership(state_, std::move(binding));
        added.push_back(layer.id);
    }
    return added;
}

void LayerGroupController::register_layer(
    const std::string& layer_id, const std::string& role,
    const std::string& factor_task_id, const std::string& constraint_kind,
    const std::string& source_version_id, const std::string& source_asset_id,
    const std::string& binding_kind, const std::string& bound_at) {
    // V13 W-I: a pinned version without an explicit kind defaults to
    // catalog_version (the pre-V13 writer's only meaning); constraint
    // layers pass content_fingerprint explicitly.
    std::string kind = binding_kind;
    if (!source_version_id.empty() && kind.empty()) {
        kind = std::string(pwb::workspace::kBindingCatalogVersion);
    }
    const pwb::workspace::LayerBinding* existing =
        pwb::workspace::membership(state_, layer_id);
    pwb::workspace::LayerBinding binding;
    binding.layer_id = layer_id;
    binding.role = role;
    binding.factor_task_id = factor_task_id;
    binding.constraint_kind = constraint_kind;
    binding.created_stage =
        existing != nullptr && !existing->created_stage.empty()
            ? existing->created_stage
            : state_.current_stage;
    binding.source_version_id = source_version_id;
    binding.created_at =
        existing != nullptr ? existing->created_at : std::string();
    binding.source_asset_id = source_asset_id;
    binding.binding_kind = kind;
    binding.bound_at = bound_at;
    pwb::workspace::set_layer_binding(state_, std::move(binding));
    // New layers go straight to their home group (an unobserved old
    // placement is not resurrected).
    placements_.erase(layer_id);
}

void LayerGroupController::unregister_layer(const std::string& layer_id) {
    pwb::workspace::drop_membership(state_, layer_id);
    placements_.erase(layer_id);
    root_order_.erase(
        std::remove(root_order_.begin(), root_order_.end(), layer_id),
        root_order_.end());
    for (auto& [gid, order] : group_orders_) {
        (void)gid;
        order.erase(std::remove(order.begin(), order.end(), layer_id),
                    order.end());
    }
}

std::string LayerGroupController::place_copy_adjacent(
    const std::string& source_id, const std::string& copy_id) {
    if (copy_id.empty() || copy_id == source_id) return "";
    std::string container;
    int position = -1;
    for (const auto& [gid, order] : group_orders_) {
        if (std::find(order.begin(), order.end(), source_id) != order.end() &&
            std::find(order.begin(), order.end(), copy_id) == order.end()) {
            container = gid;
            position = static_cast<int>(
                           std::find(order.begin(), order.end(), source_id) -
                           order.begin()) +
                       1;
            break;
        }
    }
    if (position < 0 &&
        std::find(root_order_.begin(), root_order_.end(), source_id) !=
            root_order_.end() &&
        std::find(root_order_.begin(), root_order_.end(), copy_id) ==
            root_order_.end()) {
        container = "";
        position = static_cast<int>(
                       std::find(root_order_.begin(), root_order_.end(),
                                 source_id) -
                       root_order_.begin()) +
                   1;
    }
    if (position < 0) return "";
    const pwb::workspace::LayerBinding* record =
        pwb::workspace::membership(state_, copy_id);
    const std::string copy_role =
        record != nullptr ? record->role : std::string();
    // Role-incompatible (e.g. a draft into the prediction group): do not
    // force it — home routing wins; forcing would be pulled back by the
    // next observe/reconcile cycle and flicker.
    if (!container.empty() && !movable_into_system_group(copy_role, container)) {
        return "";
    }
    placements_[copy_id] = container;
    if (!container.empty()) {
        auto& order = group_orders_[container];
        order.insert(order.begin() + position, copy_id);
    } else {
        root_order_.insert(root_order_.begin() + position, copy_id);
    }
    return container;
}

// -- desired tree & reconcile ------------------------------------------------------

LayerTreeSnapshot LayerGroupController::build_desired_tree(
    const std::vector<LayerSnapshotInput>& snapshots) const {
    LayerTreePlanInput plan_input;
    plan_input.stage = tool_policy::stage_from_value(state_.current_stage);
    for (std::size_t sub_order = 0; sub_order < snapshots.size(); ++sub_order) {
        const LayerSnapshotInput& layer = snapshots[sub_order];
        if (layer.id.empty()) continue;
        const pwb::workspace::LayerBinding* record =
            pwb::workspace::membership(state_, layer.id);
        PlanLayerRecord plan_record;
        plan_record.layer_id = layer.id;
        if (record != nullptr) {
            plan_record.role = record->role;
            plan_record.factor_task_id = record->factor_task_id;
            plan_record.constraint_kind = record->constraint_kind;
            plan_record.created_stage = record->created_stage;
        } else {
            plan_record.created_stage = state_.current_stage;
        }
        plan_record.sub_order = static_cast<long long>(sub_order);
        plan_input.records.push_back(std::move(plan_record));
    }
    plan_input.user_placements = placements_;
    plan_input.container_orders = group_orders_;
    plan_input.container_orders[""] = root_order_;
    plan_input.user_groups = plan_user_groups();
    plan_input.order_keys = order_keys_;
    plan_input.factor_titles = factor_titles;
    auto [snapshot, facts] = build_plan(plan_input);
    (void)facts;
    return snapshot;
}

void LayerGroupController::reconcile(
    const std::vector<LayerSnapshotInput>& snapshots, bool force) {
    if (stack_ == nullptr || !groups_available()) return;
    last_snapshots_ = snapshots;
    LayerTreeSnapshot desired = build_desired_tree(snapshots);
    // Failures must never be swallowed: keep last_applied unchanged,
    // retry on the next reconcile (V5 §78). The C++ port throws; the
    // host catches. The window closes exactly once in every path.
    TreeTransactionWindow window(*stack_);
    reconciling_ = true;
    struct ResetFlag {
        bool& flag;
        ~ResetFlag() { flag = false; }
    } reset{reconciling_};
    apply_tree(desired, force);
    reset.flag = false;  // explicit: reconcile() completes below
    window.close();
    const std::uint64_t revision = window.result().revision;
    if (revision > 0) note_applied_tree_revision(revision);
    last_applied_ = desired;
    state_.tree = desired.to_json();
}

bool LayerGroupController::rematerialize_for_stage() {
    if (stack_ == nullptr || !groups_available()) return false;
    if (last_snapshots_.empty()) return false;
    // Prune by live memberships (deleted layers never resurrect); the
    // caller (set_stage) must guard — bridge throws must not break the
    // stage switch.
    std::set<std::string> live_ids;
    for (const auto& entry : state_.memberships) {
        live_ids.insert(entry.first);
    }
    std::vector<LayerSnapshotInput> pruned;
    for (const LayerSnapshotInput& layer : last_snapshots_) {
        if (live_ids.count(layer.id) != 0) pruned.push_back(layer);
    }
    reconcile(pruned.empty() ? last_snapshots_ : pruned);
    return true;
}

void LayerGroupController::note_applied_tree_revision(std::uint64_t revision) {
    if (revision > applied_tree_revision_) {
        applied_tree_revision_ = revision;
    }
}

bool LayerGroupController::echo_is_stale(std::uint64_t revision) const {
    // Semantic echo suppression beyond the guard flag: programmatic
    // applies carry revisions; user echoes at or below the applied
    // revision are stale (02-authority-model invariant 3). 0 = old
    // bridge without revisions -> never stale.
    if (revision == 0 || applied_tree_revision_ == 0) return false;
    return revision <= applied_tree_revision_;
}

void LayerGroupController::apply_tree(const LayerTreeSnapshot& desired,
                                      bool force) {
    const LayerTreeSnapshot empty_tree;
    const LayerTreeSnapshot& current =
        (last_applied_.has_value() && !force) ? *last_applied_ : empty_tree;
    const pwb::workspace::TreeDiff tree_diff =
        pwb::workspace::diff_trees(current, desired);

    // 1) Group creation (topological: parents first) + renames.
    for (const auto& op : tree_diff.group_creates) {
        stack_->upsert_group(op.group_id, op.name, op.parent);
    }
    for (const auto& op : tree_diff.group_renames) {
        stack_->rename_group(op.group_id, op.new_name);
    }

    // 2) Keep-set cleanup (idempotent self-heal; children hoist).
    std::vector<std::string> keep_ids;
    {
        std::set<std::string> keep;
        for (const TreeNode* group : desired.iter_groups()) {
            keep.insert(group->group_id);
        }
        keep_ids.assign(keep.begin(), keep.end());
    }
    stack_->remove_groups_except(keep_ids);

    // 3) Placements: the diff's move set (batched, O(changed)).
    // R2-P0: skipped > 0 must abort — otherwise last_applied would claim
    // success and later diffs would stay blind to the skipped moves
    // (silent drift, only recoverable via force).
    if (!tree_diff.group_moves.empty() || !tree_diff.layer_moves.empty()) {
        std::vector<PlacementOp> placements;
        for (const auto& op : tree_diff.group_moves) {
            placements.push_back(
                PlacementOp{"group:" + op.group_id, op.new_parent,
                            op.new_index});
        }
        for (const auto& op : tree_diff.layer_moves) {
            placements.push_back(
                PlacementOp{op.layer_id, op.new_parent, op.new_index});
        }
        const PlacementReport report = stack_->apply_tree_placements(placements);
        if (report.skipped > 0) {
            throw std::runtime_error(
                "apply_tree_placements skipped " +
                std::to_string(report.skipped) + " of " +
                std::to_string(placements.size()) +
                " placements — reconcile aborted, baseline unchanged "
                "(retry will re-diff)");
        }
    }

    // 4) Runtime placement tables + order keys (the desired tree is the
    //    single source of truth).
    placements_.clear();
    group_orders_.clear();
    root_order_.clear();
    for (const TreeNode& child : desired.children) {
        if (!child.is_group) {
            placements_[child.layer_id] = "";
            root_order_.push_back(child.layer_id);
        } else {
            if (child.kind == "user") {
                user_groups_[child.group_id] = child;
            }
            collect_group(child, child.group_id);
        }
    }
    order_keys_.clear();
    collect_keys(desired);
}

// -- group visibility -----------------------------------------------------------

std::map<std::string, bool> LayerGroupController::apply_stage_visibility(
    MappingStage stage) {
    if (stack_ == nullptr || !groups_available()) {
        last_degraded_reason_ =
            stack_ == nullptr ? "无 QGIS 桥" : "桥无 group API（旧桥）";
        return {};
    }
    last_degraded_reason_.reset();
    const StageProfile& profile = stage_profile(stage);
    pwb::workspace::StageViewState& view =
        pwb::workspace::view_state(state_,
                                   tool_policy::stage_value(stage));
    const std::map<std::string, bool> effective =
        pwb::workspace::effective_group_visibility(
            view, profile.group_visibility);
    // Lock semantics: evidence groups default-locked in locked stages
    // (user may unlock).
    for (const std::string& group_id : profile.locked_groups) {
        if (system_group_template(group_id) != nullptr) {
            auto locked = view.group_locked.find(group_id);
            if (locked == view.group_locked.end() ||
                !locked->second.has_value()) {
                view.group_locked[group_id] = true;
            }
        }
    }
    for (const auto& [group_id, visible] : effective) {
        // Full push, never "changed only": last_group_visibility drifts
        // from the real QGIS state (groups rebuilt by remove_groups_except
        // / reconcile resets / direct tree edits that never flowed back);
        // after drift a changed-only push would freeze the wrong
        // visibility forever. Group counts are single digits and the
        // setter is cheap — full push buys permanent consistency.
        try {
            stack_->set_group_visibility(group_id, visible);
            last_group_visibility_[group_id] = visible;
        } catch (const std::exception&) {
            // host logs; visibility continues for the remaining groups
        }
    }
    return effective;
}

void LayerGroupController::set_group_visible(const std::string& group_id,
                                             bool visible, bool record) {
    if (stack_ != nullptr && groups_available()) {
        try {
            stack_->set_group_visibility(group_id, visible);
            last_group_visibility_[group_id] = visible;
        } catch (const std::exception&) {
        }
    }
    if (record) {
        pwb::workspace::record_group_visibility(
            pwb::workspace::view_state(state_, state_.current_stage),
            group_id, visible);
    }
}

void LayerGroupController::apply_group_expanded(
    const std::map<std::string, bool>& expanded) {
    if (stack_ == nullptr || !groups_available()) return;
    // Layered defaults: explicit stage map > persisted tree flags >
    // expanded-everywhere. The persisted layer is what keeps a user's
    // collapsed groups collapsed across reopen (Round-2 P2-3).
    std::map<std::string, bool> effective = persisted_expanded_;
    for (const auto& entry : expanded) {
        effective[entry.first] = entry.second;  // explicit entries win
    }
    if (effective.count(kBaseReferenceGroupId) == 0) {
        effective[kBaseReferenceGroupId] = true;
    }
    for (const GroupTemplate& template_def : system_group_templates()) {
        if (effective.count(template_def.group_id) == 0) {
            effective[template_def.group_id] = true;
        }
    }
    for (const auto& [node_id, is_open] : effective) {
        try {
            stack_->set_group_expanded(node_id, is_open);
            persisted_expanded_[node_id] = is_open;
        } catch (const std::exception&) {
        }
    }
}

// -- user groups -----------------------------------------------------------------

std::string LayerGroupController::create_user_group(
    const std::string& name, const std::string& parent_group_id) {
    std::string parent = parent_group_id;
    if (!parent.empty() &&
        (parent.rfind("phase", 0) == 0 || parent.rfind("factor", 0) == 0 ||
         system_group_template(parent) != nullptr ||
         user_groups_.count(parent) == 0)) {
        parent = "";  // conservative fallback: create at root
    }
    const auto now = std::chrono::system_clock::now().time_since_epoch();
    const std::uint64_t ms =
        std::chrono::duration_cast<std::chrono::milliseconds>(now).count();
    char suffix[16];
    std::snprintf(suffix, sizeof(suffix), "%08llx",
                  static_cast<unsigned long long>(ms & 0xffffffffu));
    const std::string group_id = std::string("user.") + suffix;
    TreeNode node = TreeNode::group(group_id,
                                    name.empty() ? std::string("新建组")
                                                 : name,
                                    "user");
    user_groups_[group_id] = std::move(node);
    if (!parent.empty()) {
        group_orders_[parent].push_back(group_id);
    } else {
        root_order_.push_back(group_id);
    }
    return group_id;
}

void LayerGroupController::rename_user_group(const std::string& group_id,
                                             const std::string& name) {
    auto it = user_groups_.find(group_id);
    if (it == user_groups_.end()) return;
    it->second.name = name;
    if (stack_ != nullptr && groups_available()) {
        try {
            stack_->rename_group(group_id, name);
        } catch (const std::exception&) {
        }
    }
}

void LayerGroupController::remove_user_group(const std::string& group_id) {
    if (user_groups_.erase(group_id) == 0) return;
    // Find the parent container (root or a nested parent group).
    std::string parent_id;
    for (const auto& [gid, order] : group_orders_) {
        if (std::find(order.begin(), order.end(), group_id) != order.end()) {
            parent_id = gid;
            break;
        }
    }
    std::vector<std::string> moved = group_orders_.count(group_id) != 0
                                         ? group_orders_[group_id]
                                         : std::vector<std::string>{};
    group_orders_.erase(group_id);
    std::vector<std::string>* target_order =
        parent_id.empty() ? &root_order_
                          : &group_orders_.emplace(parent_id,
                                                   std::vector<std::string>{})
                                 .first->second;
    auto insert_it = std::find(target_order->begin(), target_order->end(),
                               group_id);
    std::size_t insert_at =
        insert_it == target_order->end() ? target_order->size()
                                         : static_cast<std::size_t>(
                                               insert_it - target_order->begin());
    target_order->insert(target_order->begin() +
                             static_cast<std::ptrdiff_t>(insert_at),
                         moved.begin(), moved.end());
    for (const std::string& node_id : moved) {
        if (user_groups_.count(node_id) != 0) {
            continue;  // nested user groups hoist wholesale (members move with them)
        }
        placements_[node_id] = parent_id;
    }
    order_keys_.erase(group_id);
    for (auto& [gid, order] : group_orders_) {
        (void)gid;
        order.erase(std::remove(order.begin(), order.end(), group_id),
                    order.end());
    }
    root_order_.erase(
        std::remove(root_order_.begin(), root_order_.end(), group_id),
        root_order_.end());
}

// -- user tree event write-back ----------------------------------------------------

bool LayerGroupController::observe_tree_nodes(const pwb::domain::Json& nodes) {
    LayerTreeSnapshot observed = pwb::workspace::tree_from_nodes(nodes);
    std::set<std::string> system_ids;
    for (const GroupTemplate& template_def : system_group_templates()) {
        system_ids.insert(template_def.group_id);
    }
    // User-group discovery: observed groups outside the system templates
    // and factor namespace. Collect first, commit only when everything
    // validates (no ghost groups on rejection).
    std::map<std::string, TreeNode> discovered_user_groups;
    for (const TreeNode* group : observed.iter_groups()) {
        const std::string& gid = group->group_id;
        if (!gid.empty() && system_ids.count(gid) == 0 &&
            gid.rfind("factor.", 0) != 0 && user_groups_.count(gid) == 0) {
            TreeNode node = TreeNode::group(
                gid, group->name.empty() ? gid : group->name, "user");
            discovered_user_groups[gid] = std::move(node);
        }
    }
    std::optional<std::pair<std::string, std::string>> rejected_with;
    std::map<std::string, std::string> placements;
    std::map<std::string, std::vector<std::string>> orders;
    std::vector<std::string> root_order;

    std::function<void(const std::vector<TreeNode>&, const std::string&)>
        walk = [&](const std::vector<TreeNode>& children,
                   const std::string& parent_id) {
            for (const TreeNode& child : children) {
                if (child.is_group) {
                    // R2-P2: user groups dragged into system groups are
                    // illegal (the nesting create_user_group refuses must
                    // not be reachable via drag either) — report the pair.
                    if (!parent_id.empty() &&
                        system_ids.count(parent_id) != 0) {
                        if (!rejected_with.has_value()) {
                            rejected_with = {child.group_id, parent_id};
                        }
                        continue;
                    }
                    if (!parent_id.empty()) {
                        orders[parent_id].push_back(child.group_id);
                    } else {
                        root_order.push_back(child.group_id);
                    }
                    walk(child.children, child.group_id);
                } else {
                    const pwb::workspace::LayerBinding* record =
                        pwb::workspace::membership(state_, child.layer_id);
                    if (!parent_id.empty() &&
                        system_ids.count(parent_id) != 0 &&
                        record != nullptr &&
                        !movable_into_system_group(record->role, parent_id)) {
                        if (!rejected_with.has_value()) {
                            rejected_with = {child.layer_id, parent_id};
                        }
                        continue;
                    }
                    placements[child.layer_id] = parent_id;
                    if (!parent_id.empty()) {
                        orders[parent_id].push_back(child.layer_id);
                    } else {
                        root_order.push_back(child.layer_id);
                    }
                }
            }
        };
    walk(observed.children, std::string());
    if (rejected_with.has_value()) {
        last_observe_rejected = true;
        if (on_invalid_move) {
            try {
                on_invalid_move(rejected_with->first, rejected_with->second);
            } catch (...) {
            }
        }
        return false;
    }
    last_observe_rejected = false;
    for (auto& [gid, node] : discovered_user_groups) {
        user_groups_[gid] = std::move(node);
    }
    placements_ = std::move(placements);
    group_orders_ = std::move(orders);
    root_order_ = std::move(root_order);
    // Observed order -> keys (nested user-group mixed orders included;
    // minimal disturbance — one drag re-keys the fewest nodes).
    {
        std::map<std::string, std::string> assigned =
            pwb::workspace::assign_keys_for_order(root_order_, &order_keys_);
        for (const auto& entry : assigned) {
            order_keys_[entry.first] = entry.second;
        }
    }
    for (const auto& [gid, order] : group_orders_) {
        std::map<std::string, std::string> assigned =
            pwb::workspace::assign_keys_for_order(order, &order_keys_);
        for (const auto& entry : assigned) {
            order_keys_[entry.first] = entry.second;
        }
    }
    if (on_structure_changed) {
        try {
            on_structure_changed();
        } catch (...) {
        }
    }
    return true;
}

void LayerGroupController::record_group_visibility_event(
    const std::string& group_id, bool visible) {
    last_group_visibility_[group_id] = visible;
    pwb::workspace::record_group_visibility(
        pwb::workspace::view_state(state_, state_.current_stage), group_id,
        visible);
}

void LayerGroupController::record_layer_visibility_event(
    const std::string& layer_id, bool visible) {
    pwb::workspace::record_layer_visibility(
        pwb::workspace::view_state(state_, state_.current_stage), layer_id,
        visible);
}

void LayerGroupController::record_layer_opacity_event(
    const std::string& layer_id, double opacity) {
    pwb::workspace::record_layer_opacity(
        pwb::workspace::view_state(state_, state_.current_stage), layer_id,
        opacity);
}

// -- queries -------------------------------------------------------------------------

std::string LayerGroupController::placement_of(
    const std::string& layer_id) const {
    auto it = placements_.find(layer_id);
    if (it != placements_.end()) return it->second;
    // Unified routing (V11: QC/aid by creation-stage aux routing) — tree
    // building, presentation and edit gating share one source (D1-ws);
    // valid while degraded too.
    const pwb::workspace::LayerBinding* record =
        pwb::workspace::membership(state_, layer_id);
    if (record == nullptr) return std::string(kLegacyGroupId);
    return effective_home_group(record->role, record->created_stage,
                                record->factor_task_id);
}

std::map<std::string, PlanUserGroup>
LayerGroupController::plan_user_groups() const {
    // Flat registry with parent pointers derived from the mixed child
    // orders (_group_orders / _root_order) — user_groups itself is flat;
    // nesting lives only in the order tables.
    std::map<std::string, std::string> parent_of;
    for (const auto& [gid, order] : group_orders_) {
        for (const std::string& node_id : order) {
            if (user_groups_.count(node_id) != 0) {
                parent_of[node_id] = gid;
            }
        }
    }
    for (const std::string& node_id : root_order_) {
        if (user_groups_.count(node_id) != 0) {
            parent_of[node_id] = "";
        }
    }
    std::map<std::string, PlanUserGroup> out;
    for (const auto& [gid, group] : user_groups_) {
        PlanUserGroup plan_group;
        plan_group.group_id = gid;
        plan_group.name = group.name;
        auto parent = parent_of.find(gid);
        plan_group.parent_group_id =
            parent == parent_of.end() ? std::string() : parent->second;
        out.emplace(gid, std::move(plan_group));
    }
    return out;
}

}  // namespace pwb::ui_composite
