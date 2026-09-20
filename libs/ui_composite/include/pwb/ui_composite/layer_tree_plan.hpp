// V14 LayerTreePlan — declarative construction of the desired tree.
// 1:1 port of
// paleo_workbench/mapping_workspace/layer_tree_plan.py (V11 design,
// docs/development/qgis-cartography-runtime-v11/03-layer-tree-plan.md).
//
// LayerTreeSnapshot (libs/workspace) stays the tree carrier; this module
// is the POLICY layer that produces the desired snapshot — inputs are
// memberships, user placements, observed orders and persisted order
// keys; outputs are the keyed desired tree plus plan facts.
// LayerGroupController::build_desired_tree is a thin wrapper over it.
//
// Ordering rules (04-ordering.md):
// * final in-container order = observed order (user-drag write-back) +
//   new members merged by default scientific order (factor containers
//   use FACTOR_CHILD_ORDER rank, others the role bands); first-seen
//   containers use the default scientific order directly;
// * order -> keys via workspace::assign_keys_for_order (LIS keeps keys,
//   midpoint inserts, never a full renumber);
// * system groups in template declaration order (keys = fixed index
//   keys over the FULL template set, so empty-group visibility never
//   shifts other groups' keys); factor groups sorted by task id; user
//   groups by persisted keys, nestable since V11.
//
// QC/aid role routing (D1-ws): the membership record's creation stage
// drives aux/qc routing — tree building, presentation and edit gating
// all share effective_home_group below. Qt-free.
#pragma once

#include "pwb/tool_policy/stages.hpp"
#include "pwb/workspace/layer_tree.hpp"

#include <map>
#include <optional>
#include <string>
#include <vector>

namespace pwb::ui_composite {

using tool_policy::MappingStage;

// A layer's plan input record (derived from membership + snapshot order).
struct PlanLayerRecord {
    std::string layer_id;
    std::string role;  // "" = unknown (routing falls back, never throws)
    std::string factor_task_id;
    std::string constraint_kind;
    // Creation stage value (e.g. "facies_calibration") — QC/aid aux
    // routing.
    std::string created_stage;
    // Scientific sub-order (stable tiebreak of the composition snapshot
    // position).
    long long sub_order = 0;
};

// User group (V11: nestable — parent is another user group or root).
struct PlanUserGroup {
    std::string group_id;
    std::string name;
    std::string parent_group_id;  // "" = root
};

struct LayerTreePlanInput {
    std::vector<PlanLayerRecord> records;
    // Current stage (only affects empty-group materialization, never
    // structure/order).
    std::optional<MappingStage> stage;
    // User placement overrides (layer_id -> group_id; "" = root).
    std::map<std::string, std::string> user_placements;
    // Observed orders (group_id ("" = root loose layers) -> position
    // sequence, including user-drag write-back).
    std::map<std::string, std::vector<std::string>> container_orders;
    // User group registry (with nesting parents).
    std::map<std::string, PlanUserGroup> user_groups;
    // Persisted order keys (node_id -> key).
    std::map<std::string, std::string> order_keys;
    std::map<std::string, std::string> factor_titles;
};

// Plan by-products: default keys (recomputable, droppable) vs override
// keys (user intent, must persist).
struct LayerTreePlanFacts {
    std::map<std::string, std::string> default_keys;
    std::map<std::string, std::string> override_keys;
    std::map<std::string, std::string> group_kinds;
    // Empty system groups materialized this round (current-stage-visible
    // / base.reference).
    std::vector<std::string> materialized_empty_groups;
};

// Unified home routing: QC/aid roles route by creation stage (record
// value), everything else by static home. Shared by tree building,
// presentation and edit gating (D1-ws: no stage-aware/stage-None fork).
std::string effective_home_group(const std::string& role,
                                 const std::string& created_stage = "",
                                 const std::string& factor_task_id = "");

// Build the desired tree + plan facts (pure, deterministic: same input
// -> same output).
std::pair<pwb::workspace::LayerTreeSnapshot, LayerTreePlanFacts>
build_plan(const LayerTreePlanInput& plan_input);

}  // namespace pwb::ui_composite
