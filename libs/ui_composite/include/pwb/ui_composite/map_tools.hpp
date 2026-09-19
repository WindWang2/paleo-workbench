#pragma once

// Port of paleo_workbench/mapping/map_tools.py (UI-13): QGIS-inspired
// renderer-independent map-tool state machines.
//
// Execution-path status (Goal V7): on hosts with the QGIS bridge the
// native QgsMapTool layer (canvas shim → native tools) is the
// *production* interaction executor; the mouse-driven state machines
// here are the explicit **fallback** for the renderer-independent
// canvas, headless tests and hosts without the bridge. The commit_*
// entry points are the native tools' landing zone into the session
// authority and stay production code. The fallback must not gain
// professional capabilities the native path lacks (Goal V7 §5);
// divergences are defects.
//
// Qt-free.

#include <functional>
#include <memory>
#include <optional>
#include <set>
#include <string>
#include <vector>

#include <pwb/ui_composite/vector_layer.hpp>

namespace pwb::ui_composite {

// Modifier name set ("ctrl" / "shift" / …) as lowercase strings.
using Modifiers = std::set<std::string>;

// ---------------------------------------------------------------------------
// MapTool base
// ---------------------------------------------------------------------------

// One exclusive interactive operation; rendering overlays stay external.
class MapTool {
public:
    virtual ~MapTool() = default;

    std::string tool_id = "tool";
    // native_digitize_kind: canvas-shim routing key for tools whose
    // interaction lives entirely in the native layer (empty = fallback
    // state machine only).
    std::string native_digitize_kind;
    // Whether a handled operation mutates document data. Hosts use this
    // to distinguish data edits (composition resync) from pure pointer/
    // selection feedback (overlay repaint only). Session-bound tools
    // override through edits_data().
    virtual bool edits_data() const { return false; }

    bool active() const { return active_; }
    virtual void activate() { active_ = true; }
    virtual void deactivate() {
        cancel();
        active_ = false;
    }

    virtual bool mouse_press(const MapPoint& point,
                             const std::string& button = "left",
                             const Modifiers& modifiers = {});
    virtual bool mouse_move(const MapPoint& point,
                            const Modifiers& modifiers = {});
    virtual bool mouse_release(const MapPoint& point,
                               const std::string& button = "left",
                               const Modifiers& modifiers = {});
    virtual bool double_click(const MapPoint& point,
                              const Modifiers& modifiers = {});
    virtual bool key_press(const std::string& key);
    virtual bool cancel() { return false; }

private:
    bool active_ = false;
};

// Exclusive activation state shared by toolbar/menu/context actions.
class MapToolController {
public:
    MapTool* active_tool() const { return active_tool_.get(); }
    std::string active_tool_id() const {
        return active_tool_ ? active_tool_->tool_id : std::string{};
    }
    void set_active_tool(std::shared_ptr<MapTool> tool);
    bool key_press(const std::string& key);

private:
    std::shared_ptr<MapTool> active_tool_;
};

// ---------------------------------------------------------------------------
// Concrete tools
// ---------------------------------------------------------------------------

class PanTool : public MapTool {
public:
    PanTool() { tool_id = "pan"; }
};

// 断层截断占位工具——数字化与切割全在原生 PwbFaultCutTool；宿主侧不承
// 载任何鼠标语义（非原生画布一律拒绝激活）。
class FaultCutTool : public MapTool {
public:
    FaultCutTool() {
        tool_id = "fault_cut";
        native_digitize_kind = "faultCut";
    }
};

// 共边重塑占位工具——C++ PwbBoundaryReshapeTool（kind=boundaryReshape）。
class BoundaryReshapeTool : public MapTool {
public:
    BoundaryReshapeTool() {
        tool_id = "boundary_reshape";
        native_digitize_kind = "boundaryReshape";
    }
};

// A one-shot zoom tool; the canvas owns its viewport transform.
class ZoomTool : public MapTool {
public:
    ZoomTool(std::function<void(double, const MapPoint&)> zoom,
             double factor, std::string id);
    bool mouse_press(const MapPoint& point, const std::string& button,
                     const Modifiers& modifiers) override;

private:
    std::function<void(double, const MapPoint&)> zoom_;
    double factor_;
};

class MeasureDistanceTool : public MapTool {
public:
    // geod: optional geodesic probe (crs_contract.geod_for_crs parity) —
    // returns {azimuth1, azimuth2, distance-meters} or nullopt.
    using Geod = std::function<std::optional<std::tuple<double, double,
                                                        double>>(
        double, double, double, double)>;
    MeasureDistanceTool(
        std::function<void(double)> measurement_ready = nullptr,
        Geod geod = nullptr) {
        tool_id = "measure_distance";
        measurement_ready_ = std::move(measurement_ready);
        geod_ = std::move(geod);
    }

    std::optional<MapPoint> start;
    std::optional<MapPoint> current;
    std::optional<double> last_distance;
    bool last_geodesic = false;

    std::vector<MapPoint> points() const;
    bool mouse_press(const MapPoint& point, const std::string& button,
                     const Modifiers& modifiers) override;
    bool mouse_move(const MapPoint& point,
                    const Modifiers& modifiers) override;
    bool cancel() override;

private:
    double measure(const MapPoint& a, const MapPoint& b);
    std::function<void(double)> measurement_ready_;
    Geod geod_;
};

class SelectTool : public MapTool {
public:
    SelectTool(VectorLayer& layer,
               std::function<std::optional<std::string>(const MapPoint&)>
                   identify) {
        tool_id = "select";
        layer_ = &layer;
        identify_ = std::move(identify);
    }

    VectorLayer& layer() const { return *layer_; }
    bool mouse_press(const MapPoint& point, const std::string& button,
                     const Modifiers& modifiers) override;
    // QGIS 原生选择工具结果落图层选集（M3）：无=替换，Ctrl=并集，
    // Shift=差集，Ctrl+Shift=交集。
    bool commit_selection(const std::vector<std::string>& feature_ids,
                          const Modifiers& modifiers = {});

private:
    VectorLayer* layer_;
    std::function<std::optional<std::string>(const MapPoint&)> identify_;
};

class RectangleSelectTool : public MapTool {
public:
    RectangleSelectTool(
        VectorLayer& layer,
        std::function<std::set<std::string>(const MapPoint&,
                                            const MapPoint&)>
            select_rectangle) {
        tool_id = "select_rectangle";
        layer_ = &layer;
        select_rectangle_ = std::move(select_rectangle);
    }

    VectorLayer& layer() const { return *layer_; }
    bool mouse_press(const MapPoint& point, const std::string& button,
                     const Modifiers& modifiers) override;
    bool mouse_release(const MapPoint& point, const std::string& button,
                       const Modifiers& modifiers) override;
    bool cancel() override;

private:
    VectorLayer* layer_;
    std::function<std::set<std::string>(const MapPoint&, const MapPoint&)>
        select_rectangle_;
    std::optional<MapPoint> start_;
};

// 无层识别工具（无编修图层时 identify 的 fallback 绑定）：只把点击喂
// 给多图层识别回调，不碰任何图层选集。
class IdentifyTool : public MapTool {
public:
    explicit IdentifyTool(std::function<void(const MapPoint&)> identify) {
        tool_id = "identify";
        identify_ = std::move(identify);
    }
    bool mouse_press(const MapPoint& point, const std::string& button,
                     const Modifiers& modifiers) override;

private:
    std::function<void(const MapPoint&)> identify_;
};

// ---------------------------------------------------------------------------
// Capture tools (session-bound)
// ---------------------------------------------------------------------------

class CaptureTool : public MapTool {
public:
    std::string geometry_type;  // Point|LineString|Polygon
    VectorEditSession* session = nullptr;
    std::vector<MapPoint> points;

    CaptureTool(
        VectorEditSession* session, std::string id, std::string geometry,
        std::function<MapPoint(const MapPoint&)> snap = nullptr,
        Json attributes = Json::object(),
        std::function<void(const std::string&)> on_captured = nullptr,
        std::function<std::string()> feature_id_factory = nullptr);

    // 采集中（points 非空）只动 overlay；要素落地/会话回空后才需要全
    // 量重组合快照。
    bool edits_data() const override { return points.empty(); }

    bool mouse_press(const MapPoint& point, const std::string& button,
                     const Modifiers& modifiers) override;
    bool mouse_move(const MapPoint& point,
                    const Modifiers& modifiers) override;
    bool double_click(const MapPoint& point,
                      const Modifiers& modifiers) override;
    bool cancel() override;
    virtual bool finish();

    // QGIS 原生采点工具的完成几何直接落会话（M3）。
    bool commit_geometry(const Json& geometry);

protected:
    bool finish_with_geometry(Json geometry);
    std::function<MapPoint(const MapPoint&)> snap_;
    Json default_attributes_;
    std::function<void(const std::string&)> on_captured_;
    std::function<std::string()> feature_id_factory_;
    void notify_captured(const std::string& feature_id);
};

class AddPointTool : public CaptureTool {
public:
    using CaptureTool::CaptureTool;
    AddPointTool(VectorEditSession* session,
                 std::function<MapPoint(const MapPoint&)> snap = nullptr,
                 Json attributes = Json::object(),
                 std::function<void(const std::string&)> on_captured =
                     nullptr);
};
class AddLineTool : public CaptureTool {
public:
    AddLineTool(VectorEditSession* session,
                std::function<MapPoint(const MapPoint&)> snap = nullptr,
                Json attributes = Json::object(),
                std::function<void(const std::string&)> on_captured =
                    nullptr);
};
class AddPolygonTool : public CaptureTool {
public:
    AddPolygonTool(VectorEditSession* session,
                   std::function<MapPoint(const MapPoint&)> snap = nullptr,
                   Json attributes = Json::object(),
                   std::function<void(const std::string&)> on_captured =
                       nullptr);
};

// 两步交互 shape 工具（第二次左键落下即 finish）。
class TwoClickShapeTool : public CaptureTool {
public:
    using CaptureTool::CaptureTool;
    bool mouse_press(const MapPoint& point, const std::string& button,
                     const Modifiers& modifiers) override;
};
class ThreeClickShapeTool : public CaptureTool {
public:
    using CaptureTool::CaptureTool;
    bool mouse_press(const MapPoint& point, const std::string& button,
                     const Modifiers& modifiers) override;
};

class RectangleCaptureTool : public TwoClickShapeTool {
public:
    RectangleCaptureTool(
        VectorEditSession* session,
        std::function<MapPoint(const MapPoint&)> snap = nullptr,
        Json attributes = Json::object(),
        std::function<void(const std::string&)> on_captured = nullptr);
    bool finish() override;
};

class CircleCaptureTool : public TwoClickShapeTool {
public:
    static constexpr int kSegments = 64;
    CircleCaptureTool(
        VectorEditSession* session,
        std::function<MapPoint(const MapPoint&)> snap = nullptr,
        Json attributes = Json::object(),
        std::function<void(const std::string&)> on_captured = nullptr);
    bool finish() override;
};

class ArcCaptureTool : public ThreeClickShapeTool {
public:
    static constexpr int kSegments = 32;
    ArcCaptureTool(
        VectorEditSession* session,
        std::function<MapPoint(const MapPoint&)> snap = nullptr,
        Json attributes = Json::object(),
        std::function<void(const std::string&)> on_captured = nullptr);
    bool finish() override;
};

class RegularPolygonCaptureTool : public TwoClickShapeTool {
public:
    static constexpr int kDefaultSides = 6;
    int sides = kDefaultSides;
    RegularPolygonCaptureTool(
        VectorEditSession* session,
        std::function<MapPoint(const MapPoint&)> snap = nullptr,
        Json attributes = Json::object(),
        std::function<void(const std::string&)> on_captured = nullptr,
        int sides = kDefaultSides);
    bool finish() override;
};

class EllipseCaptureTool : public ThreeClickShapeTool {
public:
    static constexpr int kSegments = 64;
    EllipseCaptureTool(
        VectorEditSession* session,
        std::function<MapPoint(const MapPoint&)> snap = nullptr,
        Json attributes = Json::object(),
        std::function<void(const std::string&)> on_captured = nullptr);
    bool finish() override;
};

class SectorCaptureTool : public ThreeClickShapeTool {
public:
    static constexpr int kSegments = 32;
    SectorCaptureTool(
        VectorEditSession* session,
        std::function<MapPoint(const MapPoint&)> snap = nullptr,
        Json attributes = Json::object(),
        std::function<void(const std::string&)> on_captured = nullptr);
    bool finish() override;
};

// 批量捕捉对齐（V12 M5-A）：选集顶点逐个吸附到捕捉命中处（单宏）。
class SnapGeometriesTool : public MapTool {
public:
    SnapGeometriesTool(
        VectorEditSession* session,
        std::function<MapPoint(const MapPoint&)> snap_vertex) {
        tool_id = "snap_geometries";
        this->session = session;
        snap_vertex_ = std::move(snap_vertex);
    }
    VectorEditSession* session;
    int moved_points = 0;
    bool edits_data() const override { return true; }
    // 对会话全部选中要素执行吸附；返回是否有要素被改变。layer 传入
    // 提供选集（Python 读 session.layer——本会话即携 layer 引用）。
    bool run(VectorLayer& layer);

private:
    bool apply_to_feature(const std::string& feature_id);
    std::function<MapPoint(const MapPoint&)> snap_vertex_;
};

class MoveFeatureTool : public MapTool {
public:
    MoveFeatureTool(
        VectorEditSession* session,
        std::function<std::optional<std::string>(const MapPoint&)>
            identify) {
        tool_id = "move_feature";
        this->session = session;
        identify_ = std::move(identify);
    }
    VectorEditSession* session;
    bool edits_data() const override { return true; }
    bool mouse_press(const MapPoint& point, const std::string& button,
                     const Modifiers& modifiers) override;
    bool mouse_release(const MapPoint& point, const std::string& button,
                       const Modifiers& modifiers) override;
    bool cancel() override;
    bool commit_move(const std::string& feature_id, double dx, double dy);

private:
    std::function<std::optional<std::string>(const MapPoint&)> identify_;
    std::optional<std::string> feature_id_;
    std::optional<MapPoint> origin_;
};

// V7 重塑（native-only）：原生 addLine 数字化器采重塑线 → 会话几何替
// 换。无鼠标路径。
class ReshapeTool : public MapTool {
public:
    ReshapeTool(VectorEditSession* session, std::string feature_id,
                std::function<bool(const Json&)> apply_reshape) {
        tool_id = "reshape";
        this->session = session;
        this->feature_id = std::move(feature_id);
        apply_reshape_ = std::move(apply_reshape);
    }
    VectorEditSession* session;
    std::string feature_id;
    bool edits_data() const override { return true; }
    bool commit_geometry(const Json& geometry);

private:
    std::function<bool(const Json&)> apply_reshape_;
};

class VertexTool : public MapTool {
public:
    using IdentifyVertex = std::function<
        std::optional<std::pair<std::string, std::vector<int>>>(
            const MapPoint&)>;
    VertexTool(VectorEditSession* session, IdentifyVertex identify_vertex) {
        tool_id = "vertex";
        this->session = session;
        identify_vertex_ = std::move(identify_vertex);
    }
    VectorEditSession* session;
    bool edits_data() const override { return true; }
    bool mouse_press(const MapPoint& point, const std::string& button,
                     const Modifiers& modifiers) override;
    bool mouse_release(const MapPoint& point, const std::string& button,
                       const Modifiers& modifiers) override;
    bool cancel() override;
    bool commit_vertex_move(const std::string& feature_id,
                            const std::vector<int>& path,
                            const MapPoint& point);
    bool commit_vertex_insert(const std::string& feature_id,
                              const std::vector<int>& path,
                              const MapPoint& point);
    bool commit_vertex_delete(const std::string& feature_id,
                              const std::vector<int>& path);

private:
    IdentifyVertex identify_vertex_;
    std::optional<std::pair<std::string, std::vector<int>>> target_;
    std::optional<MapPoint> origin_;
};

// V10 添加内环（native-only）：原生 addPolygon 数字化器采环 → 会话
// add_ring。无鼠标路径。
class RingCaptureTool : public MapTool {
public:
    RingCaptureTool(VectorEditSession* session, std::string feature_id,
                    std::function<bool(const Json&)> apply_ring) {
        tool_id = "add_ring";
        this->session = session;
        this->feature_id = std::move(feature_id);
        apply_ring_ = std::move(apply_ring);
        native_digitize_kind = "addPolygon";
    }
    VectorEditSession* session;
    std::string feature_id;
    bool edits_data() const override { return true; }
    bool commit_geometry(const Json& geometry);

private:
    std::function<bool(const Json&)> apply_ring_;
};

// V10 添加部件（native-only）：digitizer 随图层 kind，桥 add_part 执
// 行，session.add_part 落命令。
class PartCaptureTool : public MapTool {
public:
    PartCaptureTool(VectorEditSession* session, std::string feature_id,
                    std::function<bool(const Json&)> apply_part) {
        tool_id = "add_part";
        this->session = session;
        this->feature_id = std::move(feature_id);
        apply_part_ = std::move(apply_part);
    }
    VectorEditSession* session;
    std::string feature_id;
    bool edits_data() const override { return true; }
    bool commit_geometry(const Json& geometry);

private:
    std::function<bool(const Json&)> apply_part_;
};

}  // namespace pwb::ui_composite
