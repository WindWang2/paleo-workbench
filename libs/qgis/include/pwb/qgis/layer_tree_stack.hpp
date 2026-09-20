#pragma once

// V14 QgsLayerTreeStack — the ILayerTreeStack applier over a MapSession's
// QgsProject/QgsLayerTree (the native product's runtime tree authority).
// Counterpart of the Python bridge's group/placement/transaction surface
// (native/qgis_render_bridge map_stack_service), reusing the same stable
// addressing vocabulary:
//   * groups addressed by the "pwb/group_id" custom property (display
//     names never carry identity);
//   * layers joined through layer_adapter ("pwb/layer_id", legacy
//     "pwb/doc_id" read-compat);
//   * placements are top-first indices, batched with a one-pass index
//     (no per-move rescans).
//
// Transaction window: defers the closing canvas sync — inside the window
// the attached QgsLayerTreeMapCanvasBridge instances may issue
// idempotent intermediate setLayers calls, but rendering is suppressed
// (setRenderFlag(false) on every canvas) and restored with exactly one
// refresh at close. Revisions increment monotonically per close so the
// controller can drop stale echoes (LayerGroupController::echo_is_stale).
//
// NOTE (build environment): this TU requires the vendored QGIS SDK
// (Pwb::Qgis). It is compiled only when that target exists; the logic it
// mirrors (group upsert / keep-set sweep / indexed placements) is proven
// by the fake-stack tests in libs/ui_composite/composite_tests plus the
// bridge implementation it was ported from.

#include <pwb/ui_composite/layer_group_controller.hpp>

#include <cstdint>
#include <map>
#include <optional>
#include <string>
#include <vector>

class QgsLayerTree;
class QgsLayerTreeNode;
class QgsProject;

namespace pwb::qgis {

class MapSession;

class QgsLayerTreeStack : public pwb::ui_composite::ILayerTreeStack {
public:
    // The session stays owned by the caller; the stack only operates on
    // session->project()'s layer tree.
    explicit QgsLayerTreeStack(MapSession& session);

    bool groups_available() const override;

    void upsert_group(const std::string& group_id, const std::string& name,
                      const std::string& parent) override;
    void rename_group(const std::string& group_id,
                      const std::string& name) override;
    void remove_groups_except(
        const std::vector<std::string>& keep_ids) override;
    void move_layer_to_group(const std::string& layer_id,
                             const std::string& parent, int index) override;
    void move_group(const std::string& group_id, const std::string& parent,
                    int index) override;
    pwb::ui_composite::PlacementReport apply_tree_placements(
        const std::vector<pwb::ui_composite::PlacementOp>& ops) override;
    void set_group_visibility(const std::string& group_id,
                              bool visible) override;
    void set_group_expanded(const std::string& group_id,
                            bool expanded) override;

    std::optional<std::int64_t> begin_tree_update() override;
    pwb::ui_composite::TreeUpdateResult end_tree_update(
        std::int64_t token) override;

    // Monotonic tree revision (incremented once per programmatic batch
    // close; user edits observed from tree signals carry the revision at
    // observation time).
    std::uint64_t revision() const { return revision_; }

    // Domain observation snapshot for
    // LayerGroupController::observe_tree_nodes: DFS node array
    // [{"type":"group","id","name","expanded","visible","children":[…]},
    //  {"type":"layer","id"}] (top-first child order, group ids from
    // "pwb/group_id", layer ids from the join key).
    pwb::domain::Json tree_snapshot_nodes() const;

private:
    struct NodeIndex {
        std::map<std::string, QgsLayerTreeNode*> layer_nodes;  // by join key
        std::map<std::string, QgsLayerTreeNode*> group_nodes;  // by group id
    };
    NodeIndex build_index() const;
    bool in_window() const { return window_depth_ > 0; }
    void sync_close();  // single deferred sync + refresh at window close

    MapSession& session_;
    std::uint64_t revision_ = 0;
    int window_depth_ = 0;
    std::int64_t window_token_ = 0;
    bool render_flags_suppressed_ = false;
};

}  // namespace pwb::qgis
