// UI-08 — paleo_workbench/ui/pages/map_edit_scene.py port: the edit
// QGraphicsScene — load/select/move/vertex/line/label tools, undo stack,
// dirty flag, topology validation, snap, drafts and the navigation LOD.
//
// The heavy lifting stays in the frozen cores: EditCommandStack + command
// objects, MapDraftManager (Qt shell), MapSnapManager, the topology
// planners and the item models all come from Pwb::UiDataCore /
// Pwb::UiDataQt. This class is the orchestrator — it ports exactly the
// Python scene's wiring, tolerances and signal surface.
//
// Python→C++ surface mapping:
//  * bound document — ``PaleoMapDocument`` ↔ ``domain::Json*`` (same keys;
//    non-owning: the caller keeps the document alive while bound).
//  * ``topology_issues_changed`` — Signal(list) ↔ QVariantList of
//    QVariantMap (issue dicts converted at emit).
//  * optional<T>/nullopt ↔ Python None returns.
#pragma once

#include "pwb/domain/json.hpp"
#include "pwb/ui_data_core/map_edit_commands.hpp"
#include "pwb/ui_data_core/map_edit_geometry.hpp"
#include "pwb/ui_data_core/map_edit_snap.hpp"
#include "pwb/ui_data_qt/map_edit_draft_item.hpp"
#include "pwb/ui_pages_mapedit/feature_query_index.hpp"
#include "pwb/ui_pages_mapedit/map_edit_api.hpp"

#include <QGraphicsScene>
#include <QPointF>
#include <QRectF>
#include <QStringList>
#include <QVariantList>

#include <functional>
#include <map>
#include <memory>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

namespace pwb::ui_data_qt {
class FeatureItemApi;
class FaciesPolygonItem;
class LineItem;
class VertexHandleItem;
}  // namespace pwb::ui_data_qt

namespace pwb::ui_pages_mapedit {

// _DEFAULT_SCENE_RECT / _SCENE_PAD / pixel tolerances — the frozen
// constants from map_edit_scene.py.
inline const QRectF kDefaultSceneRect{-5000.0, -5000.0, 10000.0, 10000.0};
inline constexpr double kScenePad = 50.0;
inline constexpr double kDefaultSnapTol = 8.0;     // screen px
inline constexpr double kEdgeHitTol = 8.0;         // screen px (d² compare)
inline constexpr double kHandlePickTol = 4.0;      // screen px
inline constexpr double kFeaturePickTol = 8.0;     // screen px
inline constexpr double kAdjacencyGapTol = 0.5;    // world units
inline constexpr int kEditHistoryMax = 200;
inline constexpr int kCommandStackMaxDepth = 50;

class MapEditScene : public QGraphicsScene {
    Q_OBJECT
public:
    explicit MapEditScene(QObject* parent = nullptr);

    // --- public API (Python parity) --------------------------------------
    int feature_count() const { return static_cast<int>(items_by_id_.size()); }
    ui_data_qt::FeatureItemApi* item_by_id(const std::string& feature_id) const;
    ui_data_core::EditCommandStack* command_stack() { return &command_stack_; }

    std::string current_tool() const { return tool_; }
    void set_tool(const std::string& tool_id);

    bool is_dirty() const { return dirty_; }
    void set_dirty(bool dirty);

    QStringList selected_feature_ids() const;

    int vertex_handle_count() const {
        return static_cast<int>(vertex_handles_.size());
    }
    const std::vector<ui_data_qt::VertexHandleItem*>& vertex_handles() const {
        return vertex_handles_;
    }
    void set_active_vertex_index(std::optional<int> index) {
        active_vertex_index_ = index;
    }
    std::optional<int> active_vertex_index() const {
        return active_vertex_index_;
    }

    bool snap_enabled() const { return snap_manager_.enabled(); }
    void set_snap_enabled(bool enabled) { snap_manager_.set_enabled(enabled); }
    double snap_tolerance() const { return snap_manager_.tolerance(); }
    void set_snap_tolerance(double tol) { snap_manager_.set_tolerance(tol); }
    void set_reference_snap_points(const std::vector<ui_data_core::MapPoint>&
                                       points) {
        snap_manager_.set_reference_points(points);
    }

    void set_layer_visible(const std::string& kind, bool visible);
    bool layer_is_visible(std::string_view kind) const;

    std::vector<domain::Json> features_to_records() const;
    std::vector<domain::Json> export_features() const {
        return features_to_records();
    }

    // Geometry hit path: index candidates → api.hit_test. tolerance is
    // screen pixels converted to scene units at the current view scale.
    std::optional<std::string> hit_test_at(double x, double y,
                                           double tolerance = 0.0);
    std::map<std::string, int> hit_query_diagnostics() const {
        return hit_query_index_.diagnostics();
    }

    void clear_features();
    // Python ``clear()`` override parity (hides the non-virtual base —
    // callers through MapEditScene& get the cleanup path).
    void clear();

    // ``doc`` is a PaleoMapDocument-shaped Json object; nullptr unbinds.
    void load_document(domain::Json* doc);
    domain::Json* bound_document() const { return bound_document_; }

    void translate_features(const std::vector<std::string>& feature_ids,
                            double dx, double dy);

    bool apply_set_vertex(const std::string& feature_id, int index, double x,
                          double y, int part_index = 0, int ring_index = 0);
    bool apply_insert_vertex(const std::string& feature_id, int index,
                             double x, double y, int part_index = 0,
                             int ring_index = 0);
    bool apply_delete_vertex(const std::string& feature_id, int index,
                             int part_index = 0, int ring_index = 0);
    bool apply_property_change(const std::string& feature_id,
                               const std::string& key,
                               const domain::Json& value);

    // create_feature(record) → new feature id or nullopt.
    std::optional<std::string> create_feature(const domain::Json& record);

    int draft_point_count() const { return draft_manager_.point_count(); }
    std::optional<std::string> draft_kind() const {
        return draft_manager_.kind();
    }
    std::optional<std::string> finish_line_draft();
    std::optional<std::string> finish_facies_draft();
    void cancel_line_draft() { draft_manager_.cancel(); }

    void refresh_topology(const std::string& feature_id = std::string());
    // Structured issues for the bottom workbench and the save gate.
    domain::Json topology_issues();
    // (all_clear, issues) — the save-gate pair.
    std::pair<bool, domain::Json> validate_for_save();

    domain::Json rebuild_topology_forced(std::optional<double> snap_tol =
                                             std::nullopt);
    std::optional<std::string> merge_selected_facies();
    std::optional<std::vector<std::string>> split_selected_facies_by_line();

    bool undo();
    bool redo();

    // --- navigation display LOD -------------------------------------------
    void set_navigation_lod(bool active);
    bool navigation_lod() const { return navigation_lod_; }

    int snap_candidate_build_count() const {
        return snap_manager_.build_count();
    }

    // The geometry backend seam (shapely parity): nullptr reproduces the
    // no-shapely Python environment exactly — merge/split return nullopt and
    // shape-level validation issues stay empty.
    void set_geometry_backend(ui_data_core::MapGeometryBackend* backend) {
        backend_ = backend;
    }
    ui_data_core::MapGeometryBackend* geometry_backend() const {
        return backend_;
    }

    // Item-construction seam (Python ``item_from_record``): tests may
    // substitute a different factory; the default wraps the ui_data_qt
    // shells over ui_data_core::item_from_record models.
    using ItemFromRecordFn =
        std::function<ui_data_qt::FeatureItemApi*(const domain::Json&)>;
    void set_item_from_record_fn(ItemFromRecordFn fn) {
        item_from_record_fn_ = std::move(fn);
    }

    // Keyboard delegation seam (Python MapEditView.keyPressEvent → scene).
    void key_press(QKeyEvent* event) { keyPressEvent(event); }

signals:
    void selection_ids_changed(const QStringList& ids);
    void document_dirty_changed(bool dirty);
    void command_stack_changed();
    void topology_issues_changed(const QVariantList& issues);

protected:
    void mousePressEvent(QGraphicsSceneMouseEvent* event) override;
    void mouseMoveEvent(QGraphicsSceneMouseEvent* event) override;
    void mouseReleaseEvent(QGraphicsSceneMouseEvent* event) override;
    void mouseDoubleClickEvent(QGraphicsSceneMouseEvent* event) override;
    void keyPressEvent(QKeyEvent* event) override;
    void drawItems(QPainter* painter, int numItems, QGraphicsItem* items[],
                   const QStyleOptionGraphicsItem options[],
                   QWidget* widget = nullptr) override;

private:
    // --- internals --------------------------------------------------------
    void on_selection_changed();
    void emit_selection_ids();
    bool push_vertex_edit(const std::string& feature_id,
                          const ui_data_core::MapRing& old_coords,
                          const ui_data_core::MapRing& new_coords,
                          int part_index, int ring_index);
    void apply_coordinates(const std::string& feature_id,
                           const ui_data_core::MapRing& coordinates);
    void apply_ring_coordinates(const std::string& feature_id, int part_index,
                                int ring_index,
                                const ui_data_core::MapRing& coordinates);
    void apply_move_one(const std::string& feature_id, double dx, double dy);
    void apply_property(const std::string& feature_id, const std::string& key,
                        const domain::Json& value);
    void add_feature_from_record(const domain::Json& record);
    void remove_feature_by_id(const std::string& feature_id);
    void register_item(ui_data_qt::FeatureItemApi* item);
    ui_data_qt::FeatureItemApi* item_from_record(const domain::Json& record);

    void append_edit_log(const ui_data_core::EditCommand& command,
                         const std::string& action);
    void refresh_hit_entry(ui_data_qt::FeatureItemApi* item);
    double units_per_pixel() const;
    std::optional<std::string> single_editable_feature_id() const;

    void clear_vertex_handles();
    void refresh_vertex_handles();
    void sync_handle_positions(ui_data_qt::FeatureItemApi* item);
    ui_data_qt::VertexHandleItem* handle_at(const QPointF& pos) const;
    ui_data_qt::FeatureItemApi* feature_item_at(const QPointF& pos) const;

    void reset_drag_positions();
    void cancel_drag();
    void cancel_vertex_drag();
    void cancel_draft() { draft_manager_.cancel(); }

    std::pair<double, double> snap_xy(double x, double y);
    void invalidate_snap_candidates();
    std::vector<ui_data_core::SnapItem> snap_items() const;
    std::vector<ui_data_core::MapPoint> snap_candidates();

    void publish_topology_issues();
    domain::Json facies_geometry_issues(
        const ui_data_qt::FaciesPolygonItem* item);
    void apply_adjacency_warnings();
    void fit_scene_rect();

    // Item registry — insertion order preserved (Python dict semantics).
    std::unordered_map<std::string, ui_data_qt::FeatureItemApi*> items_by_id_;
    std::vector<std::string> item_order_;

    FeatureQueryIndex hit_query_index_;
    bool loading_features_ = false;
    std::string tool_ = "select";
    domain::Json* bound_document_ = nullptr;  // non-owning
    ui_data_core::EditCommandStack command_stack_;
    bool dirty_ = false;

    // Drag state.
    bool dragging_ = false;
    QPointF drag_origin_;
    QPointF drag_last_;
    std::vector<std::string> drag_ids_;

    // Vertex edit state.
    std::vector<ui_data_qt::VertexHandleItem*> vertex_handles_;
    std::optional<int> active_vertex_index_;
    int active_vertex_part_index_ = 0;
    int active_vertex_ring_index_ = 0;
    bool vertex_drag_ = false;
    std::optional<std::string> vertex_drag_feature_id_;
    std::optional<int> vertex_drag_index_;
    int vertex_drag_part_index_ = 0;
    int vertex_drag_ring_index_ = 0;
    QPointF vertex_drag_origin_;
    std::optional<ui_data_core::MapPoint> vertex_drag_start_xy_;

    std::map<std::string, bool> layer_visible_{
        {"facies", true}, {"well", true}, {"line", true}, {"label", true}};

    ui_data_core::MapSnapManager snap_manager_{kDefaultSnapTol};
    std::optional<SnapCandidateIndex> snap_index_;
    int snap_index_build_ = -1;

    bool navigation_lod_ = false;
    std::optional<domain::Json> last_published_issues_;
    std::map<std::string, domain::Json> topology_issue_cache_;
    ui_data_qt::MapDraftManager draft_manager_;
    ui_data_core::MapGeometryBackend* backend_ = nullptr;  // non-owning
    ItemFromRecordFn item_from_record_fn_;
    // Audit payloads for scene-constructed commands (the Python
    // ``hasattr`` reads resolved at construction time). The weak_ptr pins
    // the owner identity so a recycled address can never pick up a stale
    // payload.
    struct AuditPayload {
        std::weak_ptr<const ui_data_core::EditCommand> owner;
        domain::Json payload;
    };
    std::unordered_map<const ui_data_core::EditCommand*, AuditPayload>
        audit_payloads_;
};

}  // namespace pwb::ui_pages_mapedit
