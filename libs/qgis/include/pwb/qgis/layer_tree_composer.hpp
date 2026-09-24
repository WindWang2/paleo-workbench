#pragma once

// LayerTreeComposer — the single writer/reader of the session's QGIS
// layer-tree STRUCTURE (successor of the retired V14
// plan/diff/keys/applier reconcile plane).
//
// AUTHORITY MODEL: the real QgsLayerTree of the MapSession's QgsProject
// IS the layer tree. There is no desired tree, no diff engine, no order
// keys, no mirror state and no observe/write-back loop here:
//   * structure the user sees = QgsLayerTree child order;
//   * user drag/rename/group edits land directly on the tree (the
//     QgsLayerTreeView created by MapSession::createLayerTree allows
//     reorder/rename/visibility natively) and simply ARE the result;
//   * canvas layer set follows via QgsLayerTreeMapCanvasBridge;
//   * export order reads layerOrder() (MapSession::layerIdsTopFirst).
//
// The composer only:
//   1. builds the INITIAL structure once per project open — from the
//      QGIS-native XML sidecar (QgsLayerTree::writeXml, the same
//      serializer .qgs uses) when present, else migrating the legacy
//      domain-tree JSON one-shot, else from system-group templates +
//      membership routing;
//   2. keeps the system-group skeleton present (create-only);
//   3. applies stage visibility policy onto real group nodes
//      (batched: render suppression + exactly one closing refresh);
//   4. executes user-group/placement operations on the real nodes;
//   5. persists the observed tree to the sidecar at save (single
//      direction QGIS -> file; the domain project JSON no longer stores
//      tree geometry).
//
// Group identity stays machine-readable: the "pwb/group_id" custom
// property on group nodes (never display names). Layers join through
// the deterministic QGIS layer id == pwb/layer_id set at admission
// (MapSession::addVectorLayer/addRasterLayer), with the legacy
// "pwb/doc_id" custom property as read-compat fallback.
//
// Geological semantics (role routing, stage profiles) come from
// pwb::ui_composite::layer_groups + the workspace membership state; the
// composer adds no semantics of its own.

#include <pwb/ui_composite/layer_group_controller.hpp>
#include <pwb/workspace/state.hpp>

#include <filesystem>
#include <map>
#include <optional>
#include <string>
#include <vector>

class QgsLayerTree;
class QgsLayerTreeGroup;
class QgsLayerTreeNode;

namespace pwb::qgis {

class MapSession;

class LayerTreeComposer {
public:
    LayerTreeComposer(MapSession& session,
                      pwb::workspace::MappingWorkspaceState& state);
    // Session-scoped authority over one tree — references make copies
    // meaningless and a cloned batch_depth_ would desynchronize
    // in_structural_batch().
    LayerTreeComposer(const LayerTreeComposer&) = delete;
    LayerTreeComposer& operator=(const LayerTreeComposer&) = delete;

    // ---- open path -------------------------------------------------------
    // Build the initial structure (call once per project open, after the
    // session layers are admitted). Priority: sidecar restore > legacy
    // state.tree migration > template routing. In every path: system
    // groups are ensured, live layers missing from the restored
    // structure are routed to their home groups (band order for a fresh
    // build), and any user structure is kept verbatim. After compose(),
    // only QGIS tree state exists — nothing is mirrored back.
    // Returns false when the sidecar existed but could not be read (the
    // caller reports; compose falls back to legacy/routing and still
    // yields a usable tree).
    bool compose(const std::optional<std::filesystem::path>& sidecar,
                 std::string* error = nullptr);

    // .qgs handoff restore: QgsProject::read already rebuilt the live
    // tree — it IS the structure (same authority decision as a sidecar
    // restore). Ensures the system skeleton and routes only layers with
    // no node; root-level placements stay deliberate user choice. Call
    // instead of compose() when the session map was restored from the
    // sibling .qgs file.
    void adopt_restored_tree();

    // Restore the QGIS-native tree sidecar (QgsLayerTree::writeXml
    // format). Drops layer nodes that no longer resolve to live layers
    // (stale ids), keeps everything else verbatim.
    bool restore_tree(const std::filesystem::path& sidecar,
                      std::string* error = nullptr);

    // Persist the observed tree (structure/order/visibility/expanded,
    // via QGIS's own layer-tree serializer — the same XML a .qgs file
    // embeds).
    bool save_tree(const std::filesystem::path& sidecar,
                   std::string* error = nullptr);
    static bool has_sidecar(const std::filesystem::path& sidecar);

    // ---- system skeleton ---------------------------------------------------
    // Create-only, idempotent: every system-group template exists at its
    // template position among the root's groups (existing groups are
    // never moved/renamed; user structure untouched). Factor task
    // subgroups are created on routing demand.
    void ensure_system_groups();

    // factor task titles for group display names (host syncs from the
    // project document; ids stay authoritative).
    void set_factor_titles(std::map<std::string, std::string> titles) {
        factor_titles_ = std::move(titles);
    }

    // ---- visibility (batched; one refresh per batch) -----------------------
    void apply_group_visibility(const std::map<std::string, bool>& visibility);
    void set_group_visibility(const std::string& group_id, bool visible);

    // ---- user groups ---------------------------------------------------------
    // Create a user group (parent must be a user group or root; system /
    // factor groups cannot host user subgroups — invalid parents fall
    // back to root, never throws). Returns the minted group id.
    std::string create_user_group(const std::string& name,
                                  const std::string& parent_group_id = "");
    // Rename any group (addressed by group id).
    bool rename_group(const std::string& group_id, const std::string& name);
    // Remove a user group; children hoist one level up (layers and
    // nested groups are never deleted). System groups refuse (false).
    bool remove_user_group(const std::string& group_id);

    // ---- placement --------------------------------------------------------------
    // Route one layer to its membership home group (tail insert; keeps
    // the user's arrangement — band order only governs the initial
    // arrangement of a fresh build). Returns the container group id
    // ("" = root) or nullopt when the layer is not in the project.
    std::optional<std::string> route_layer(const std::string& layer_id);
    // Move a layer (role-checked against movable_into_system_group;
    // illegal system-group placements are refused). index < 0 = append.
    // Returns the container actually used, or nullopt on refusal.
    std::optional<std::string> place_layer(const std::string& layer_id,
                                           const std::string& parent_group_id,
                                           int index = -1);
    // V12 duplicate contract: place the copy right above its source when
    // the role is compatible; otherwise home routing wins. Returns the
    // container or nullopt.
    std::optional<std::string> place_copy_adjacent(
        const std::string& source_id, const std::string& copy_id);

    // ---- queries against the live tree ---------------------------------------
    // True while a composer mutation batch (structure or stage-visibility
    // push) is running — host-side user-gesture recorders use this to
    // suppress echoes of programmatic changes.
    bool in_structural_batch() const { return batch_depth_ > 0; }
    // "pwb/group_id" of a node ("" when it carries none).
    static std::string group_id_of(const QgsLayerTreeNode* node);
    // Group id of the group directly containing the layer ("" = root);
    // nullopt when the layer has no tree node.
    std::optional<std::string> placement_of(const std::string& layer_id) const;
    // Domain layer ids inside a group (top-first), or the whole tree
    // order (group_id empty) — reads layerOrder() semantics.
    std::vector<std::string> layers_in(const std::string& group_id) const;
    bool group_exists(const std::string& group_id) const;

private:
    struct MutationGuard;  // bridge detach + render suppression + 1 refresh

    QgsLayerTree* root() const;  // QgsProject::layerTreeRoot() exact type
    QgsLayerTreeGroup* find_group(const std::string& group_id) const;
    QgsLayerTreeNode* find_layer_node(const std::string& layer_id) const;
    void clear_tree_structure();  // root children -> empty (bridge-safe)
    // One-shot legacy migration: the retired V14 state.tree JSON (same
    // shape the old LayerTreeSnapshot serialized) -> real tree nodes.
    // Live layers only; group ids/kinds carried over verbatim.
    void migrate_legacy_tree();
    // Route live layers into their membership home groups: layers with
    // no node always; root-level (admission auto-insert) layers only on
    // a fresh build (route_root_level=true) — after a sidecar/legacy
    // restore, root-level placement is a deliberate user choice.
    void route_unplaced_layers(bool route_root_level);
    // Create the per-task factor subgroup under the factor root (titled
    // from the host's task titles when known).
    QgsLayerTreeGroup* make_factor_group_(const std::string& group_id);

    MapSession& session_;
    pwb::workspace::MappingWorkspaceState& state_;
    std::map<std::string, std::string> factor_titles_;
    int batch_depth_ = 0;  // MutationGuard nesting depth
};

}  // namespace pwb::qgis
