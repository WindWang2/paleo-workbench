// V14 LayerTreeSnapshot — serializable domain representation of the
// layer tree. 1:1 port of
// paleo_workbench/mapping_workspace/layer_tree.py (V5 §9 authority
// boundary):
//
// 1. a pure-data description of the domain-side DESIRED tree (the target
//    state that drives reconcile);
// 2. the domain projection of observed QGIS tree results (user
//    drag/check/rename events written back);
// 3. the serialization carrier for project persistence (to_json/from_json,
//    no Qt).
//
// It must never grow into a second runtime-mutable tree — every domain
// edit is "build a new snapshot -> incremental reconcile of QGIS", not
// in-place long-lived editing. Python's frozen dataclasses become a
// tagged node struct (variant-of-self is not expressible; the tag keeps
// the same isinstance discipline: is_group() routes exactly where Python
// used isinstance(child, GroupNode)).
#pragma once

#include "pwb/domain/json.hpp"

#include <optional>
#include <string>
#include <vector>

namespace pwb::workspace {

// A layer node in the tree (scientific state lives on the layer itself,
// never duplicated here).
struct LayerRef {
    std::string layer_id;
    // Optional stage-membership annotation (debug/diagnostics; visibility
    // lives in StageViewState).
    std::string note;
    // V11 stable order key (layer_order; empty = un-keyed legacy node,
    // fixed-width derived at migration).
    std::string order_key;
};

// Any node in the tree: a layer reference or a group.
struct TreeNode {
    bool is_group = false;
    // Layer fields (valid when !is_group).
    std::string layer_id;
    std::string note;
    // Group fields (valid when is_group).
    // group_id is the stable identity (e.g. "phase1.initial_facies" or
    // "factor.<task_id>"), decoupled from the display name — user renames
    // never change the id, and system UI never infers semantics from
    // display names.
    std::string group_id;
    std::string name;
    // "system" = stage-flow semantic group (role-managed, undeletable);
    // "user" = user organization group.
    std::string kind = "system";
    bool expanded = true;
    bool locked = false;
    // Group visibility (domain-side last-known value of the QGIS group
    // check state).
    bool visible = true;
    std::vector<TreeNode> children;  // group nodes only

    // V11 stable order key. System-group keys derive from the template
    // band (never user-overridable); user-group keys persist the drag
    // order. Shared by layer nodes.
    std::string order_key;

    static TreeNode layer(std::string id, std::string key = "",
                          std::string note_text = "") {
        TreeNode node;
        node.is_group = false;
        node.layer_id = std::move(id);
        node.order_key = std::move(key);
        node.note = std::move(note_text);
        return node;
    }
    static TreeNode group(std::string id, std::string display_name,
                          std::string group_kind = "system") {
        TreeNode node;
        node.is_group = true;
        node.group_id = std::move(id);
        node.name = std::move(display_name);
        node.kind = std::move(group_kind);
        return node;
    }

    domain::Json to_json() const;
    static std::optional<TreeNode> from_json(const domain::Json& data);
};

// Whole desired/observed tree snapshot (root children == children of the
// QGIS tree root).
struct LayerTreeSnapshot {
    std::vector<TreeNode> children;
    // Observed snapshots may carry a source marker ("domain" | "qgis");
    // preserved on serialization for diagnostics.
    std::string source = "domain";

    // -- queries ------------------------------------------------------------
    // DFS traversal yielding layer ids (QGIS semantics: layers earlier in
    // traversal render on top).
    std::vector<std::string> iter_layers() const;
    // DFS traversal yielding group nodes (pre-order: parent before children).
    std::vector<const TreeNode*> iter_groups() const;
    std::vector<TreeNode*> iter_groups_mut();
    const TreeNode* find_group(const std::string& group_id) const;
    TreeNode* find_group(const std::string& group_id);
    // Parent group of a layer; nullptr when the layer sits at root level
    // (Python returns None for root-level — root is the implicit parent).
    const TreeNode* find_layer_parent(const std::string& layer_id) const;
    // Tree traversal order (top-first).
    std::vector<std::string> layer_ids_top_first() const {
        return iter_layers();
    }
    std::vector<std::string> group_ids() const;

    // -- render compatibility (V5 §48) ---------------------------------------
    // Flatten the domain tree over the given snapshot ids: display order
    // follows tree traversal; ids not in the tree (newly appeared, not
    // yet grouped) keep their input order appended at the tail — never
    // dropped.
    std::vector<std::string> flatten_for_render(
        const std::vector<std::string>& snapshot_layer_ids) const;

    // -- serialization --------------------------------------------------------
    domain::Json to_json() const;
    static LayerTreeSnapshot from_json(const domain::Json& data);
};

// Convenience: build an observed snapshot from a bridge callback node
// array (each item {type,id,name,...}).
LayerTreeSnapshot tree_from_nodes(const domain::Json& nodes);

}  // namespace pwb::workspace
