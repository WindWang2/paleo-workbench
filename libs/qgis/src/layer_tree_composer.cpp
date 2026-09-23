// LayerTreeComposer — see layer_tree_composer.hpp. Structural mutations
// port the proven protection patterns of the retired QgsLayerTreeStack
// (originally native/qgis_render_bridge/src/map_stack_service.cpp):
//   * nodeType()+static_cast dispatch (qobject_cast is unreliable on
//     QgsLayerTree node classes in the vendored build — bridge M2T3);
//   * recursive post-order subtree detach/restore around takeChild (the
//     hidden removeChildrenPrivate recursion would otherwise destroy
//     nested-group subtrees);
//   * RegistryBridgeDetach around every root-level takeChild window
//     (#1154: the registry bridge's removal accounting is not disabled
//     by setEnabled(false) and would unregister live layers).
#include "pwb/qgis/layer_tree_composer.hpp"

#include "pwb/qgis/layer_adapter.hpp"
#include "pwb/qgis/map_session.hpp"
#include "pwb/ui_composite/layer_groups.hpp"
#include "pwb/ui_composite/layer_ordering.hpp"
#include "pwb/workspace/state_ops.hpp"

#include <QDomDocument>
#include <QFile>
#include <QSaveFile>
#include <QList>
#include <QPointer>
#include <QUuid>
#include <QVariant>

#include <qgslayertree.h>
#include <qgslayertreeregistrybridge.h>
#include <qgsmapcanvas.h>
#include <qgsmaplayer.h>
#include <qgsproject.h>
#include <qgsreadwritecontext.h>

#include <algorithm>
#include <functional>
#include <memory>
#include <set>

namespace pwb::qgis {

namespace {

constexpr const char* kGroupIdProp = "pwb/group_id";
constexpr const char* kGroupKindProp = "pwb/group_kind";  // "system"|"user"
constexpr const char* kExpandedProp = "pwb/expanded";
// Sidecar root tag; the tree itself serializes as QgsLayerTree::writeXml's
// "layer-tree-group" element — byte-compatible with what a .qgs embeds.
constexpr const char* kSidecarRootTag = "pwb-layer-tree";
constexpr const char* kSidecarTreeTag = "layer-tree-group";

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

void detachGroupSubtree(
    QgsLayerTreeNode* node,
    QList<std::pair<QgsLayerTreeNode*, QList<QgsLayerTreeNode*>>>* log) {
    const QList<QgsLayerTreeNode*> children = node->children();
    if (children.isEmpty()) return;
    for (QgsLayerTreeNode* child : children) {
        detachGroupSubtree(child, log);
    }
    for (QgsLayerTreeNode* child : children) {
        node->takeChild(child);  // child is a leaf here (post-order)
    }
    log->append({node, children});
}

void restoreGroupSubtree(
    const QList<std::pair<QgsLayerTreeNode*, QList<QgsLayerTreeNode*>>>& log) {
    for (const auto& entry : log) {
        auto* group = treeGroupCast(entry.first);
        if (group == nullptr) continue;
        for (int i = 0; i < entry.second.size(); ++i) {
            group->insertChildNode(i, entry.second.at(i));
        }
    }
}

// #1154 dance (bridge): the registry bridge's removal accounting is not
// gated by setEnabled (groupWillRemoveChildren collects layer ids
// unconditionally); during takeChild windows both root connections must
// be severed and re-attached verbatim on destruction. Nested use is
// safe: an inner detach finds the connections already severed
// (disconnect returns false -> no reconnect) and records
// wasEnabled=false (the outer scope disabled it) -> no premature
// re-enable.
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

// Batched mutation scope: severs the registry bridge, suppresses canvas
// rendering on every live canvas and restores it with exactly one
// refresh at scope exit (R2-13: restore only what this scope
// suppressed). Nested use is safe: an inner scope finds every canvas
// already suppressed (renderFlag false -> empty list -> no refresh of
// its own); the outer scope performs the single closing refresh.
struct LayerTreeComposer::MutationGuard {
    MapSession& session;
    LayerTreeComposer& owner;
    std::unique_ptr<RegistryBridgeDetach> bridge_detach;
    std::vector<QPointer<QgsMapCanvas>> suppressed;

    MutationGuard(MapSession& s, LayerTreeComposer& c) : session(s), owner(c) {
        ++owner.batch_depth_;
        if (s.project() != nullptr) {
            bridge_detach = std::make_unique<RegistryBridgeDetach>(
                s.project(), s.project()->layerTreeRoot());
        }
        for (QgsMapCanvas* canvas : s.canvases()) {
            if (canvas != nullptr && canvas->renderFlag()) {
                canvas->setRenderFlag(false);
                suppressed.push_back(canvas);
            }
        }
    }

    ~MutationGuard() {
        bridge_detach.reset();
        for (const QPointer<QgsMapCanvas>& canvas : suppressed) {
            if (canvas != nullptr && !canvas->renderFlag()) {
                canvas->setRenderFlag(true);
            }
        }
        if (!suppressed.empty()) session.refreshCanvases();
        --owner.batch_depth_;
    }

    MutationGuard(const MutationGuard&) = delete;
    MutationGuard& operator=(const MutationGuard&) = delete;
};

LayerTreeComposer::LayerTreeComposer(
    MapSession& session, pwb::workspace::MappingWorkspaceState& state)
    : session_(session), state_(state) {}

QgsLayerTree* LayerTreeComposer::root() const {
    QgsProject* project = session_.project();
    return project != nullptr ? project->layerTreeRoot() : nullptr;
}

QgsLayerTreeGroup* LayerTreeComposer::find_group(
    const std::string& group_id) const {
    QgsLayerTreeGroup* tree_root = root();
    if (tree_root == nullptr || group_id.empty()) return nullptr;
    std::function<QgsLayerTreeGroup*(QgsLayerTreeGroup*)> walk =
        [&](QgsLayerTreeGroup* parent) -> QgsLayerTreeGroup* {
        const QList<QgsLayerTreeNode*> children = parent->children();
        for (QgsLayerTreeNode* child : children) {
            auto* group = treeGroupCast(child);
            if (group == nullptr) continue;
            if (group->customProperty(kGroupIdProp).toString().toStdString() ==
                group_id) {
                return group;
            }
            if (QgsLayerTreeGroup* found = walk(group)) return found;
        }
        return nullptr;
    };
    return walk(tree_root);
}

QgsLayerTreeNode* LayerTreeComposer::find_layer_node(
    const std::string& layer_id) const {
    QgsLayerTreeGroup* tree_root = root();
    if (tree_root == nullptr || layer_id.empty()) return nullptr;
    std::function<QgsLayerTreeNode*(QgsLayerTreeGroup*)> walk =
        [&](QgsLayerTreeGroup* parent) -> QgsLayerTreeNode* {
        const QList<QgsLayerTreeNode*> children = parent->children();
        for (QgsLayerTreeNode* child : children) {
            if (auto* layer_node = treeLayerCast(child)) {
                QgsMapLayer* layer = layer_node->layer();
                if (layer == nullptr) continue;
                if (layer->id().toStdString() == layer_id ||
                    layer_adapter::layer_id_of(layer) == layer_id) {
                    return child;
                }
            } else if (auto* group = treeGroupCast(child)) {
                if (QgsLayerTreeNode* found = walk(group)) return found;
            }
        }
        return nullptr;
    };
    return walk(tree_root);
}

bool LayerTreeComposer::group_exists(const std::string& group_id) const {
    return find_group(group_id) != nullptr;
}

std::string LayerTreeComposer::group_id_of(const QgsLayerTreeNode* node) {
    return node != nullptr
               ? node->customProperty(kGroupIdProp).toString().toStdString()
               : std::string();
}

// ---- open path --------------------------------------------------------------

bool LayerTreeComposer::compose(
    const std::optional<std::filesystem::path>& sidecar, std::string* error) {
    if (root() == nullptr) {
        if (error != nullptr) *error = "session has no project";
        return false;
    }
    bool ok = true;
    bool restored = false;
    if (sidecar.has_value() && has_sidecar(*sidecar)) {
        std::string restore_error;
        restored = restore_tree(*sidecar, &restore_error);
        if (!restored) {
            ok = false;  // sidecar existed but failed: report, keep going
            if (error != nullptr) {
                *error = "sidecar restore failed (" + restore_error +
                         ") — falling back to legacy/routing";
            }
        }
    }
    bool structured_source = false;  // tree came from a persisted payload
    if (!restored) {
        if (state_.tree.is_object() && !state_.tree.empty() &&
            state_.tree.contains("children")) {
            // One-shot migration of the retired V14 desired-tree payload.
            // From now on the QGIS tree (sidecar) is the carrier.
            migrate_legacy_tree();
            structured_source = true;
        }
    } else {
        structured_source = true;
    }
    ensure_system_groups();
    // After a persisted restore/migration, root-level layers are
    // DELIBERATE user placements — only layers with no node at all
    // (added since the last save) route home. On a fresh build every
    // root-level node is an admission auto-insert and routes.
    route_unplaced_layers(/*route_root_level=*/!structured_source);
    // The migrated legacy tree stays in state_ until the FIRST
    // successful sidecar save clears it (the host does that in
    // syncLayerControlOnSave). If that save fails, the document keeps
    // carrying the legacy tree — the user's structure survives the next
    // open instead of being silently lost.
    return ok;
}

void LayerTreeComposer::clear_tree_structure() {
    QgsLayerTreeGroup* tree_root = root();
    if (tree_root == nullptr) return;
    RegistryBridgeDetach bridge_detach(session_.project(), tree_root);
    tree_root->removeAllChildren();
}

void LayerTreeComposer::migrate_legacy_tree() {
    QgsLayerTreeGroup* tree_root = root();
    if (tree_root == nullptr) return;
    // Recursive build of real nodes from the retired
    // LayerTreeSnapshot::to_json shape: {is_group, group_id, name, kind,
    // expanded, visible, children | layer_id, order_key}. Live layers
    // only; ids of dead layers are dropped (their memberships survive in
    // the domain state untouched).
    std::function<QgsLayerTreeNode*(const pwb::domain::Json&)>
        make_node = [&](const pwb::domain::Json& data) -> QgsLayerTreeNode* {
        if (!data.is_object()) return nullptr;
        if (data.value("is_group", false)) {
            const std::string group_id = data.value("group_id", std::string());
            if (group_id.empty()) return nullptr;
            std::string name = data.value("name", std::string());
            if (name.empty()) name = group_id;
            const std::string kind = data.value("kind", std::string("system"));
            // Template titles stay authoritative for system groups
            // (display-name drift in old projects self-heals).
            if (const auto* template_def =
                    pwb::ui_composite::system_group_template(group_id)) {
                name = template_def->title;
            }
            auto* group = new QgsLayerTreeGroup(QString::fromStdString(name));
            group->setCustomProperty(kGroupIdProp,
                                     QString::fromStdString(group_id));
            group->setCustomProperty(kGroupKindProp,
                                     QString::fromStdString(kind));
            group->setCustomProperty(
                kExpandedProp, data.value("expanded", true));
            group->setItemVisibilityChecked(data.value("visible", true));
            if (data.contains("children") && data["children"].is_array()) {
                for (const auto& child : data["children"]) {
                    if (QgsLayerTreeNode* node = make_node(child)) {
                        group->addChildNode(node);
                    }
                }
            }
            return group;
        }
        const std::string layer_id = data.value("layer_id", std::string());
        if (layer_id.empty()) return nullptr;
        QgsMapLayer* layer = session_.layerById(layer_id);
        if (layer == nullptr) return nullptr;  // dead id: drop the node
        return new QgsLayerTreeLayer(layer);
    };
    MutationGuard guard(session_, *this);
    // Build first (a nullptr child never mounts), then adopt in one
    // guarded window.
    std::vector<QgsLayerTreeNode*> built;
    for (const auto& child : state_.tree.value("children",
                                               pwb::domain::Json::array())) {
        if (QgsLayerTreeNode* node = make_node(child)) built.push_back(node);
    }
    clear_tree_structure();
    for (QgsLayerTreeNode* node : built) {
        tree_root->addChildNode(node);
    }
    // Expand states from the carrier property (setExpanded is runtime;
    // the property survives the sidecar roundtrip).
    std::function<void(QgsLayerTreeGroup*)> expand = [&](QgsLayerTreeGroup* g) {
        g->setExpanded(g->customProperty(kExpandedProp, true).toBool());
        for (QgsLayerTreeNode* child : g->children()) {
            if (auto* group = treeGroupCast(child)) expand(group);
        }
    };
    expand(tree_root);
}

QgsLayerTreeGroup* LayerTreeComposer::make_factor_group_(
    const std::string& group_id) {
    const std::string task_id =
        pwb::ui_composite::factor_task_of_group(group_id).value_or("");
    std::string title = task_id.empty() ? group_id : task_id;
    const auto titles_it = factor_titles_.find(task_id);
    if (titles_it != factor_titles_.end() && !titles_it->second.empty()) {
        title = titles_it->second;
    }
    MutationGuard guard(session_, *this);
    auto* node = new QgsLayerTreeGroup(QString::fromStdString(title));
    node->setCustomProperty(kGroupIdProp, QString::fromStdString(group_id));
    node->setCustomProperty(kGroupKindProp, QStringLiteral("system"));
    node->setCustomProperty(kExpandedProp, true);
    node->setExpanded(true);
    if (QgsLayerTreeGroup* factor_root =
            find_group(pwb::ui_composite::kFactorRootGroupId)) {
        factor_root->addChildNode(node);
    } else {
        root()->addChildNode(node);
    }
    return node;
}

void LayerTreeComposer::route_unplaced_layers(bool route_root_level) {
    QgsProject* project = session_.project();
    QgsLayerTree* tree_root = root();
    if (project == nullptr || tree_root == nullptr) return;
    // Batched, index-driven routing (no per-layer tree scans — a fresh
    // 1000-layer build must stay linear). One guard window for the whole
    // batch: exactly one closing refresh.
    MutationGuard guard(session_, *this);
    // QGIS-internal O(N^2) guard: every root-level child removal runs
    // QgsLayerTree::nodeRemovedChildren, which walks the whole tree once
    // PER customLayerOrder entry. The auto-inserted admission nodes keep
    // that list at N entries, so N takeChild calls would cost N*N tree
    // walks. Clearing the custom order first (mHasCustomLayerOrder is
    // false by default — layerOrder() reads the tree, never this list)
    // makes each removal O(1); group-level inserts never re-populate it
    // (only ROOT additions do, and this batch makes none).
    tree_root->setCustomLayerOrder(QList<QgsMapLayer*>());
    ensure_system_groups();
    // One DFS builds: group_id -> group node, layer_id -> root-level
    // layer node (the registry bridge's auto-insert position). Layers
    // already inside groups (restored sidecar / migrated user structure)
    // keep their placement verbatim.
    // Routing key resolution (join id, falling back to the QGIS id) is
    // shared by the index and the candidates — keying them differently
    // would double-mount property-joined layers.
    const auto routing_key = [](QgsMapLayer* layer) {
        const std::string join_id = layer_adapter::layer_id_of(layer);
        return !join_id.empty() ? join_id : layer->id().toStdString();
    };
    std::map<std::string, QgsLayerTreeGroup*> groups;
    std::map<std::string, QgsLayerTreeNode*> root_layer_nodes;
    std::set<std::string> root_level_ids;
    std::set<std::string> grouped_layers;
    std::function<void(QgsLayerTreeGroup*)> index_tree =
        [&](QgsLayerTreeGroup* parent) {
        for (QgsLayerTreeNode* child : parent->children()) {
            if (auto* group = treeGroupCast(child)) {
                const std::string gid =
                    group->customProperty(kGroupIdProp).toString().toStdString();
                if (!gid.empty()) groups[gid] = group;
                index_tree(group);
            } else if (auto* layer_node = treeLayerCast(child)) {
                QgsMapLayer* layer = layer_node->layer();
                if (layer == nullptr) continue;
                const std::string key = routing_key(layer);
                if (parent == tree_root) {
                    root_layer_nodes[key] = child;
                    root_level_ids.insert(key);
                } else {
                    grouped_layers.insert(key);
                }
            }
        }
    };
    index_tree(tree_root);
    struct Candidate {
        std::string layer_id;
        QgsMapLayer* layer;
        pwb::ui_composite::BandSortKey sort_key;
    };
    std::vector<Candidate> candidates;
    const auto layers = project->mapLayers();
    for (auto it = layers.constBegin(); it != layers.constEnd(); ++it) {
        QgsMapLayer* layer = it.value();
        if (layer == nullptr) continue;
        const std::string id = layer->id().toStdString();
        if (id.empty()) continue;
        if (grouped_layers.count(id) != 0) continue;  // placed: keep it
        if (!route_root_level && root_level_ids.count(id) != 0) {
            continue;  // persisted root placement: deliberate, keep it
        }
        const std::string routing_id = routing_key(layer);
        const pwb::workspace::LayerBinding* record =
            pwb::workspace::membership(state_, routing_id);
        Candidate candidate;
        candidate.layer_id = routing_id;
        candidate.layer = layer;
        const std::string role =
            record != nullptr ? record->role : std::string();
        candidate.sort_key = pwb::ui_composite::band_sort_key(role);
        candidates.push_back(std::move(candidate));
    }
    // Band order = the initial scientific arrangement inside each group
    // (smaller band renders on top). After the first arrange the real
    // tree order is the truth — bands are never re-applied.
    std::sort(candidates.begin(), candidates.end(),
              [](const Candidate& a, const Candidate& b) {
                  return a.sort_key < b.sort_key;
              });
    std::map<std::string, QgsLayerTreeGroup*> factor_targets;
    for (const Candidate& candidate : candidates) {
        const pwb::workspace::LayerBinding* record =
            pwb::workspace::membership(state_, candidate.layer_id);
        std::string home;
        if (record != nullptr) {
            home = pwb::ui_composite::effective_home_group(
                record->role, record->created_stage, record->factor_task_id);
        } else {
            home = std::string(pwb::ui_composite::kLegacyGroupId);
        }
        QgsLayerTreeGroup* target = nullptr;
        if (home.rfind("factor.", 0) == 0) {
            auto known = factor_targets.find(home);
            if (known != factor_targets.end()) {
                target = known->second;
            } else {
                auto existing = groups.find(home);
                if (existing != groups.end()) {
                    target = existing->second;
                } else {
                    target = make_factor_group_(home);
                    if (target != nullptr) groups[home] = target;
                }
                factor_targets[home] = target;
            }
        } else if (!home.empty()) {
            auto found = groups.find(home);
            if (found != groups.end()) target = found->second;
        }
        if (target == nullptr) continue;  // home group not materialized
                                           // (unknown id): stay at root
        auto node_it = root_layer_nodes.find(candidate.layer_id);
        if (node_it != root_layer_nodes.end()) {
            QgsLayerTreeNode* node = node_it->second;
            tree_root->takeChild(node);
            target->addChildNode(node);
        } else {
            target->addLayer(candidate.layer);
        }
    }
}

bool LayerTreeComposer::restore_tree(const std::filesystem::path& sidecar,
                                     std::string* error) {
    QgsProject* project = session_.project();
    if (project == nullptr) {
        if (error != nullptr) *error = "session has no project";
        return false;
    }
    QFile file(QString::fromStdString(sidecar.generic_string()));
    if (!file.open(QIODevice::ReadOnly)) {
        if (error != nullptr) *error = "cannot open " + sidecar.generic_string();
        return false;
    }
    QDomDocument document;
    const QDomDocument::ParseResult parsed = document.setContent(&file);
    if (!parsed) {
        if (error != nullptr) {
            *error = "sidecar parse error: " +
                     parsed.errorMessage.toStdString();
        }
        return false;
    }
    const QDomElement tree_element =
        document.documentElement().firstChildElement(kSidecarTreeTag);
    if (tree_element.isNull()) {
        if (error != nullptr) *error = "sidecar has no layer-tree-group";
        return false;
    }
    QgsReadWriteContext context;
    std::unique_ptr<QgsLayerTree> restored =
        QgsLayerTree::readXml(tree_element, context);
    if (restored == nullptr) {
        if (error != nullptr) *error = "QgsLayerTree::readXml failed";
        return false;
    }
    restored->resolveReferences(project);
    // Drop stale layer nodes (their layer no longer resolves); keep
    // everything else verbatim (custom properties ride along natively).
    std::function<void(QgsLayerTreeGroup*)> prune = [&](QgsLayerTreeGroup* g) {
        const QList<QgsLayerTreeNode*> children = g->children();
        for (QgsLayerTreeNode* child : children) {
            if (treeLayerCast(child) != nullptr) {
                if (treeLayerCast(child)->layer() == nullptr) {
                    g->removeChildNode(child);  // deletes the dead node
                }
            } else if (auto* group = treeGroupCast(child)) {
                prune(group);
            }
        }
    };
    prune(restored.get());
    // Adopt inside one guarded window: the auto-inserted flat nodes from
    // layer admission are cleared, the restored structure takes their
    // place. Live layers missing from the restored structure are routed
    // by compose() right after (registry membership is untouched — the
    // guard severs the bridge).
    MutationGuard guard(session_, *this);
    // Same custom-order guard as route_unplaced_layers (the clear below
    // is one removal; the re-adds stay group-level).
    QgsLayerTree* tree_root = root();
    tree_root->setCustomLayerOrder(QList<QgsMapLayer*>());
    clear_tree_structure();
    for (QgsLayerTreeNode* child : restored->children()) {
        restored->takeChild(child);
        tree_root->addChildNode(child);
    }
    std::function<void(QgsLayerTreeGroup*)> expand = [&](QgsLayerTreeGroup* g) {
        g->setExpanded(g->customProperty(kExpandedProp, true).toBool());
        for (QgsLayerTreeNode* child : g->children()) {
            if (auto* group = treeGroupCast(child)) expand(group);
        }
    };
    expand(tree_root);
    return true;
}

bool LayerTreeComposer::save_tree(const std::filesystem::path& sidecar,
                                  std::string* error) {
    QgsLayerTreeGroup* tree_root = root();
    if (tree_root == nullptr) {
        if (error != nullptr) *error = "session has no project";
        return false;
    }
    // Expand states persist as node properties (QGIS serializes custom
    // properties natively; the node's runtime mExpanded itself is not
    // serialized by QgsLayerTree::writeXml).
    std::function<void(QgsLayerTreeGroup*)> record = [&](QgsLayerTreeGroup* g) {
        g->setCustomProperty(kExpandedProp, g->isExpanded());
        for (QgsLayerTreeNode* child : g->children()) {
            if (auto* group = treeGroupCast(child)) record(group);
        }
    };
    record(tree_root);
    QDomDocument document;
    QDomElement root_element = document.createElement(kSidecarRootTag);
    document.appendChild(root_element);
    QgsReadWriteContext context;
    tree_root->writeXml(root_element, context);
    std::error_code ec;
    std::filesystem::create_directories(sidecar.parent_path(), ec);
    // Atomic write (QSaveFile commits by rename): a crash or disk-full
    // mid-write can never truncate the previous good sidecar, and the
    // byte count is verified before success is claimed.
    QSaveFile file(QString::fromStdString(sidecar.generic_string()));
    if (!file.open(QIODevice::WriteOnly)) {
        if (error != nullptr) {
            *error = "cannot write " + sidecar.generic_string();
        }
        return false;
    }
    const QByteArray payload = document.toByteArray(2);
    if (file.write(payload) != payload.size() || !file.commit()) {
        if (error != nullptr) {
            *error = "short/failed write of " + sidecar.generic_string();
        }
        return false;
    }
    return true;
}

bool LayerTreeComposer::has_sidecar(const std::filesystem::path& sidecar) {
    std::error_code ec;
    return std::filesystem::exists(sidecar, ec);
}

// ---- system skeleton -----------------------------------------------------------

void LayerTreeComposer::ensure_system_groups() {
    QgsLayerTreeGroup* tree_root = root();
    if (tree_root == nullptr) return;
    const std::vector<pwb::ui_composite::GroupTemplate>& templates =
        pwb::ui_composite::system_group_templates();
    // Create-only, in template order, positioned after the last
    // already-present template group so the skeleton keeps its band
    // order while user content stays untouched.
    MutationGuard guard(session_, *this);
    for (const auto& template_def : templates) {
        if (find_group(template_def.group_id) != nullptr) continue;
        auto* node = new QgsLayerTreeGroup(
            QString::fromStdString(template_def.title));
        node->setCustomProperty(kGroupIdProp,
                                QString::fromStdString(template_def.group_id));
        node->setCustomProperty(kGroupKindProp, QStringLiteral("system"));
        node->setCustomProperty(kExpandedProp, true);
        node->setExpanded(true);
        if (template_def.parent_id.empty()) {
            // Insert after the last preceding template group (or at the
            // very top when none exists yet).
            int index = 0;
            const QList<QgsLayerTreeNode*> children = tree_root->children();
            for (int i = 0; i < children.size(); ++i) {
                auto* group = treeGroupCast(children.at(i));
                if (group == nullptr) continue;
                const std::string gid =
                    group->customProperty(kGroupIdProp).toString().toStdString();
                if (gid.empty()) continue;
                if (pwb::ui_composite::system_group_template(gid) != nullptr) {
                    index = i + 1;
                }
            }
            tree_root->insertChildNode(index, node);
        } else {
            QgsLayerTreeGroup* parent = find_group(template_def.parent_id);
            if (parent == nullptr) {
                // Parent template missing (template order guarantees it
                // exists when reached here); fail closed to root rather
                // than dropping the group.
                tree_root->insertChildNode(0, node);
            } else {
                parent->addChildNode(node);
            }
        }
    }
}

// ---- visibility -----------------------------------------------------------------

void LayerTreeComposer::apply_group_visibility(
    const std::map<std::string, bool>& visibility) {
    if (root() == nullptr) return;
    // Full push, never "changed only" (drift rationale, Python R6): the
    // real tree may have been touched by user checks between pushes.
    // Group counts are single digits and the setter is cheap; the guard
    // coalesces the canvas cost into one refresh.
    MutationGuard guard(session_, *this);
    for (const auto& [group_id, visible] : visibility) {
        QgsLayerTreeGroup* group = find_group(group_id);
        if (group == nullptr) continue;  // not materialized yet: skip
        group->setItemVisibilityChecked(visible);
    }
}

void LayerTreeComposer::set_group_visibility(const std::string& group_id,
                                             bool visible) {
    QgsLayerTreeGroup* group = find_group(group_id);
    if (group == nullptr) return;  // Python parity: silent skip
    MutationGuard guard(session_, *this);
    group->setItemVisibilityChecked(visible);
}

// ---- user groups -------------------------------------------------------------------

std::string LayerTreeComposer::create_user_group(
    const std::string& name, const std::string& parent_group_id) {
    QgsLayerTreeGroup* tree_root = root();
    if (tree_root == nullptr) return std::string();
    std::string parent = parent_group_id;
    const auto is_system = [](const std::string& gid) {
        return pwb::ui_composite::system_group_template(gid) != nullptr ||
               gid.rfind("factor.", 0) == 0 ||
               gid.rfind("phase", 0) == 0;
    };
    QgsLayerTreeGroup* parent_node = tree_root;
    if (!parent.empty()) {
        QgsLayerTreeGroup* found = find_group(parent);
        // Parent must be a USER group (or root): system/factor groups
        // never host user subgroups.
        if (found == nullptr || is_system(parent)) {
            parent.clear();  // conservative fallback: create at root
        } else {
            parent_node = found;
        }
    }
    const std::string group_id =
        "user_" + QUuid::createUuid().toString(QUuid::WithoutBraces)
                     .toStdString();
    MutationGuard guard(session_, *this);
    auto* node = new QgsLayerTreeGroup(
        QString::fromStdString(name.empty() ? std::string("新建组") : name));
    node->setCustomProperty(kGroupIdProp, QString::fromStdString(group_id));
    node->setCustomProperty(kGroupKindProp, QStringLiteral("user"));
    node->setCustomProperty(kExpandedProp, true);
    node->setExpanded(true);
    parent_node->addChildNode(node);
    return group_id;
}

bool LayerTreeComposer::rename_group(const std::string& group_id,
                                     const std::string& name) {
    QgsLayerTreeGroup* group = find_group(group_id);
    if (group == nullptr) return false;
    group->setName(QString::fromStdString(name));
    return true;
}

bool LayerTreeComposer::remove_user_group(const std::string& group_id) {
    QgsLayerTreeGroup* group = find_group(group_id);
    if (group == nullptr) return false;
    const std::string kind =
        group->customProperty(kGroupKindProp).toString().toStdString();
    if (kind == "system" ||
        pwb::ui_composite::system_group_template(group_id) != nullptr ||
        group_id.rfind("factor.", 0) == 0) {
        return false;  // system/factor groups are never user-removable
    }
    QgsLayerTreeNode* parent_node = group->parent();
    auto* parent_group =
        parent_node != nullptr ? treeGroupCast(parent_node) : nullptr;
    if (parent_group == nullptr) return false;
    MutationGuard guard(session_, *this);
    // Hoist children one level up at the group's position (never delete
    // contents), then drop the now-empty group node.
    const int position = parent_group->children().indexOf(group);
    const QList<QgsLayerTreeNode*> children = group->children();
    for (int i = 0; i < children.size(); ++i) {
        QgsLayerTreeNode* child = children.at(i);
        if (auto* child_group = treeGroupCast(child)) {
            // Protected move for nested subgroups (takeChild's hidden
            // subtree unmount).
            QList<std::pair<QgsLayerTreeNode*, QList<QgsLayerTreeNode*>>> log;
            detachGroupSubtree(child_group, &log);
            group->takeChild(child);
            parent_group->insertChildNode(position + i, child);
            restoreGroupSubtree(log);
        } else {
            group->takeChild(child);
            parent_group->insertChildNode(position + i, child);
        }
    }
    parent_group->removeChildNode(group);  // deletes the now-empty node
    return true;
}

// ---- placement -----------------------------------------------------------------------

std::optional<std::string> LayerTreeComposer::route_layer(
    const std::string& layer_id) {
    QgsProject* project = session_.project();
    if (project == nullptr || layer_id.empty()) return std::nullopt;
    QgsMapLayer* layer = session_.layerById(layer_id);
    if (layer == nullptr) return std::nullopt;
    const pwb::workspace::LayerBinding* record =
        pwb::workspace::membership(state_, layer_id);
    std::string home;
    if (record != nullptr) {
        home = pwb::ui_composite::effective_home_group(
            record->role, record->created_stage, record->factor_task_id);
    } else {
        home = std::string(pwb::ui_composite::kLegacyGroupId);
    }
    // Ensure the static skeleton exists (cheap: create-only walk).
    ensure_system_groups();
    QgsLayerTreeGroup* target = nullptr;
    if (home.rfind("factor.", 0) == 0) {
        // Factor task subgroup: per-task groups are dynamic, titled from
        // the host's task titles when known.
        target = find_group(home);
        if (target == nullptr) target = make_factor_group_(home);
    } else if (!home.empty()) {
        target = find_group(home);
    }
    QgsLayerTreeNode* node = find_layer_node(layer_id);
    if (node == nullptr) {
        // Not in the tree (e.g. registry auto-insert disabled during a
        // bulk load): create the node directly in its home.
        if (target != nullptr) {
            MutationGuard guard(session_, *this);
            target->addLayer(layer);
            return home;
        }
        MutationGuard guard(session_, *this);
        root()->addLayer(layer);
        return std::string();  // routed to root
    }
    MutationGuard guard(session_, *this);
    if (target == nullptr) {
        // Home is root: move the node to the root tail.
        if (QgsLayerTreeNode* old_parent = node->parent()) {
            if (treeGroupCast(old_parent) == root()) {
                return std::string();
            }
            RegistryBridgeDetach detach(session_.project(), root());
            old_parent->takeChild(node);
            root()->addChildNode(node);
        }
        return std::string();
    }
    if (QgsLayerTreeNode* old_parent = node->parent()) {
        if (old_parent == target) return home;
        if (treeGroupCast(old_parent) == root()) {
            RegistryBridgeDetach detach(session_.project(), root());
            root()->takeChild(node);
            target->addChildNode(node);
        } else {
            old_parent->takeChild(node);
            target->addChildNode(node);
        }
    } else {
        target->addChildNode(node);
    }
    return home;
}

std::optional<std::string> LayerTreeComposer::place_layer(
    const std::string& layer_id, const std::string& parent_group_id,
    int index) {
    QgsLayerTreeNode* node = find_layer_node(layer_id);
    if (node == nullptr) return std::nullopt;
    QgsLayerTreeGroup* tree_root = root();
    QgsLayerTreeGroup* target = tree_root;
    if (!parent_group_id.empty()) {
        target = find_group(parent_group_id);
        if (target == nullptr) return std::nullopt;
        // Role gate: a system group only accepts role-compatible layers
        // (business rule; user groups always allow).
        if (parent_group_id != pwb::ui_composite::kLegacyGroupId &&
            pwb::ui_composite::system_group_template(parent_group_id) !=
                nullptr) {
            const pwb::workspace::LayerBinding* record =
                pwb::workspace::membership(state_, layer_id);
            const std::string role =
                record != nullptr ? record->role : std::string();
            if (!pwb::ui_composite::movable_into_system_group(
                    role, parent_group_id)) {
                return std::nullopt;
            }
        }
    }
    MutationGuard guard(session_, *this);
    if (QgsLayerTreeNode* old_parent = node->parent()) {
        if (treeGroupCast(old_parent) == tree_root) {
            RegistryBridgeDetach detach(session_.project(), tree_root);
            tree_root->takeChild(node);
        } else {
            old_parent->takeChild(node);
        }
    }
    const int count = static_cast<int>(target->children().size());
    target->insertChildNode(index < 0 ? count : (std::min)(index, count), node);
    return parent_group_id;
}

std::optional<std::string> LayerTreeComposer::place_copy_adjacent(
    const std::string& source_id, const std::string& copy_id) {
    if (copy_id.empty() || copy_id == source_id) return std::nullopt;
    QgsLayerTreeNode* source_node = find_layer_node(source_id);
    if (source_node == nullptr) return std::nullopt;
    QgsLayerTreeNode* parent_node = source_node->parent();
    auto* parent_group =
        parent_node != nullptr ? treeGroupCast(parent_node) : nullptr;
    const std::string parent_gid =
        parent_group != nullptr && parent_group != root()
            ? parent_group->customProperty(kGroupIdProp)
                  .toString()
                  .toStdString()
            : std::string();
    if (!parent_gid.empty()) {
        // Role-incompatible (e.g. a draft into the prediction group): do
        // not force it — home routing wins.
        const pwb::workspace::LayerBinding* record =
            pwb::workspace::membership(state_, copy_id);
        const std::string copy_role =
            record != nullptr ? record->role : std::string();
        if (!pwb::ui_composite::movable_into_system_group(copy_role,
                                                          parent_gid)) {
            return route_layer(copy_id);
        }
    }
    QgsLayerTreeGroup* container =
        parent_group != nullptr && parent_group != root() ? parent_group
                                                          : root();
    const int position = container->children().indexOf(source_node) + 1;
    return place_layer(copy_id, parent_gid, position);
}

// ---- queries ---------------------------------------------------------------------------

std::optional<std::string> LayerTreeComposer::placement_of(
    const std::string& layer_id) const {
    QgsLayerTreeNode* node = find_layer_node(layer_id);
    if (node == nullptr) return std::nullopt;
    QgsLayerTreeNode* parent_node = node->parent();
    auto* parent_group =
        parent_node != nullptr ? treeGroupCast(parent_node) : nullptr;
    if (parent_group == nullptr || parent_group == root()) {
        return std::string();
    }
    return parent_group->customProperty(kGroupIdProp).toString().toStdString();
}

std::vector<std::string> LayerTreeComposer::layers_in(
    const std::string& group_id) const {
    std::vector<std::string> out;
    if (group_id.empty()) {
        // Whole tree order, top-first (layerOrder() semantics).
        QgsProject* project = session_.project();
        if (project == nullptr) return out;
        for (QgsMapLayer* layer : project->layerTreeRoot()->layerOrder()) {
            if (layer == nullptr) continue;
            const std::string id = layer_adapter::layer_id_of(layer);
            out.push_back(id.empty() ? layer->id().toStdString() : id);
        }
        return out;
    }
    QgsLayerTreeGroup* group = find_group(group_id);
    if (group == nullptr) return out;
    for (QgsLayerTreeNode* child : group->children()) {
        if (auto* layer_node = treeLayerCast(child)) {
            QgsMapLayer* layer = layer_node->layer();
            if (layer == nullptr) continue;
            const std::string id = layer_adapter::layer_id_of(layer);
            if (!id.empty()) out.push_back(id);
        }
    }
    return out;
}

}  // namespace pwb::qgis
