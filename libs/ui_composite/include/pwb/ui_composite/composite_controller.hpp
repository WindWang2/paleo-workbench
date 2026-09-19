#pragma once

// Port of paleo_workbench/ui/workstation/composite_editing.py
// CompositeEditController (UI-13): 综合编修文档的用户矢量图层与数字化
// 会话。
//
// The core is Qt-free: the seven Python Signals become a
// CompositeControllerEvents sink (std::functions; the Qt shell forwards
// them to real signals), and every QGIS/native dependency sits behind an
// injected seam:
//
//   * CompositeCanvasHooks — duck-typed canvas (UnifiedMapCanvas /
//     QgisCanvasShim): zoom, current-layer push/introspection, snapping
//     config projection, native toggles, native-tool cancel.
//   * INativeEditing — NativeEditSessionController + bridge stack +
//     qgis_render_bridge geometry facade (mirror-buffer edit authority).
//     nullptr = no native sessions (Python-only path, honest fallbacks).
//   * ICompositeGeometryOps — vector_operations / geometry_operations /
//     geometry_service equivalents (shapely/bridge in Python; QgsGeometry
//     in the QGIS target). Absent = the "no engine" honest rejection.
//   * edit gate / role lookup — CompositeDocument stays the authority;
//     the controller never grows a second role/gate table.
//
// Qt-free.

#include <cstdint>
#include <functional>
#include <map>
#include <memory>
#include <optional>
#include <set>
#include <string>
#include <utility>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/ui_composite/crs_gate.hpp>
#include <pwb/ui_composite/map_interaction.hpp>
#include <pwb/ui_composite/map_snapshot.hpp>
#include <pwb/ui_composite/map_tools.hpp>
#include <pwb/ui_composite/templates.hpp>
#include <pwb/ui_composite/topology_checker.hpp>
#include <pwb/ui_composite/topology_service.hpp>
#include <pwb/ui_composite/vector_layer.hpp>

namespace pwb::ui_composite {

using pwb::domain::Json;

// ---------------------------------------------------------------------------
// Events sink (Python Signal parity — Qt shell forwards to real signals)
// ---------------------------------------------------------------------------

struct CompositeControllerEvents {
    std::function<void()> layers_changed;
    // (layer_id) — geometry/attributes changed.
    std::function<void(const std::string&)> content_changed;
    // 会话已提交 / 回滚（数据进入图层权威，宿主须立即同步工程文档）。
    std::function<void()> sessions_committed;
    // (message) — 全部层档手势波及邻层被门禁拒绝。
    std::function<void(const std::string&)> native_join_refused;
    // (violations Json array) — 地质守卫违规上报。
    std::function<void(const Json&)> geology_blocked;
    // (layer_id, feature_id) — 捕获工具落地一个新要素。
    std::function<void(const std::string&, const std::string&)>
        feature_captured;
    std::function<void()> state_changed;
};

// ---------------------------------------------------------------------------
// Canvas seam
// ---------------------------------------------------------------------------

// Duck-typed canvas hooks (UnifiedMapCanvas / QgisCanvasShim). Every
// member is optional — absence mirrors "attribute not callable" Python
// fallbacks.
struct CompositeCanvasHooks {
    std::function<double()> map_units_per_pixel;
    std::function<void(double, const MapPoint&)> zoom_by;
    std::function<void(const std::string&)> set_current_layer;
    std::function<std::string()> current_layer_doc_id;
    // set_snapping_config: returns false when the push is rejected
    // (controller then flips snapping.enabled off — #1276 parity).
    std::function<bool(const Json&)> set_snapping_config;
    std::function<void(bool)> set_vertex_edit_scope;
    std::function<void(bool)> set_tracing_enabled;
    std::function<bool()> native_tool_busy;
    std::function<void()> cancel_native_tool;
    std::function<void()> focus;
    // Native-canvas facts: canvas_address() non-zero ⇔ hasattr(canvas,
    // "canvas_address") in Python (native-only tool pre-checks).
    std::function<std::uintptr_t()> canvas_address;

    bool attached() const { return static_cast<bool>(map_units_per_pixel); }
    bool native_canvas() const {
        return canvas_address && canvas_address() != 0;
    }
    double units_per_pixel() const {
        if (map_units_per_pixel) {
            try {
                double v = map_units_per_pixel();
                if (v > 0.0) return v;
            } catch (const std::exception&) {
            }
        }
        return 1.0;
    }
};

// ---------------------------------------------------------------------------
// Native edit session seam
// ---------------------------------------------------------------------------

// NativeEditSessionController + bridge stack + qgis_render_bridge
// geometry facade. All mirror-layer operations route through here; the
// QGIS target wires QgsVectorLayer edit buffers; tests stub; nullptr in
// the controller = Python-only path.
class INativeEditing {
public:
    virtual ~INativeEditing() = default;

    // bridge_supports(stack) parity — does the wired bridge offer mirror
    // edit sessions at all.
    virtual bool bridge_supports() const = 0;
    virtual bool is_open(const std::string& layer_id) const = 0;
    virtual std::vector<std::string> session_layer_ids() const = 0;
    // open(stack, layer, gate, canvas_address): gate is the controller's
    // can_edit_layer; return (ok, reason).
    virtual std::pair<bool, std::string> open(
        const std::string& layer_id,
        const std::function<std::pair<bool, std::string>(
            const std::string&)>& gate) = 0;
    // commit_all(gate, topology, geology, on_committed) — 全或无.
    // geology: optional fn(records) → violations Json array (already
    // computed by the controller); on_committed(layer_id).
    virtual std::pair<bool, std::string> commit_all(
        const std::function<std::pair<bool, std::string>(
            const std::string&)>& gate,
        TopologyService& topology,
        const std::function<Json(const Json&)>& geology,
        const std::function<void(const std::string&)>& on_committed) = 0;
    virtual std::pair<bool, std::string> rollback(
        const std::string& layer_id) = 0;
    // pending_changes: mirror_layer_dirty; nullopt = no query surface.
    virtual std::optional<bool> pending_changes(
        const std::string& layer_id) const = 0;
    virtual bool undo_gesture() = 0;
    virtual bool redo_gesture() = 0;
    // gestures.finish(gesture_id, undo_text=, layer_ids=).
    virtual void finish_gesture(const std::string& gesture_id,
                                const std::string& undo_text,
                                const std::vector<std::string>& layer_ids) = 0;
    // Mirror readback + writes (GeoJSON record/field envelopes).
    virtual std::vector<Json> readback_features(
        const std::string& layer_id) = 0;
    virtual Json mirror_layer_schema(const std::string& layer_id) = 0;
    virtual std::vector<Json> mirror_features(
        const std::string& layer_id) = 0;
    virtual std::pair<bool, std::string> set_feature_attributes(
        const std::string& layer_id,
        const std::vector<std::string>& feature_ids,
        const Json& payload) = 0;
    // Digitize routing: error string ("" = success).
    virtual std::string add_mirror_feature(const std::string& layer_id,
                                           const Json& feature) = 0;
    // capability probes (callable checks on the bridge).
    virtual bool has_merge() const = 0;
    virtual bool has_split() const = 0;
    virtual bool has_fault_cut() const = 0;
    virtual bool has_shared_boundary_reshape() const = 0;
    virtual std::string merge_mirror_features(
        const std::string& layer_id,
        const std::vector<std::string>& feature_ids,
        const Json& payload) = 0;
    virtual std::string split_mirror_features(
        const std::string& layer_id, const Json& curve,
        const std::vector<std::string>& feature_ids) = 0;
    virtual std::string fault_cut_mirror_features(
        const std::string& layer_id, const Json& curve,
        const std::vector<std::string>& feature_ids,
        const Json& options) = 0;
    // set_map_tool(address, kind) — route the digitizer for split etc.
    virtual void set_map_tool(std::uintptr_t canvas_address,
                              const std::string& kind) = 0;
    // align_publish_ledger_for_layer(stack, layer, metadata).
    virtual void align_publish_ledger(
        const std::string& layer_id,
        const std::map<std::string, std::string>& metadata) = 0;
};

// ---------------------------------------------------------------------------
// Python-session geometry operations seam
// ---------------------------------------------------------------------------

// vector_operations / geometry_operations / geometry_service parity.
// Each op mirrors one Python function; a missing seam mirrors the
// shapely/bridge-absent environment (callers produce the same honest
// rejections). Operations mutate the session only through the
// controller's edit_source scopes.
class ICompositeGeometryOps {
public:
    virtual ~ICompositeGeometryOps() = default;

    // vector_operations.merge_selected_polygons(session, sorted_ids)
    // → new feature id (throws on failure).
    virtual std::string merge_selected_polygons(
        VectorEditSession& session,
        const std::vector<std::string>& sorted_ids) = 0;
    // vector_operations.split_polygon_by_line(session, polygon_id,
    // line_feature) → new feature ids.
    virtual std::vector<std::string> split_polygon_by_line(
        VectorEditSession& session, const std::string& polygon_id,
        const VectorFeature& line_feature) = 0;
    // geometry_service.make_geometry_valid(geometry).
    virtual Json make_geometry_valid(const Json& geometry) = 0;
    // geometry_operations.multipart_to_singlepart(geometry) → array of
    // singlepart geometries.
    virtual std::vector<Json> multipart_to_singlepart(
        const Json& geometry) = 0;
    // geometry_operations.singlepart_to_multipart(geometries).
    virtual Json singlepart_to_multipart(
        const std::vector<Json>& geometries) = 0;
    // geometry_operations.trim_line / extend_line_to_boundary.
    virtual Json trim_line(const Json& geometry, const Json& boundary,
                           const std::string& keep) = 0;
    virtual Json extend_line_to_boundary(const Json& geometry,
                                         const Json& boundary,
                                         double max_extend) = 0;
    // geometry_operations.reverse_geometry / simplify / smooth /
    // offset_curve (simplify/smooth/offset return geometry).
    virtual Json reverse_geometry(const Json& geometry) = 0;
    virtual Json simplify(const Json& geometry, double tolerance) = 0;
    virtual Json smooth(const Json& geometry, int iterations,
                        double offset) = 0;
    virtual Json offset_curve(const Json& geometry, double distance) = 0;
    // Shapely affinity rotate/scale around a center point (M5-B
    // transform_selection).
    virtual Json rotate(const Json& geometry, double angle_degrees,
                        const MapPoint& origin) = 0;
    virtual Json scale(const Json& geometry, double xfact, double yfact,
                       const MapPoint& origin) = 0;
    // union centroid over geometries (transform_selection center).
    virtual MapPoint union_centroid(const std::vector<Json>& geoms) = 0;
    // native.geometry.reshape(target, line) — reshape applier seam.
    virtual std::optional<Json> reshape(const Json& target,
                                        const Json& line) = 0;
    // native.geometry.add_part / delete_part.
    virtual std::optional<Json> add_part(const Json& target,
                                         const Json& part) = 0;
    virtual std::optional<Json> delete_part(const Json& geometry,
                                            int part_index) = 0;
};

// ---------------------------------------------------------------------------
// Geology gate seam (geotopo Ticket 4/5)
// ---------------------------------------------------------------------------

// run_geology_gate(records, roles) → violations [{code,message,severity}]
using GeologyGateFn = std::function<Json(
    const std::map<std::string, std::vector<Json>>& records,
    const std::map<std::string, std::string>& roles)>;

// ---------------------------------------------------------------------------
// CompositeEditController
// ---------------------------------------------------------------------------

// 综合编修文档的用户矢量图层与数字化会话（Qt-free core）。
class CompositeEditController {
public:
    explicit CompositeEditController(std::string project_crs = "");

    std::string project_crs;
    MapToolController tools;
    CompositeControllerEvents events;

    // M2 §4 三开关（随编辑会话持久化）。
    bool vertex_all_layers = true;
    bool avoid_intersections_enabled = true;
    bool tracing_enabled = false;
    // EditDelta 引擎溯源 token（宿主在桥探测后注入）。
    std::string qgis_capability_token = "unavailable";
    // 宿主注入的多图层识别回调（Identify Results 面板）。
    std::function<void(const MapPoint&)> identify_delegate;
    // 状态条阻断任务标签（tool_context_inputs 的 blocking_task）。
    std::string blocking_task_label;

    // -- 注入 seams ------------------------------------------------------------
    // RAW/锁定门禁 layer_id → (allowed, reason)；无注入 = 全放行。
    using EditGate = std::function<std::pair<bool, std::string>(
        const std::string&)>;
    void set_edit_gate(EditGate gate) { edit_gate_ = std::move(gate); }
    std::pair<bool, std::string> can_edit_layer(
        const std::string& layer_id) const;
    // 角色查询 layer_id → role value（stage membership 权威）。
    using RoleLookup =
        std::function<std::optional<std::string>(const std::string&)>;
    void set_role_lookup(RoleLookup lookup) {
        role_lookup_ = std::move(lookup);
    }
    // 原生合并确认（MergeFeaturesDialog payload seam）：records → payload
    // （nullopt = 用户取消）。
    using MergeConfirmFn =
        std::function<std::optional<Json>(const std::vector<Json>&)>;
    void set_merge_confirm(MergeConfirmFn fn) {
        merge_confirm_ = std::move(fn);
    }
    // 桥 capability manifest 的 features 集（_bridge_snapping_features）。
    using BridgeFeaturesFn = std::function<std::set<std::string>()>;
    void set_bridge_features(BridgeFeaturesFn fn) {
        bridge_features_ = std::move(fn);
    }
    // 地质门（run_geology_gate）。
    void set_geology_gate(GeologyGateFn fn) {
        geology_gate_ = std::move(fn);
    }
    // 几何算子缝（无注入 = 无引擎环境）。
    void set_geometry_ops(std::shared_ptr<ICompositeGeometryOps> ops) {
        geometry_ops_ = std::move(ops);
    }
    ICompositeGeometryOps* geometry_ops() const {
        return geometry_ops_.get();
    }
    // 原生编辑会话缝（无注入 = Python-only）。
    void set_native_editing(std::shared_ptr<INativeEditing> native) {
        native_editing_ = std::move(native);
    }
    INativeEditing* native_editing() const { return native_editing_.get(); }
    // CRS parseability probe（_crs_parseable 注入；nullptr = 非空即合法）。
    void set_crs_validator(CrsValidator v) { crs_validator_ = std::move(v); }

    // -- 画布绑定 ---------------------------------------------------------------
    void attach_canvas(const CompositeCanvasHooks& canvas);
    void detach_canvas() { canvas_ = CompositeCanvasHooks{}; }
    const CompositeCanvasHooks& canvas() const { return canvas_; }

    // -- 角色/捕获语义 -----------------------------------------------------------
    void set_layer_role(const std::string& layer_id,
                        const std::string& role_value);
    std::string role_of_layer(const std::string& layer_id) const;
    std::optional<bool> snapping_role_recommended(
        const VectorLayer* layer) const;
    Json capture_defaults_for_role(const std::string& layer_id) const;
    std::optional<std::string> apply_capture_spec(
        const std::string& layer_id);

    // -- 图层 CRUD ---------------------------------------------------------------
    std::vector<std::string> layer_ids() const;
    VectorLayer* layer(const std::string& layer_id);
    const VectorLayer* layer(const std::string& layer_id) const;
    std::string kind_of(const std::string& layer_id) const;
    static bool is_composite_layer(const std::string& layer_id);
    VectorLayer& create_layer(const std::string& name,
                              const std::string& kind,
                              const std::string& geo_template = "",
                              const std::string& role = "");
    void rename_layer(const std::string& layer_id,
                      const std::string& name);
    std::string layer_template(const std::string& layer_id) const;
    Json layer_schema(const std::string& layer_id) const;
    std::string layer_role(const std::string& layer_id) const;
    void set_snapping_scope(bool current_layer_only);
    std::pair<bool, std::string> apply_render_preset(
        const std::string& layer_id);
    void set_layer_style(const std::string& layer_id, const Json& style);
    VectorLayer* duplicate_layer(const std::string& layer_id,
                                 bool notify = true);
    void remove_layer(const std::string& layer_id);

    // -- 工程持久化 ----------------------------------------------------------------
    // project record payloads are Json (host maps to UserVectorLayer /
    // mapping_workspace dicts) — keeps the core free of project models.
    bool load_from_project(
        const std::vector<Json>& user_vector_layers,
        const Json& mapping_workspace, const Json& workarea_boundary);
    std::vector<Json> sync_to_project(Json& mapping_workspace) const;

    // -- 活动图层与编辑会话 ------------------------------------------------------------
    const std::optional<std::string>& active_layer_id() const {
        return active_layer_id_;
    }
    VectorLayer* active_layer();
    std::optional<std::string> topmost_visible_layer_id() const;
    TopologyService& topology() { return topology_; }
    std::vector<Json> gate_topology_issues(const VectorLayer& layer);
    std::vector<Json> run_topology_checks();
    bool editing() const;
    std::string current_canvas_layer_id() const;
    bool repush_canvas_current_layer();
    void set_active_layer(const std::optional<std::string>& layer_id);
    std::map<std::string, std::tuple<int64_t, int64_t,
                                     std::set<std::string>>>
    snapshot_changed_hints() const;
    const std::optional<std::pair<std::string, std::string>>&
    last_switch_block_reason() const {
        return last_switch_block_reason_;
    }
    void note_tree_selection(const std::optional<std::string>& node_id);
    EditTargetSnapshot edit_targets() const;
    void start_editing();
    std::pair<VectorEditSession*, std::string> ensure_layer_session(
        const std::string& layer_id);
    const std::optional<CrsDomainCheck>& last_crs_gate_check() const {
        return last_crs_gate_check_;
    }
    bool apply_crs_fix(const std::string& layer_id,
                       const std::string& mode);
    std::pair<bool, std::string> apply_project_crs(
        const std::string& crs);
    std::set<std::string> facies_field_names(
        const std::string& layer_id) const;
    std::pair<bool, std::string> apply_facies_selection(
        const std::string& layer_id,
        const std::vector<std::string>& feature_ids,
        const Json& selection);
    void import_layer_features(const std::string& layer_id,
                               const std::vector<VectorFeature>& features);
    std::optional<std::string> save_edits();
    bool commit_native_capture(const Json& geometry);
    void cancel_native_capture();
    void join_native_layers(const std::vector<std::string>& doc_ids);
    void set_vertex_scope(bool all_layers);
    void set_avoid_intersections(bool enabled);
    void set_tracing(bool enabled);
    void record_native_gesture(const Json& payload);
    void note_compound_layer(const std::string& layer_id);
    // compound_macro parity: begin/end RAII — gestures and digitize
    // captures inside the block merge into ONE gesture (Ctrl+Z 跨层同步
    // 撤销). Nested blocks merge into the outer macro.
    void begin_compound_macro(const std::string& undo_text);
    void end_compound_macro();
    void rollback_edits();
    std::pair<int, std::vector<std::string>> flush_edit_sessions();
    void set_qgis_capability_token(const std::string& token) {
        qgis_capability_token = token.empty() ? "unavailable" : token;
    }

    // -- 工具装配 -----------------------------------------------------------------
    void activate_tool(const std::string& action_id);
    void set_snapping(bool enabled);
    void repush_snapping() { push_snapping_config(); }
    SnappingService& snapping() { return snapping_; }
    const SnappingService& snapping() const { return snapping_; }
    void set_topology(bool enabled);
    bool topology_enabled() const { return topology_.enabled; }
    std::vector<Json> validate_open_session_topology();
    std::vector<Json> validate_active_layer_topology();
    int repair_layer_geometries(const std::string& layer_id);

    // -- 几何命令 ------------------------------------------------------------------
    std::pair<bool, std::string> geometry_command_at_point(
        const std::string& command_id, const MapPoint& point);
    std::pair<bool, std::string> geometry_command(
        const std::string& command_id,
        const std::optional<Json>& curve = std::nullopt);
    std::pair<bool, std::string> transform_selection(
        const std::string& op_id, double angle_degrees = 0.0,
        double xfact = 1.0, double yfact = 0.0 /* 0 = use xfact */);
    std::pair<bool, std::string> clipboard_copy_selection(bool cut = false);
    std::pair<bool, std::string> clipboard_paste();
    std::pair<bool, std::string> fill_ring_at_point(const MapPoint& point);
    std::pair<bool, std::string> trim_extend_selection(
        const std::string& op_id, const Json& boundary,
        const std::string& keep = "inside", double max_extend = 1e9);
    std::pair<bool, std::string> snap_geometries(
        std::optional<double> tolerance = std::nullopt);
    std::pair<bool, std::string> selection_geometry_op(
        const std::string& op_id, double tolerance = 0.5,
        int iterations = 1, double offset = 0.25, double distance = 1.0);

    // -- 多图层识别 ------------------------------------------------------------------
    std::vector<Json> identify_all(
        const MapPoint& point,
        const std::vector<MapLayerSnapshot>& base_layers = {});
    bool locate_identify_result(const Json& result);
    void cancel_active_tool();
    void selection_command(const std::string& command_id);
    bool edit_command(const std::string& command_id);

    // -- 快照与状态 --------------------------------------------------------------------
    std::vector<MapLayerSnapshot> snapshot_layers(
        const std::map<std::string, MapLayerSnapshot>& display = {});
    void apply_display_state(
        const std::vector<MapLayerSnapshot>& display_layers,
        bool include_names = false);
    tool_policy::ToolContextSnapshot tool_context_inputs() const;
    Json overlay_state() const;

    // -- display/内部状态读口（面板/持久化用） ----------------------------------------
    const std::map<std::string, std::pair<bool, double>>& display() const {
        return display_;
    }
    void set_display(const std::string& layer_id, bool visible,
                     double opacity) {
        display_[layer_id] = {visible, opacity};
    }
    const std::map<std::string, std::string>& layer_roles() const {
        return layer_roles_;
    }
    const std::map<std::string, std::string>& kinds() const {
        return kinds_;
    }

private:
    // internals ------------------------------------------------------------
    std::pair<bool, std::string> crs_domain_gate(const VectorLayer& layer);
    bool native_session_eligible(const VectorLayer& layer);
    VectorEditSession& open_session(VectorLayer& layer);
    void retire_session_on_target_switch(VectorLayer& previous);
    void rebind_active_tool();
    double tolerance() const;
    MapPoint snap_point(const MapPoint& point);
    void push_snapping_config();
    void push_native_edit_toggles();
    std::set<std::string> bridge_snapping_features() const;
    std::optional<std::string> commit_native_sessions();
    bool geology_gate_enabled() const;
    std::vector<Json> collect_geology_violations(
        const std::optional<Json>& records = std::nullopt);
    void on_native_committed(VectorLayer& layer);
    std::function<bool(const Json&)> make_reshape_applier(
        VectorEditSession* session, const std::string& feature_id);
    bool apply_captured_ring(VectorEditSession* session,
                             const std::string& feature_id,
                             const Json& ring_geometry);
    std::function<bool(const Json&)> make_part_applier(
        VectorEditSession* session, const std::string& feature_id);
    bool apply_captured_part(VectorEditSession* session,
                             const std::string& feature_id,
                             const Json& part_geometry);
    std::pair<bool, std::string> native_geometry_command(
        const std::string& command_id, VectorLayer& layer,
        const std::optional<Json>& curve);
    std::pair<bool, std::string> native_fault_cut(
        VectorLayer& layer, const std::optional<Json>& curve);
    std::vector<Json> selected_native_records(VectorLayer& layer);
    std::pair<bool, std::string> native_merge(VectorLayer& layer);
    std::pair<bool, std::string> native_split_begin(VectorLayer& layer);
    bool commit_native_split(const Json& geometry);
    std::pair<bool, std::string> explode_selected_multipart(
        VectorLayer& layer, VectorEditSession& session);
    std::pair<bool, std::string> collect_selected_multipart(
        VectorLayer& layer, VectorEditSession& session);
    std::pair<bool, std::string> ring_and_part_commands(
        const std::string& command_id, const Json& pick_point);
    struct SplitInputs {
        VectorLayer* polygon_layer;
        std::string polygon_id;
        VectorFeature line_feature;
    };
    std::optional<SplitInputs> split_inputs();
    std::pair<int, bool> selection_geometry_facts(
        const VectorLayer& layer, const VectorEditSession* session) const;
    void refresh_error_count_quiet(VectorLayer& layer);

    // state ------------------------------------------------------------------
    SnappingService snapping_;
    TopologyService topology_;
    std::map<std::string, std::unique_ptr<VectorLayer>> layers_;
    std::map<std::string, std::string> kinds_;
    std::map<std::string, std::string> templates_;
    std::map<std::string, Json> schemas_;
    std::map<std::string, std::string> layer_roles_;
    std::map<std::string, std::pair<bool, double>> display_;
    std::optional<std::string> tree_selection_;
    std::optional<std::pair<std::string, std::string>>
        last_switch_block_reason_;
    std::optional<std::string> active_layer_id_;
    std::string active_tool_action_ = "pan";
    CompositeCanvasHooks canvas_;
    std::shared_ptr<INativeEditing> native_editing_;
    std::shared_ptr<ICompositeGeometryOps> geometry_ops_;
    std::optional<CrsDomainCheck> last_crs_gate_check_;
    std::optional<Json> compound_capture_;
    std::vector<std::string> compound_capture_layers_;
    std::string compound_capture_undo_text_;
    // (source layer id, source CRS, [(geometry, attributes)])
    std::optional<
        std::tuple<std::string, std::string, std::vector<Json>>>
        feature_clipboard_;
    std::optional<std::string> pending_native_split_;
    // 修订键控序列化缓存：(revision, session*, features, extent, records)。
    struct RecordsCacheEntry {
        int64_t revision = 0;
        const VectorEditSession* session = nullptr;
        std::vector<Json> features;
        MapExtent extent{0.0, 0.0, 1.0, 1.0};
        std::map<std::string, Json> records;
    };
    std::map<std::string, RecordsCacheEntry> records_cache_;
    std::map<std::string,
             std::tuple<int64_t, int64_t, std::set<std::string>>>
        changed_hints_;
    mutable std::map<std::string, std::pair<int64_t, std::vector<Json>>>
        persist_cache_;
    EditGate edit_gate_;
    RoleLookup role_lookup_;
    MergeConfirmFn merge_confirm_;
    BridgeFeaturesFn bridge_features_;
    GeologyGateFn geology_gate_;
    CrsValidator crs_validator_;
    // memo for selection_geometry_facts.
    mutable std::map<
        std::tuple<const void*, int64_t, std::set<std::string>>,
        std::pair<int, bool>>
        selection_facts_cache_;
};

// 模块常量（Python parity）。
inline const std::string& composite_layer_id_prefix() {
    static const std::string prefix = "composite:";
    return prefix;
}
const std::set<std::string>& layer_bound_tools();
const std::map<std::string, std::string>& kind_bound_tools();
// 快照 metadata["role"] 不落盘的角色。
const std::set<std::string>& snapshot_roleless_roles();
// LayerRole/原始字符串 → 快照 metadata 用角色值（"" = 无角色）。
std::string normalize_layer_role(const std::string& role);
// pick_topmost_visible_layer_id 纯函数。
std::optional<std::string> pick_topmost_visible_layer_id(
    const std::vector<std::string>& layer_ids_bottom_up,
    const std::set<std::string>& visible_ids);

}  // namespace pwb::ui_composite
