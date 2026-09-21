// V14 tree diff — port of layer_tree_diff.py (see layer_tree_diff.hpp).
#include "pwb/workspace/layer_tree_diff.hpp"

#include <algorithm>
#include <map>
#include <set>

namespace pwb::workspace {

namespace {

// Patience LIS over an int sequence, returning chosen sequence indices.
std::vector<std::size_t> lis_chosen_positions(
    const std::vector<long long>& seq) {
    std::vector<long long> tails;
    std::vector<std::size_t> tails_pos;
    std::vector<std::int64_t> prev(seq.size(), -1);
    for (std::size_t idx = 0; idx < seq.size(); ++idx) {
        const long long value = seq[idx];
        auto pos_it = std::lower_bound(tails.begin(), tails.end(), value);
        const std::size_t pos = static_cast<std::size_t>(pos_it - tails.begin());
        if (pos == tails.size()) {
            tails.push_back(value);
            tails_pos.push_back(idx);
        } else {
            tails[pos] = value;
            tails_pos[pos] = idx;
        }
        prev[idx] = pos > 0 ? static_cast<std::int64_t>(tails_pos[pos - 1]) : -1;
    }
    std::vector<std::size_t> chosen;
    std::int64_t node =
        tails_pos.empty() ? -1 : static_cast<std::int64_t>(tails_pos.back());
    while (node >= 0) {
        chosen.push_back(static_cast<std::size_t>(node));
        node = prev[static_cast<std::size_t>(node)];
    }
    return chosen;
}

struct TreeIndex {
    // parent node id ("") -> child ids (in order). Only parents that have
    // children appear (diff iterates the union).
    std::map<std::string, std::vector<std::string>> children_of;
    // node id -> parent id.
    std::map<std::string, std::string> parents;
    // group id -> node.
    std::map<std::string, const TreeNode*> groups;
};

std::string node_id_of(const TreeNode& node) {
    return node.is_group ? node.group_id : node.layer_id;
}

void index_tree_into(const std::vector<TreeNode>& children,
                     const std::string& parent_id, TreeIndex& index) {
    for (const TreeNode& child : children) {
        const std::string node_id = node_id_of(child);
        if (child.is_group) index.groups[node_id] = &child;
        index.parents[node_id] = parent_id;
        index.children_of[parent_id].push_back(node_id);
        if (child.is_group) index_tree_into(child.children, node_id, index);
    }
}

TreeIndex index_tree(const LayerTreeSnapshot& snapshot) {
    TreeIndex index;
    index_tree_into(snapshot.children, "", index);
    return index;
}

// Whether each desired position belongs to the order-preserving
// "do not move" set (current<->desired common subsequence).
std::vector<bool> lcs_membership(const std::vector<std::string>& current_ids,
                                 const std::vector<std::string>& desired_ids) {
    std::map<std::string, std::vector<std::size_t>> current_positions;
    for (std::size_t idx = 0; idx < current_ids.size(); ++idx) {
        current_positions[current_ids[idx]].push_back(idx);
    }
    // Reduction: for each desired id in order, append its current
    // positions reversed (the classic patience mapping).
    std::vector<long long> seq;
    std::vector<std::size_t> des_index_of;
    for (std::size_t di = 0; di < desired_ids.size(); ++di) {
        auto it = current_positions.find(desired_ids[di]);
        if (it == current_positions.end()) continue;
        for (std::size_t ri = it->second.size(); ri-- > 0;) {
            seq.push_back(static_cast<long long>(it->second[ri]));
            des_index_of.push_back(di);
        }
    }
    const std::vector<std::size_t> chosen = lis_chosen_positions(seq);
    std::vector<bool> membership(desired_ids.size(), false);
    for (const std::size_t k : chosen) membership[des_index_of[k]] = true;
    return membership;
}

}  // namespace

std::vector<std::size_t> lcs_indices(const std::vector<std::string>& a,
                                     const std::vector<std::string>& b) {
    if (a == b) {
        std::vector<std::size_t> out(a.size());
        for (std::size_t i = 0; i < a.size(); ++i) out[i] = i;
        return out;
    }
    std::map<std::string, std::vector<std::size_t>> b_positions;
    for (std::size_t idx = 0; idx < b.size(); ++idx) {
        b_positions[b[idx]].push_back(idx);
    }
    std::vector<long long> seq;
    std::vector<std::size_t> a_index_of;
    for (std::size_t a_idx = 0; a_idx < a.size(); ++a_idx) {
        auto it = b_positions.find(a[a_idx]);
        if (it == b_positions.end()) continue;
        for (std::size_t ri = it->second.size(); ri-- > 0;) {
            seq.push_back(static_cast<long long>(it->second[ri]));
            a_index_of.push_back(a_idx);
        }
    }
    const std::vector<std::size_t> chosen = lis_chosen_positions(seq);
    std::set<std::size_t> keep;
    for (const std::size_t k : chosen) keep.insert(a_index_of[k]);
    return std::vector<std::size_t>(keep.begin(), keep.end());
}

TreeDiff diff_trees(const LayerTreeSnapshot& current,
                    const LayerTreeSnapshot& desired) {
    const TreeIndex cur = index_tree(current);
    const TreeIndex des = index_tree(desired);

    TreeDiff diff;

    // -- group set + renames + keyed states ----------------------------------
    for (const auto& [group_id, group] : des.groups) {
        auto cur_it = cur.groups.find(group_id);
        if (cur_it == cur.groups.end()) {
            GroupCreate create;
            create.group_id = group_id;
            create.name = group->name;
            auto parent_it = des.parents.find(group_id);
            create.parent = parent_it == des.parents.end()
                                ? std::string()
                                : parent_it->second;
            diff.group_creates.push_back(std::move(create));
        } else {
            const TreeNode* cur_group = cur_it->second;
            if (cur_group->name != group->name) {
                diff.group_renames.push_back(
                    GroupRename{group_id, group->name});
            }
            if (cur_group->visible != group->visible) {
                diff.group_states.push_back(
                    GroupStateSet{group_id, "visible", group->visible});
            }
            if (cur_group->expanded != group->expanded) {
                diff.group_states.push_back(
                    GroupStateSet{group_id, "expanded", group->expanded});
            }
            if (cur_group->locked != group->locked) {
                diff.group_states.push_back(
                    GroupStateSet{group_id, "locked", group->locked});
            }
        }
    }
    for (const auto& [group_id, group] : cur.groups) {
        (void)group;
        if (des.groups.find(group_id) == des.groups.end()) {
            diff.group_removes.push_back(GroupRemove{group_id});
        }
    }

    // Creates in topological order (parents before children): depth in
    // the desired tree approximates a topological order.
    auto depth_of = [&des](const std::string& group_id) {
        int depth = 0;
        std::string node = group_id;
        while (!node.empty()) {
            auto it = des.parents.find(node);
            if (it == des.parents.end()) break;
            node = it->second;
            ++depth;
        }
        return depth;
    };
    std::stable_sort(diff.group_creates.begin(), diff.group_creates.end(),
                     [&](const GroupCreate& a, const GroupCreate& b) {
                         return depth_of(a.group_id) < depth_of(b.group_id);
                     });

    // -- placement and order: LCS over the container union -------------------
    std::set<std::string> all_containers;
    for (const auto& entry : cur.children_of) all_containers.insert(entry.first);
    for (const auto& entry : des.children_of) all_containers.insert(entry.first);
    for (const std::string& container : all_containers) {
        auto cur_it = cur.children_of.find(container);
        auto des_it = des.children_of.find(container);
        std::vector<std::string> cur_ids =
            cur_it == cur.children_of.end() ? std::vector<std::string>{}
                                            : cur_it->second;
        std::vector<std::string> des_ids =
            des_it == des.children_of.end() ? std::vector<std::string>{}
                                            : des_it->second;
        const std::vector<bool> in_lcs = lcs_membership(cur_ids, des_ids);
        for (std::size_t index = 0; index < des_ids.size(); ++index) {
            if (in_lcs[index]) continue;
            const std::string& node_id = des_ids[index];
            auto parent_it = des.parents.find(node_id);
            const std::string parent =
                parent_it == des.parents.end() ? container : parent_it->second;
            if (des.groups.count(node_id) != 0) {
                diff.group_moves.push_back(
                    GroupMove{node_id, parent, static_cast<int>(index)});
            } else {
                diff.layer_moves.push_back(
                    LayerMove{node_id, parent, static_cast<int>(index)});
            }
        }
    }
    return diff;
}

}  // namespace pwb::workspace
