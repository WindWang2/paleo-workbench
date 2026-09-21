// V14 layer tree model — port of layer_tree.py (see layer_tree.hpp).
#include "pwb/workspace/layer_tree.hpp"

#include <set>

namespace pwb::workspace {

namespace {

void iter_layers_into(const std::vector<TreeNode>& children,
                      std::vector<std::string>& out) {
    for (const TreeNode& child : children) {
        if (child.is_group) {
            iter_layers_into(child.children, out);
        } else {
            out.push_back(child.layer_id);
        }
    }
}

void iter_groups_into(const std::vector<TreeNode>& children,
                      std::vector<const TreeNode*>& out) {
    for (const TreeNode& child : children) {
        if (child.is_group) {
            out.push_back(&child);
            iter_groups_into(child.children, out);
        }
    }
}

void iter_groups_mut_into(std::vector<TreeNode>& children,
                          std::vector<TreeNode*>& out) {
    for (TreeNode& child : children) {
        if (child.is_group) {
            out.push_back(&child);
            iter_groups_mut_into(child.children, out);
        }
    }
}

const TreeNode* find_group_in(const std::vector<TreeNode>& children,
                              const std::string& group_id) {
    for (const TreeNode& child : children) {
        if (!child.is_group) continue;
        if (child.group_id == group_id) return &child;
        if (const TreeNode* found = find_group_in(child.children, group_id)) {
            return found;
        }
    }
    return nullptr;
}

const TreeNode* find_layer_parent_in(const std::vector<TreeNode>& children,
                                     const std::string& layer_id) {
    for (const TreeNode& child : children) {
        if (!child.is_group && child.layer_id == layer_id) return nullptr;
    }
    for (const TreeNode& child : children) {
        if (!child.is_group) continue;
        for (const TreeNode& grand : child.children) {
            if (!grand.is_group && grand.layer_id == layer_id) return &child;
        }
        if (const TreeNode* found =
                find_layer_parent_in(child.children, layer_id)) {
            return found;
        }
    }
    return nullptr;
}

}  // namespace

domain::Json TreeNode::to_json() const {
    domain::Json out = domain::Json::object();
    if (!is_group) {
        out["type"] = "layer";
        out["id"] = layer_id;
        if (!order_key.empty()) out["order_key"] = order_key;
        return out;
    }
    out["type"] = "group";
    out["id"] = group_id;
    out["name"] = name;
    out["kind"] = kind;
    out["expanded"] = expanded;
    out["locked"] = locked;
    out["visible"] = visible;
    out["children"] = domain::Json::array();
    for (const TreeNode& child : children) {
        out["children"].push_back(child.to_json());
    }
    if (!order_key.empty()) out["order_key"] = order_key;
    return out;
}

std::optional<TreeNode> TreeNode::from_json(const domain::Json& data) {
    if (!data.is_object()) return std::nullopt;
    const std::string type = data.value("type", std::string());
    const std::string id = data.value("id", std::string());
    if (type == "layer") {
        TreeNode node = TreeNode::layer(id, data.value("order_key", std::string()));
        node.note = data.value("note", std::string());
        return node;
    }
    if (type == "group") {
        TreeNode node = TreeNode::group(
            id, data.value("name", id.empty() ? std::string() : id));
        node.kind = data.value("kind", std::string("system"));
        node.expanded = data.value("expanded", true);
        node.locked = data.value("locked", false);
        node.visible = data.value("visible", true);
        node.order_key = data.value("order_key", std::string());
        if (data.contains("children") && data["children"].is_array()) {
            for (const auto& child : data["children"]) {
                if (auto parsed = TreeNode::from_json(child)) {
                    node.children.push_back(std::move(*parsed));
                }
            }
        }
        return node;
    }
    return std::nullopt;
}

std::vector<std::string> LayerTreeSnapshot::iter_layers() const {
    std::vector<std::string> out;
    iter_layers_into(children, out);
    return out;
}

std::vector<const TreeNode*> LayerTreeSnapshot::iter_groups() const {
    std::vector<const TreeNode*> out;
    iter_groups_into(children, out);
    return out;
}

std::vector<TreeNode*> LayerTreeSnapshot::iter_groups_mut() {
    std::vector<TreeNode*> out;
    iter_groups_mut_into(children, out);
    return out;
}

const TreeNode* LayerTreeSnapshot::find_group(
    const std::string& group_id) const {
    return find_group_in(children, group_id);
}

TreeNode* LayerTreeSnapshot::find_group(const std::string& group_id) {
    return const_cast<TreeNode*>(
        static_cast<const LayerTreeSnapshot*>(this)->find_group(group_id));
}

const TreeNode* LayerTreeSnapshot::find_layer_parent(
    const std::string& layer_id) const {
    return find_layer_parent_in(children, layer_id);
}

std::vector<std::string> LayerTreeSnapshot::group_ids() const {
    std::vector<std::string> out;
    for (const TreeNode* group : iter_groups()) {
        out.push_back(group->group_id);
    }
    return out;
}

std::vector<std::string> LayerTreeSnapshot::flatten_for_render(
    const std::vector<std::string>& snapshot_layer_ids) const {
    std::set<std::string> snapshot_set(snapshot_layer_ids.begin(),
                                       snapshot_layer_ids.end());
    const std::vector<std::string> tree_order = iter_layers();
    std::vector<std::string> ordered;
    std::set<std::string> seen;
    for (const std::string& layer_id : tree_order) {
        if (snapshot_set.count(layer_id) != 0) {
            ordered.push_back(layer_id);
            seen.insert(layer_id);
        }
    }
    for (const std::string& layer_id : snapshot_layer_ids) {
        if (seen.count(layer_id) == 0) ordered.push_back(layer_id);
    }
    return ordered;
}

domain::Json LayerTreeSnapshot::to_json() const {
    domain::Json out = domain::Json::object();
    out["source"] = source;
    out["children"] = domain::Json::array();
    for (const TreeNode& child : children) {
        out["children"].push_back(child.to_json());
    }
    return out;
}

LayerTreeSnapshot LayerTreeSnapshot::from_json(const domain::Json& data) {
    LayerTreeSnapshot snapshot;
    if (!data.is_object()) return snapshot;
    snapshot.source = data.value("source", std::string("domain"));
    if (data.contains("children") && data["children"].is_array()) {
        for (const auto& child : data["children"]) {
            if (auto parsed = TreeNode::from_json(child)) {
                snapshot.children.push_back(std::move(*parsed));
            }
        }
    }
    return snapshot;
}

namespace {

TreeNode group_from_bridge_node(const domain::Json& node) {
    TreeNode group = TreeNode::group(
        node.value("id", std::string()), node.value("name", std::string()));
    group.kind = node.value("kind", std::string("system"));
    const std::string id = node.value("id", std::string());
    // Python: ids starting with phase/factor/root are system groups,
    // everything else observed in the tree is a user group.
    group.kind =
        (id.rfind("phase", 0) == 0 || id.rfind("factor", 0) == 0 ||
         id.rfind("root", 0) == 0)
            ? node.value("kind", std::string("system"))
            : "user";
    group.expanded = node.value("expanded", true);
    group.locked = node.value("locked", false);
    group.visible = node.value("visible", true);
    group.order_key = node.value("order_key", std::string());
    if (node.contains("children") && node["children"].is_array()) {
        for (const auto& child : node["children"]) {
            if (!child.is_object()) continue;
            if (child.value("type", std::string()) == "group") {
                group.children.push_back(group_from_bridge_node(child));
            } else {
                group.children.push_back(TreeNode::layer(
                    child.value("id", std::string()),
                    child.value("order_key", std::string())));
            }
        }
    }
    return group;
}

}  // namespace

LayerTreeSnapshot tree_from_nodes(const domain::Json& nodes) {
    LayerTreeSnapshot snapshot;
    snapshot.source = "qgis";
    if (!nodes.is_array()) return snapshot;
    for (const auto& node : nodes) {
        if (!node.is_object()) continue;
        const std::string type = node.value("type", std::string());
        if (type == "group") {
            snapshot.children.push_back(group_from_bridge_node(node));
        } else if (type == "layer") {
            snapshot.children.push_back(
                TreeNode::layer(node.value("id", std::string())));
        }
    }
    return snapshot;
}

}  // namespace pwb::workspace
