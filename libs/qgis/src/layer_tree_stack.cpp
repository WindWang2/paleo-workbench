// V14 QgsLayerTreeStack — see layer_tree_stack.hpp. Mechanical
// translation of the controller's op vocabulary onto the stable public
// QGIS layer-tree API, porting the proven protection patterns of
// native/qgis_render_bridge/src/map_stack_service.cpp verbatim:
//   * nodeType()+static_cast dispatch (qobject_cast is unreliable on
//     QgsLayerTree node classes in the vendored build — bridge M2T3);
//   * recursive post-order subtree detach/restore around takeChild (the
//     hidden removeChildrenPrivate recursion would otherwise destroy
//     nested-group subtrees);
//   * RegistryBridgeDetach around every takeChild dance (#1154: the
//     registry bridge's removal accounting is not disabled by
//     setEnabled(false) and would unregister live layers).
// Group nodes are always swept empty-first — layer nodes are never
// deleted by this applier.
#include "pwb/qgis/layer_tree_stack.hpp"

#include "pwb/qgis/layer_adapter.hpp"
#include "pwb/qgis/map_session.hpp"

#include <QUuid>
#include <QVariant>

#include <qgslayertree.h>
#include <qgslayertreeregistrybridge.h>
#include <qgsmapcanvas.h>
#include <qgsmaplayer.h>
#include <qgsproject.h>

#include <algorithm>
#include <functional>
#include <stdexcept>

namespace pwb::qgis {

namespace {

constexpr const char* kGroupIdProp = "pwb/group_id";

// M2T3 lesson (bridge): qobject_cast is unreliable on QgsLayerTree node
// classes under the vendored build; dispatch on the nodeType() enum.
inline QgsLayerTreeGroup* treeGroupCast(QgsLayerTreeNode* node) {
    return node != nullptr && node->nodeType() == QgsLayerTreeNode::NodeGroup
               ? static_cast<QgsLayerTreeGroup*>(node)
               : nullptr;
}

inline QgsLayerTreeLayer* treeLayerCast(QgsLayerTreeNode* node) {
    return node != nullptr && node->nodeType() == QgsLayerTreeNode::NodeLayer
               ? static_cast<QgsLayerTreeLayer*>(node)
               : nullptr;
}

QgsLayerTreeGroup* findGroupByGroupId(QgsLayerTreeGroup* parent,
                                      const std::string& group_id) {
    if (parent == nullptr || group_id.empty()) return nullptr;
    const QList<QgsLayerTreeNode*> children = parent->children();
    for (QgsLayerTreeNode* child : children) {
        auto* group = treeGroupCast(child);
        if (group == nullptr) continue;
        if (group->customProperty(kGroupIdProp).toString().toStdString() ==
            group_id) {
            return group;
        }
        if (QgsLayerTreeGroup* found = findGroupByGroupId(group, group_id)) {
            return found;
        }
    }
    return nullptr;
}

// Mint a stable id for groups created inside QGIS (never identity from
// display names) and persist it on the node.
std::string ensureGroupNodeId(QgsLayerTreeGroup* group) {
    if (group == nullptr) return std::string();
    const QVariant existing = group->customProperty(kGroupIdProp);
    if (existing.isValid() && !existing.toString().isEmpty()) {
        return existing.toString().toStdString();
    }
    const std::string assigned =
        "user_" + QUuid::createUuid().toString(QUuid::WithoutBraces)
                     .toStdString();
    group->setCustomProperty(kGroupIdProp, QString::fromStdString(assigned));
    return assigned;
}

bool isDescendantOf(QgsLayerTreeNode* node, QgsLayerTreeNode* candidate) {
    for (QgsLayerTreeNode* p = node; p != nullptr; p = p->parent()) {
        if (p == candidate) return true;
    }
    return false;
}

// takeChild's hidden semantics (bridge comment): removeChildrenPrivate
// recursively unmounts ALL descendants of the moved node first
// (makeOrphan) — taking a group that still carries child groups destroys
// the subtree. This post-order detach guarantees every takeChild target
// is childless at that moment; restore re-inserts in order.
struct SubtreeDetachEntry {
    QgsLayerTreeNode* node;
    QList<QgsLayerTreeNode*> children;
};

void detachGroupSubtree(QgsLayerTreeNode* node,
                        QList<SubtreeDetachEntry*>* log) {
    const QList<QgsLayerTreeNode*> children = node->children();
    if (children.isEmpty()) return;
    for (QgsLayerTreeNode* child : children) {
        detachGroupSubtree(child, log);
    }
    for (QgsLayerTreeNode* child : children) {
        node->takeChild(child);  // bool return; child is a leaf here
    }
    log->append(new SubtreeDetachEntry{node, children});
}

void restoreGroupSubtree(const QList<SubtreeDetachEntry*>& log) {
    for (const auto* entry : log) {
        auto* group =
            treeGroupCast(const_cast<QgsLayerTreeNode*>(entry->node));
        if (group == nullptr) continue;
        for (int i = 0; i < entry->children.size(); ++i) {
            group->insertChildNode(i, entry->children.at(i));
        }
    }
}

// #1154 dance (bridge): the registry bridge's removal accounting is not
// gated by setEnabled (groupWillRemoveChildren collects layer ids
// unconditionally); during takeChild/insertChildNode windows both root
// connections must be severed and re-attached verbatim on destruction.
struct RegistryBridgeDetach {
    QgsLayerTreeGroup* root = nullptr;
    QgsLayerTreeRegistryBridge* bridge = nullptr;
    bool detached = false;
    bool wasEnabled = false;

    explicit RegistryBridgeDetach(QgsProject* project,
                                  QgsLayerTreeGroup* treeRoot)
        : root(treeRoot),
          bridge(project ? project->layerTreeRegistryBridge() : nullptr) {
        if (bridge == nullptr || root == nullptr) return;
        wasEnabled = bridge->isEnabled();
        if (wasEnabled) bridge->setEnabled(false);
        detached = QObject::disconnect(root, nullptr, bridge, nullptr);
    }

    ~RegistryBridgeDetach() {
        if (bridge == nullptr) return;
        if (detached) {
            QObject::connect(
                root, SIGNAL(willRemoveChildren(QgsLayerTreeNode*, int, int)),
                bridge,
                SLOT(groupWillRemoveChildren(QgsLayerTreeNode*, int, int)));
            QObject::connect(
                root, SIGNAL(removedChildren(QgsLayerTreeNode*, int, int)),
                bridge, SLOT(groupRemovedChildren()));
        }
        if (wasEnabled) bridge->setEnabled(true);
    }

    RegistryBridgeDetach(const RegistryBridgeDetach&) = delete;
    RegistryBridgeDetach& operator=(const RegistryBridgeDetach&) = delete;
};

}  // namespace

QgsLayerTreeStack::QgsLayerTreeStack(MapSession& session)
    : session_(session) {}

bool QgsLayerTreeStack::groups_available() const {
    return session_.project() != nullptr;
}

QgsLayerTreeStack::NodeIndex QgsLayerTreeStack::build_index() const {
    NodeIndex index;
    std::function<void(QgsLayerTreeGroup*)> walk =
        [&](QgsLayerTreeGroup* parent) {
            const QList<QgsLayerTreeNode*> children = parent->children();
            for (QgsLayerTreeNode* child : children) {
                if (auto* layer_node = treeLayerCast(child)) {
                    QgsMapLayer* layer = layer_node->layer();
                    if (layer == nullptr) continue;
                    std::string legacy;
                    const std::string id = layer_adapter::layer_id_of(
                        layer, &legacy);
                    const std::string key =
                        !id.empty() ? id : legacy;  // legacy doc_id compat
                    if (!key.empty()) {
                        index.layer_nodes[key] = child;
                    }
                } else if (auto* group = treeGroupCast(child)) {
                    const std::string gid = ensureGroupNodeId(group);
                    index.group_nodes[gid] = child;
                    walk(group);
                }
            }
        };
    walk(session_.project()->layerTreeRoot());
    return index;
}

void QgsLayerTreeStack::upsert_group(const std::string& group_id,
                                     const std::string& name,
                                     const std::string& parent) {
    if (session_.project() == nullptr) {
        throw std::runtime_error("layer tree stack has no project");
    }
    if (group_id.empty()) {
        throw std::invalid_argument("group_id must not be empty");
    }
    QgsLayerTree* root = session_.project()->layerTreeRoot();
    QgsLayerTreeGroup* parent_group = root;
    if (!parent.empty()) {
        parent_group = findGroupByGroupId(root, parent);
        if (parent_group == nullptr) {
            throw std::invalid_argument("parent group not found: " + parent);
        }
    }
    QgsLayerTreeGroup* existing = findGroupByGroupId(root, group_id);
    if (existing == nullptr) {
        auto* node = new QgsLayerTreeGroup(QString::fromStdString(name));
        node->setCustomProperty(kGroupIdProp,
                                QString::fromStdString(group_id));
        parent_group->addChildNode(node);
    } else {
        if (existing->name().toStdString() != name) {
            existing->setName(QString::fromStdString(name));
        }
        if (existing != parent_group && existing->parent() != parent_group) {
            // Wrong parent: move the whole group with the bridge's
            // protected dance (subtree detach + registry-bridge sever).
            RegistryBridgeDetach bridge_detach(session_.project(), root);
            QList<SubtreeDetachEntry*> subtree_log;
            detachGroupSubtree(existing, &subtree_log);
            if (QgsLayerTreeNode* old_parent = existing->parent()) {
                old_parent->takeChild(existing);
            }
            parent_group->addChildNode(existing);
            restoreGroupSubtree(subtree_log);
            qDeleteAll(subtree_log);
        }
    }
    if (!in_window()) sync_close();
}

void QgsLayerTreeStack::rename_group(const std::string& group_id,
                                     const std::string& name) {
    if (session_.project() == nullptr) {
        throw std::runtime_error("layer tree stack has no project");
    }
    QgsLayerTreeGroup* group = findGroupByGroupId(
        session_.project()->layerTreeRoot(), group_id);
    if (group == nullptr) {
        throw std::invalid_argument("group not found: " + group_id);
    }
    if (group->name().toStdString() != name) {
        group->setName(QString::fromStdString(name));
    }
}

void QgsLayerTreeStack::remove_groups_except(
    const std::vector<std::string>& keep_ids) {
    if (session_.project() == nullptr) {
        throw std::runtime_error("layer tree stack has no project");
    }
    QgsLayerTree* root = session_.project()->layerTreeRoot();
    RegistryBridgeDetach bridge_detach(session_.project(), root);
    // Port of the bridge's removeGroupsExcept: collect doomed groups
    // bottom-up (children before parents), then hoist each doomed group's
    // direct children to its parent and delete the now-empty group node.
    // A group deletion NEVER deletes layers. The detach/restore dance is
    // used only for GROUP children (takeChild recursively unmounts the
    // moved node's descendants — layers have none; the desired tree's
    // root-reachability invariant means keep-groups never sit inside a
    // doomed group, but the dance makes the hoist safe regardless).
    std::vector<QgsLayerTreeGroup*> doomed;
    std::function<void(QgsLayerTreeGroup*)> collect =
        [&](QgsLayerTreeGroup* parent) {
            const QList<QgsLayerTreeNode*> children = parent->children();
            for (QgsLayerTreeNode* child : children) {
                auto* group = treeGroupCast(child);
                if (group == nullptr) continue;
                collect(group);
                const std::string gid = ensureGroupNodeId(group);
                if (std::find(keep_ids.begin(), keep_ids.end(), gid) ==
                    keep_ids.end()) {
                    doomed.push_back(group);
                }
            }
        };
    collect(root);
    for (QgsLayerTreeGroup* group : doomed) {
        QgsLayerTreeNode* parent_node = group->parent();
        auto* parent_group = treeGroupCast(parent_node);
        if (parent_group == nullptr) continue;
        const QList<QgsLayerTreeNode*> children = group->children();
        for (QgsLayerTreeNode* child : children) {
            if (auto* child_group = treeGroupCast(child)) {
                QList<SubtreeDetachEntry*> subtree_log;
                detachGroupSubtree(child_group, &subtree_log);
                group->takeChild(child);
                parent_group->addChildNode(child);
                restoreGroupSubtree(subtree_log);
                qDeleteAll(subtree_log);
            } else {
                group->takeChild(child);
                parent_group->addChildNode(child);
            }
        }
        parent_group->removeChildNode(group);
    }
    if (!in_window()) sync_close();
}

void QgsLayerTreeStack::move_layer_to_group(const std::string& layer_id,
                                            const std::string& parent,
                                            int index) {
    apply_tree_placements({{layer_id, parent, index}});
}

void QgsLayerTreeStack::move_group(const std::string& group_id,
                                   const std::string& parent, int index) {
    apply_tree_placements({{"group:" + group_id, parent, index}});
}

pwb::ui_composite::PlacementReport QgsLayerTreeStack::apply_tree_placements(
    const std::vector<pwb::ui_composite::PlacementOp>& ops) {
    if (session_.project() == nullptr) {
        throw std::runtime_error("layer tree stack has no project");
    }
    QgsLayerTree* root = session_.project()->layerTreeRoot();
    // One-pass index: join key -> layer node, group id -> group node
    // (mirrors the bridge's applyTreePlacements; no per-move rescans).
    NodeIndex index = build_index();
    pwb::ui_composite::PlacementReport report;
    RegistryBridgeDetach bridge_detach(session_.project(), root);
    for (const pwb::ui_composite::PlacementOp& op : ops) {
        QgsLayerTreeGroup* target = root;
        if (!op.parent.empty()) {
            auto found = index.group_nodes.find(op.parent);
            if (found == index.group_nodes.end()) {
                ++report.skipped;
                continue;
            }
            target = treeGroupCast(found->second);
            if (target == nullptr) {
                ++report.skipped;
                continue;
            }
        }
        if (op.node.rfind("group:", 0) == 0) {
            const std::string gid = op.node.substr(6);
            auto found = index.group_nodes.find(gid);
            if (found == index.group_nodes.end()) {
                ++report.skipped;
                continue;
            }
            QgsLayerTreeNode* node = found->second;
            if (node == target || isDescendantOf(target, node)) {
                ++report.skipped;  // never move a group into itself
                continue;
            }
            // Subtree-safe move with the bridge's protected dance.
            QList<SubtreeDetachEntry*> subtree_log;
            detachGroupSubtree(node, &subtree_log);
            if (QgsLayerTreeNode* old_parent = node->parent()) {
                old_parent->takeChild(node);
            }
            const int count = static_cast<int>(target->children().size());
            target->insertChildNode(
                op.index < 0 ? count : std::min(op.index, count), node);
            restoreGroupSubtree(subtree_log);
            qDeleteAll(subtree_log);
        } else {
            auto found = index.layer_nodes.find(op.node);
            if (found == index.layer_nodes.end()) {
                ++report.skipped;
                continue;
            }
            QgsLayerTreeNode* node = found->second;
            if (QgsLayerTreeNode* old_parent = node->parent()) {
                old_parent->takeChild(node);
            }
            const int count = static_cast<int>(target->children().size());
            target->insertChildNode(
                op.index < 0 ? count : std::min(op.index, count), node);
        }
        ++report.applied;
    }
    if (!in_window()) sync_close();
    report.revision = revision_;
    return report;
}

void QgsLayerTreeStack::set_group_visibility(const std::string& group_id,
                                             bool visible) {
    if (session_.project() == nullptr) return;
    QgsLayerTreeGroup* group = findGroupByGroupId(
        session_.project()->layerTreeRoot(), group_id);
    if (group == nullptr) return;  // Python parity: silent skip
    group->setItemVisibilityChecked(visible);
}

void QgsLayerTreeStack::set_group_expanded(const std::string& group_id,
                                           bool expanded) {
    // Expanded state lives on the tree view/model side; the node-level
    // property keeps the domain value across reopen.
    if (session_.project() == nullptr) return;
    QgsLayerTreeGroup* group = findGroupByGroupId(
        session_.project()->layerTreeRoot(), group_id);
    if (group == nullptr) return;
    group->setCustomProperty("pwb/expanded", expanded);
}

std::optional<std::int64_t> QgsLayerTreeStack::begin_tree_update() {
    ++window_depth_;
    if (window_depth_ == 1) {
        window_token_ = static_cast<std::int64_t>(revision_ + 1);
        // Suppress rendering during the batch: tree-bridge setLayers
        // calls stay idempotent; the single refresh happens at close.
        for (QgsMapCanvas* canvas : session_.canvases()) {
            if (canvas != nullptr && canvas->renderFlag()) {
                canvas->setRenderFlag(false);
                render_flags_suppressed_ = true;
            }
        }
    }
    return window_token_;
}

pwb::ui_composite::TreeUpdateResult QgsLayerTreeStack::end_tree_update(
    std::int64_t token) {
    if (window_depth_ == 0) {
        throw std::runtime_error(
            "end_tree_update without an open window");
    }
    if (token != window_token_) {
        // Token mismatch (nested misuse): reset depth but still flush the
        // pending sync — mirror of the bridge's partial-failure rule.
        window_depth_ = 0;
        sync_close();
        throw std::runtime_error("tree update token mismatch");
    }
    --window_depth_;
    pwb::ui_composite::TreeUpdateResult result;
    if (window_depth_ == 0) {
        sync_close();
        result.revision = ++revision_;
        result.deferred_sync = true;
    }
    return result;
}

void QgsLayerTreeStack::sync_close() {
    // The deferred single sync: restore rendering (if this stack
    // suppressed it), then one refresh across every canvas.
    if (render_flags_suppressed_) {
        render_flags_suppressed_ = false;
        for (QgsMapCanvas* canvas : session_.canvases()) {
            if (canvas != nullptr && !canvas->renderFlag()) {
                canvas->setRenderFlag(true);
            }
        }
    }
    session_.refreshCanvases();
}

pwb::domain::Json QgsLayerTreeStack::tree_snapshot_nodes() const {
    pwb::domain::Json nodes = pwb::domain::Json::array();
    if (session_.project() == nullptr) return nodes;
    std::function<void(QgsLayerTreeGroup*, pwb::domain::Json&)>
        append_children = [&](QgsLayerTreeGroup* parent,
                              pwb::domain::Json& out) {
            const QList<QgsLayerTreeNode*> children = parent->children();
            for (QgsLayerTreeNode* child : children) {
                if (auto* group = treeGroupCast(child)) {
                    pwb::domain::Json node = pwb::domain::Json::object();
                    node["type"] = "group";
                    node["id"] = ensureGroupNodeId(group);
                    node["name"] = group->name().toStdString();
                    node["visible"] = group->itemVisibilityChecked();
                    node["expanded"] =
                        group->customProperty("pwb/expanded", true).toBool();
                    node["children"] = pwb::domain::Json::array();
                    append_children(group, node["children"]);
                    out.push_back(std::move(node));
                } else if (auto* layer_node = treeLayerCast(child)) {
                    QgsMapLayer* layer = layer_node->layer();
                    if (layer == nullptr) continue;
                    std::string legacy;
                    const std::string id =
                        layer_adapter::layer_id_of(layer, &legacy);
                    const std::string key = !id.empty() ? id : legacy;
                    if (key.empty()) continue;  // unknown layers stay out
                    pwb::domain::Json node = pwb::domain::Json::object();
                    node["type"] = "layer";
                    node["id"] = key;
                    out.push_back(std::move(node));
                }
            }
        };
    append_children(session_.project()->layerTreeRoot(), nodes);
    return nodes;
}

}  // namespace pwb::qgis
