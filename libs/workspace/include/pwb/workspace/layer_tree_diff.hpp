// V14 TreeDiff — minimal op set between desired and current tree
// (keyed LCS). 1:1 port of
// paleo_workbench/mapping_workspace/layer_tree_diff.py (V11 design,
// docs/development/qgis-cartography-runtime-v11/05-tree-diff.md).
//
// Replaces the coarse "discovery order differs -> re-place all children"
// path: per container, the child-id sequences are matched with a longest
// common subsequence — nodes inside the LCS do not move; the others move
// to their target positions. Group-set differences become create/remove;
// rename / visibility / expand / lock are separate keyed ops.
//
// The op structs are frozen vocabulary (assertable counts in tests);
// LayerGroupController._apply_tree maps them onto ILayerTreeStack calls
// inside the native transaction window.
//
// Complexity: O(sum |children| log) (LCS via patience), no list.index
// hot path.
#pragma once

#include "pwb/workspace/layer_tree.hpp"

#include <string>
#include <vector>

namespace pwb::workspace {

struct GroupCreate {
    std::string group_id;
    std::string name;
    std::string parent;  // "" = root
};

struct GroupRemove {
    std::string group_id;
};

struct GroupRename {
    std::string group_id;
    std::string new_name;
};

struct GroupMove {
    std::string group_id;
    std::string new_parent;
    int new_index = 0;
};

struct LayerMove {
    std::string layer_id;
    std::string new_parent;  // "" = root
    int new_index = 0;
};

// Keyed group-state set (kind in {"visible", "expanded", "locked"}).
struct GroupStateSet {
    std::string group_id;
    std::string kind;
    bool value = false;
};

struct TreeDiff {
    std::vector<GroupCreate> group_creates;
    std::vector<GroupRemove> group_removes;
    std::vector<GroupRename> group_renames;
    std::vector<GroupMove> group_moves;
    std::vector<LayerMove> layer_moves;
    std::vector<GroupStateSet> group_states;

    bool is_empty() const {
        return group_creates.empty() && group_removes.empty() &&
               group_renames.empty() && group_moves.empty() &&
               layer_moves.empty() && group_states.empty();
    }
    std::size_t op_count() const {
        return group_creates.size() + group_removes.size() +
               group_renames.size() + group_moves.size() +
               layer_moves.size() + group_states.size();
    }
};

// LCS: ascending indices of `a` that belong to the common subsequence of
// a and b. O(n log n) (patience LIS reduction); equal sequences return
// every index.
std::vector<std::size_t> lcs_indices(const std::vector<std::string>& a,
                                     const std::vector<std::string>& b);

// Minimal op set: current (observed/applied) -> desired. Conventions:
// * group removal never cascades layer deletion (remove_groups_except
//   hoists children — op semantics match the stack);
// * group creates are emitted in topological order (parents first);
// * moves are only emitted for nodes outside the container LCS
//   (including cross-container moves);
// * visible/expanded/locked compare only groups present on both sides.
TreeDiff diff_trees(const LayerTreeSnapshot& current,
                    const LayerTreeSnapshot& desired);

}  // namespace pwb::workspace
