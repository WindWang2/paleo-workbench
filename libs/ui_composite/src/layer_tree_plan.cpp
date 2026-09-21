// V14 layer tree plan — port of layer_tree_plan.py (see
// layer_tree_plan.hpp).
#include "pwb/ui_composite/layer_tree_plan.hpp"

#include "pwb/ui_composite/layer_groups.hpp"
#include "pwb/workspace/layer_order.hpp"

#include <algorithm>
#include <functional>
#include <set>

namespace pwb::ui_composite {

namespace {

using pwb::workspace::LayerTreeSnapshot;
using pwb::workspace::TreeNode;

// In-container default sort key as a TUPLE (band, sub_order, id) — never
// a decimal-string concatenation ("150/…" sorts before "20/…" and would
// invert the band order for mixed-digit bands).
pwb::workspace::BandSortKey default_layer_sort_key(
    const PlanLayerRecord& record, bool factor_container) {
    // factor containers: pipeline rank; others: role band; both
    // tie-broken by scientific sub-order then stable id (total order).
    if (factor_container) {
        return pwb::workspace::BandSortKey(
            pwb::workspace::factor_role_rank(record.role), record.sub_order,
            record.layer_id);
    }
    return pwb::workspace::band_sort_key(record.role, record.sub_order,
                                         record.layer_id);
}

// Final in-container order: observed order (live members) + new members
// merged by default scientific order. New-member merge side (V12 D9/R10):
// * system/factor containers -> TAIL (bottom). The role band order is
//   the container's invariant; putting new layers on top would let them
//   cross band order (e.g. a new basemap above integrated facies);
// * user containers / root -> top of the display. For user groups that
//   is the list HEAD; for the flat root list the domain convention is
//   "list tail = top of display" — fresh members append and still land
//   on top visually.
std::vector<std::string> merge_container_order(
    const std::vector<PlanLayerRecord>& members,
    const std::vector<std::string>* observed, bool factor_container,
    bool system_container) {
    std::map<std::string, const PlanLayerRecord*> by_id;
    for (const PlanLayerRecord& record : members) {
        by_id[record.layer_id] = &record;
    }
    std::vector<std::string> ordered;
    if (observed != nullptr && !observed->empty()) {
        std::set<std::string> seen;
        for (const std::string& node_id : *observed) {
            auto it = by_id.find(node_id);
            if (it != by_id.end() && seen.insert(node_id).second) {
                ordered.push_back(node_id);
            }
        }
        std::vector<const PlanLayerRecord*> fresh;
        for (const PlanLayerRecord& record : members) {
            if (seen.count(record.layer_id) == 0) fresh.push_back(&record);
        }
        std::sort(fresh.begin(), fresh.end(),
                  [factor_container](const PlanLayerRecord* a,
                                     const PlanLayerRecord* b) {
                      return default_layer_sort_key(*a, factor_container) <
                             default_layer_sort_key(*b, factor_container);
                  });
        std::vector<std::string> fresh_ids;
        fresh_ids.reserve(fresh.size());
        for (const PlanLayerRecord* record : fresh) {
            fresh_ids.push_back(record->layer_id);
        }
        if (system_container) {
            ordered.insert(ordered.end(), fresh_ids.begin(), fresh_ids.end());
        } else {
            ordered.insert(ordered.begin(), fresh_ids.begin(),
                           fresh_ids.end());
        }
        return ordered;
    }
    std::vector<const PlanLayerRecord*> sorted_members;
    sorted_members.reserve(members.size());
    for (const PlanLayerRecord& record : members) sorted_members.push_back(&record);
    std::sort(sorted_members.begin(), sorted_members.end(),
              [factor_container](const PlanLayerRecord* a,
                                 const PlanLayerRecord* b) {
                  return default_layer_sort_key(*a, factor_container) <
                         default_layer_sort_key(*b, factor_container);
              });
    for (const PlanLayerRecord* record : sorted_members) {
        ordered.push_back(record->layer_id);
    }
    return ordered;
}

}  // namespace

std::string effective_home_group(const std::string& role,
                                 const std::string& created_stage,
                                 const std::string& factor_task_id) {
    std::optional<MappingStage> stage;
    if (!created_stage.empty()) {
        stage = tool_policy::stage_from_value(created_stage);
    }
    return home_group_for_role(role, stage, factor_task_id);
}

std::pair<LayerTreeSnapshot, LayerTreePlanFacts> build_plan(
    const LayerTreePlanInput& plan_input) {
    const std::vector<GroupTemplate>& templates = system_group_templates();
    std::set<std::string> system_ids;
    std::map<std::string, std::size_t> template_index;
    for (std::size_t i = 0; i < templates.size(); ++i) {
        system_ids.insert(templates[i].group_id);
        template_index[templates[i].group_id] = i;
    }
    auto is_factor_id = [](const std::string& gid) {
        return gid.rfind("factor.", 0) == 0;
    };

    // 1) Member routing: user placement (when the container exists) ->
    //    creation-stage home -> root. Container existence only trusts the
    //    three authorities (system templates / user_groups registry /
    //    factor namespace) — container_orders is an order hint, not an
    //    existence proof; ghost keys never swallow layers.
    std::map<std::string, std::vector<PlanLayerRecord>> containers;
    std::vector<PlanLayerRecord> root_layers;
    for (const PlanLayerRecord& record : plan_input.records) {
        std::string placement;
        auto placed = plan_input.user_placements.find(record.layer_id);
        if (placed != plan_input.user_placements.end()) {
            placement = placed->second;
        } else {
            placement = effective_home_group(record.role, record.created_stage,
                                             record.factor_task_id);
        }
        bool known = placement.empty() || system_ids.count(placement) != 0 ||
                     plan_input.user_groups.count(placement) != 0 ||
                     is_factor_id(placement);
        if (!known) {
            placement = effective_home_group(record.role, record.created_stage,
                                             record.factor_task_id);
            known = system_ids.count(placement) != 0 || is_factor_id(placement);
        }
        if (placement.empty() || !known) {
            root_layers.push_back(record);
        } else {
            containers[placement].push_back(record);
        }
    }

    // 2) In-container orders + keys.
    std::map<std::string, std::string> keys = plan_input.order_keys;
    std::map<std::string, std::vector<std::string>> orders;
    for (const auto& [group_id, members] : containers) {
        const bool factor_container = is_factor_id(group_id);
        auto observed_it = plan_input.container_orders.find(group_id);
        const std::vector<std::string>* observed =
            observed_it == plan_input.container_orders.end()
                ? nullptr
                : &observed_it->second;
        std::vector<std::string> merged = merge_container_order(
            members, observed, factor_container,
            factor_container || system_ids.count(group_id) != 0);
        orders[group_id] = merged;
        std::map<std::string, std::string> assigned =
            pwb::workspace::assign_keys_for_order(merged, &keys);
        for (const auto& entry : assigned) keys[entry.first] = entry.second;
    }

    // Root loose layers (observed order first as well; fresh members
    // append — domain list tail renders on top).
    const std::vector<std::string>* root_observed = nullptr;
    auto root_observed_it = plan_input.container_orders.find("");
    if (root_observed_it != plan_input.container_orders.end()) {
        root_observed = &root_observed_it->second;
    }
    std::vector<std::string> root_ids =
        merge_container_order(root_layers, root_observed, false, true);
    {
        std::map<std::string, std::string> assigned =
            pwb::workspace::assign_keys_for_order(root_ids, &keys);
        for (const auto& entry : assigned) keys[entry.first] = entry.second;
    }

    // 3) Factor subgroups (union: current members + observed historical
    //    factor groups).
    std::set<std::string> factor_ids;
    for (const auto& entry : containers) {
        if (is_factor_id(entry.first)) factor_ids.insert(entry.first);
    }
    for (const auto& entry : plan_input.container_orders) {
        if (is_factor_id(entry.first)) factor_ids.insert(entry.first);
    }

    // 4) User group tree (nestable): child order = observed mixed order
    //    (nested groups + layers, keys assigned uniformly). Parent
    //    pointers are sanitized — self-loops / unknown parents / cycles
    //    fall back to root (no infinite recursion); observed mounting
    //    only accepts "members routed to this group + sanitized child
    //    groups" (no double-mounting, no ghosts).
    std::map<std::string, std::set<std::string>> member_of;
    for (const auto& [group_id, members] : containers) {
        if (plan_input.user_groups.count(group_id) != 0) {
            std::set<std::string> ids;
            for (const PlanLayerRecord& record : members) {
                ids.insert(record.layer_id);
            }
            member_of[group_id] = std::move(ids);
        }
    }
    std::map<std::string, std::string> safe_parents;
    for (const auto& [group_id, info] : plan_input.user_groups) {
        std::string parent = info.parent_group_id;
        if (parent == group_id ||
            plan_input.user_groups.count(parent) == 0) {
            // Self-loop / unknown parent (incl. system-group ids) ->
            // root; cycles are caught by the reachability pass below.
            parent.clear();
        }
        safe_parents[group_id] = parent;
    }
    std::map<std::string, std::vector<std::string>> user_children_of;
    for (const auto& [group_id, parent] : safe_parents) {
        if (parent != group_id) user_children_of[parent].push_back(group_id);
    }
    auto key_of = [&keys](const std::string& nid) {
        auto it = keys.find(nid);
        return it == keys.end() ? nid : it->second;
    };
    for (auto& [parent, children] : user_children_of) {
        (void)parent;
        std::sort(children.begin(), children.end(),
                  [&](const std::string& a, const std::string& b) {
                      return key_of(a) < key_of(b);
                  });
    }
    // Cyclic groups (unreachable from root) promote to root — the
    // structure survives, expandable, never disappears.
    std::set<std::string> reachable;
    std::vector<std::string> frontier = user_children_of.count("")
                                            ? user_children_of[""]
                                            : std::vector<std::string>{};
    while (!frontier.empty()) {
        const std::string node = frontier.back();
        frontier.pop_back();
        if (reachable.count(node) != 0) continue;
        reachable.insert(node);
        auto it = user_children_of.find(node);
        if (it != user_children_of.end()) {
            for (const std::string& child : it->second) {
                frontier.push_back(child);
            }
        }
    }
    std::vector<std::string> unreachable;
    for (const auto& [group_id, parent] : safe_parents) {
        (void)parent;
        if (reachable.count(group_id) == 0) unreachable.push_back(group_id);
    }
    std::sort(unreachable.begin(), unreachable.end());
    for (const std::string& group_id : unreachable) {
        // Promote to root AND remove from the old parent's child list —
        // leaving both mounts duplicates the group in the built tree
        // (duplicate ids poison diff_trees' index; Round-2 P2-4).
        auto old_parent_it = safe_parents.find(group_id);
        if (old_parent_it != safe_parents.end() &&
            !old_parent_it->second.empty()) {
            auto& old_siblings = user_children_of[old_parent_it->second];
            old_siblings.erase(std::remove(old_siblings.begin(),
                                           old_siblings.end(), group_id),
                               old_siblings.end());
        }
        user_children_of[""].push_back(group_id);
        safe_parents[group_id] = "";
    }
    if (user_children_of.count("") != 0) {
        std::sort(user_children_of[""].begin(), user_children_of[""].end(),
                  [&](const std::string& a, const std::string& b) {
                      return key_of(a) < key_of(b);
                  });
    }

    // Recursive user-group builder with a visiting set (cycle guard: the
    // cycle edge is not expanded, the group mounts empty).
    std::function<TreeNode(const std::string&, std::set<std::string>)>
        make_user_group = [&](const std::string& group_id,
                              std::set<std::string> visiting) -> TreeNode {
        const PlanUserGroup& info = plan_input.user_groups.at(group_id);
        if (visiting.count(group_id) != 0) {
            TreeNode node = TreeNode::group(group_id,
                                            info.name.empty() ? group_id
                                                              : info.name,
                                            "user");
            node.order_key = key_of(group_id);
            return node;
        }
        visiting.insert(group_id);
        auto observed_it = plan_input.container_orders.find(group_id);
        const std::vector<std::string>& observed =
            observed_it == plan_input.container_orders.end()
                ? std::vector<std::string>{}
                : observed_it->second;
        const std::set<std::string>* allowed = nullptr;
        auto member_it = member_of.find(group_id);
        if (member_it != member_of.end()) allowed = &member_it->second;
        std::set<std::string> placed;
        std::vector<TreeNode> children;
        for (const std::string& node_id : observed) {
            if (plan_input.user_groups.count(node_id) != 0) {
                auto parent_it = safe_parents.find(node_id);
                if (node_id != group_id && parent_it != safe_parents.end() &&
                    parent_it->second == group_id &&
                    placed.insert(node_id).second) {
                    children.push_back(
                        make_user_group(node_id, visiting));
                }
                // Not our child / self-loop -> dropped (never mounted,
                // no ghosts).
            } else if (allowed != nullptr &&
                       allowed->count(node_id) != 0 &&
                       placed.insert(node_id).second) {
                // Only members routed to this group mount here (layers
                // inside system groups / deleted ids never enter).
                children.push_back(TreeNode::layer(node_id, key_of(node_id)));
            }
        }
        // V12 D9/R10: unobserved NEW layers mount on top; then unobserved
        // nested groups in key order.
        auto order_it = orders.find(group_id);
        if (order_it != orders.end()) {
            std::vector<TreeNode> fresh;
            for (const std::string& layer_id : order_it->second) {
                if (placed.count(layer_id) == 0) {
                    fresh.push_back(
                        TreeNode::layer(layer_id, key_of(layer_id)));
                    placed.insert(layer_id);
                }
            }
            children.insert(children.begin(), fresh.begin(), fresh.end());
        }
        auto child_groups_it = user_children_of.find(group_id);
        if (child_groups_it != user_children_of.end()) {
            for (const std::string& child : child_groups_it->second) {
                if (placed.count(child) == 0) {
                    children.push_back(make_user_group(child, visiting));
                    placed.insert(child);
                }
            }
        }
        TreeNode node = TreeNode::group(
            group_id, info.name.empty() ? group_id : info.name, "user");
        node.children = std::move(children);
        node.order_key = key_of(group_id);
        return node;
    };

    std::function<TreeNode(const std::string&)> make_system_group =
        [&](const std::string& group_id) -> TreeNode {
        std::vector<TreeNode> children;
        if (group_id == kFactorRootGroupId) {
            for (const std::string& factor_id : factor_ids) {
                children.push_back(make_system_group(factor_id));
            }
        }
        auto order_it = orders.find(group_id);
        if (order_it != orders.end()) {
            for (const std::string& layer_id : order_it->second) {
                children.push_back(
                    TreeNode::layer(layer_id, key_of(layer_id)));
            }
        }
        const GroupTemplate* template_ptr = system_group_template(group_id);
        if (template_ptr != nullptr) {
            TreeNode node =
                TreeNode::group(group_id, template_ptr->title, "system");
            node.children = std::move(children);
            node.order_key = pwb::workspace::key_for_index(
                static_cast<long long>(template_index[group_id]));
            return node;
        }
        // factor.<task>: dynamic system group.
        const std::string task_id =
            factor_task_of_group(group_id).value_or("");
        std::string title = task_id;
        if (title.empty()) title = group_id;
        auto title_it = plan_input.factor_titles.find(task_id);
        if (title_it != plan_input.factor_titles.end() && !title_it->second.empty()) {
            title = title_it->second;
        }
        TreeNode node = TreeNode::group(group_id, title, "system");
        node.children = std::move(children);
        node.order_key = key_of(group_id);
        return node;
    };

    // 5) Root assembly: system groups (template order; empty groups only
    //    materialize for the current stage / base) -> root user groups +
    //    loose layers (uniform key order). System keys anchor the FULL
    //    template index (empty groups appearing/disappearing never moves
    //    other groups' keys).
    LayerTreeSnapshot snapshot;
    std::vector<std::string> materialized_empty;
    for (const GroupTemplate& template_def : templates) {
        TreeNode group = make_system_group(template_def.group_id);
        if (!group.children.empty()) {
            snapshot.children.push_back(std::move(group));
            continue;
        }
        if (template_def.group_id == kBaseReferenceGroupId ||
            (plan_input.stage.has_value() &&
             template_def.stage_visible(*plan_input.stage))) {
            materialized_empty.push_back(template_def.group_id);
            snapshot.children.push_back(std::move(group));
        }
    }

    std::vector<std::string> root_user_groups;
    if (user_children_of.count("") != 0) {
        root_user_groups = user_children_of[""];
    }
    std::sort(root_user_groups.begin(), root_user_groups.end(),
              [&](const std::string& a, const std::string& b) {
                  return key_of(a) < key_of(b);
              });
    std::set<std::string> root_id_set(root_ids.begin(), root_ids.end());
    std::set<std::string> root_user_set(root_user_groups.begin(),
                                        root_user_groups.end());
    std::vector<std::string> root_mixed;
    if (root_observed != nullptr) {
        for (const std::string& nid : *root_observed) {
            if (root_id_set.count(nid) != 0 ||
                root_user_set.count(nid) != 0) {
                root_mixed.push_back(nid);
            }
        }
    }
    for (const std::string& nid : root_ids) {
        if (std::find(root_mixed.begin(), root_mixed.end(), nid) ==
            root_mixed.end()) {
            root_mixed.push_back(nid);
        }
    }
    for (const std::string& nid : root_user_groups) {
        if (std::find(root_mixed.begin(), root_mixed.end(), nid) ==
            root_mixed.end()) {
            root_mixed.push_back(nid);
        }
    }
    {
        std::map<std::string, std::string> assigned =
            pwb::workspace::assign_keys_for_order(root_mixed, &keys);
        for (const auto& entry : assigned) keys[entry.first] = entry.second;
    }
    std::vector<std::string> by_key = root_mixed;
    std::sort(by_key.begin(), by_key.end(),
              [&](const std::string& a, const std::string& b) {
                  const std::string ka = key_of(a);
                  const std::string kb = key_of(b);
                  if (ka != kb) return ka < kb;
                  return a < b;
              });
    for (const std::string& nid : by_key) {
        if (root_user_set.count(nid) != 0) {
            snapshot.children.push_back(
                make_user_group(nid, std::set<std::string>{}));
        } else {
            snapshot.children.push_back(TreeNode::layer(nid, key_of(nid)));
        }
    }

    snapshot.source = "domain";
    LayerTreePlanFacts facts;
    for (const auto& entry : keys) {
        if (plan_input.order_keys.count(entry.first) != 0) {
            facts.override_keys[entry.first] = entry.second;
        } else {
            facts.default_keys[entry.first] = entry.second;
        }
    }
    for (const GroupTemplate& template_def : templates) {
        facts.group_kinds[template_def.group_id] = "system";
    }
    for (const std::string& factor_id : factor_ids) {
        facts.group_kinds[factor_id] = "factor";
    }
    for (const auto& entry : plan_input.user_groups) {
        facts.group_kinds[entry.first] = "user";
    }
    facts.materialized_empty_groups = materialized_empty;
    return {std::move(snapshot), std::move(facts)};
}

}  // namespace pwb::ui_composite
