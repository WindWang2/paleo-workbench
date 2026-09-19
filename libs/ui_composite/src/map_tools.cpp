#include <pwb/ui_composite/map_tools.hpp>

#include <cmath>
#include <cstdlib>
#include <utility>

namespace pwb::ui_composite {
namespace {

Json point_json(const MapPoint& p) { return Json::array({p[0], p[1]}); }

MapPoint point_or_raw(const std::function<MapPoint(const MapPoint&)>& snap,
                      const MapPoint& p) {
    return snap ? snap(p) : p;
}

// _commit_vertex parity: the drag is synthesized as one compound command.
bool commit_vertex(VectorEditSession& session, const std::string& feature_id,
                   const std::vector<int>& path, const MapPoint& point,
                   const char* source_suffix) {
    try {
        (void)session.feature(feature_id);
    } catch (const std::exception&) {
        return false;
    }
    session.begin_edit_command();
    try {
        auto guard = session.edit_source(
            std::string("vertex(") + source_suffix + ")");
        session.set_vertex(feature_id, path, point_json(point));
    } catch (const std::exception&) {
        session.destroy_edit_command();
        return false;
    }
    session.end_edit_command();
    return true;
}

}  // namespace

// ---------------------------------------------------------------------------
// MapTool base
// ---------------------------------------------------------------------------

bool MapTool::mouse_press(const MapPoint&, const std::string&,
                          const Modifiers&) {
    return false;
}
bool MapTool::mouse_move(const MapPoint&, const Modifiers&) { return false; }
bool MapTool::mouse_release(const MapPoint&, const std::string&,
                            const Modifiers&) {
    return false;
}
bool MapTool::double_click(const MapPoint& point, const Modifiers& mods) {
    return mouse_press(point, "left", mods);
}
bool MapTool::key_press(const std::string& key) {
    std::string lower = key;
    for (auto& c : lower) c = static_cast<char>(std::tolower(c));
    if (lower == "escape") return cancel();
    return false;
}

// ---------------------------------------------------------------------------
// MapToolController
// ---------------------------------------------------------------------------

void MapToolController::set_active_tool(std::shared_ptr<MapTool> tool) {
    if (tool.get() == active_tool_.get()) return;
    if (active_tool_) active_tool_->deactivate();
    active_tool_ = std::move(tool);
    if (active_tool_) active_tool_->activate();
}

bool MapToolController::key_press(const std::string& key) {
    return active_tool_ && active_tool_->key_press(key);
}

// ---------------------------------------------------------------------------
// ZoomTool
// ---------------------------------------------------------------------------

ZoomTool::ZoomTool(std::function<void(double, const MapPoint&)> zoom,
                   double factor, std::string id)
    : zoom_(std::move(zoom)), factor_(factor) {
    tool_id = std::move(id);
}

bool ZoomTool::mouse_press(const MapPoint& point, const std::string& button,
                           const Modifiers&) {
    if (button != "left") return false;
    zoom_(factor_, point);
    return true;
}

// ---------------------------------------------------------------------------
// MeasureDistanceTool
// ---------------------------------------------------------------------------

std::vector<MapPoint> MeasureDistanceTool::points() const {
    std::vector<MapPoint> out;
    if (start) out.push_back(*start);
    if (current) out.push_back(*current);
    return out;
}

double MeasureDistanceTool::measure(const MapPoint& a, const MapPoint& b) {
    if (geod_) {
        try {
            if (auto result = geod_(a[0], a[1], b[0], b[1])) {
                double distance = std::get<2>(*result);
                if (std::isfinite(distance)) {
                    last_geodesic = true;
                    return distance;
                }
            }
        } catch (const std::exception&) {
        }
    }
    last_geodesic = false;
    return std::hypot(b[0] - a[0], b[1] - a[1]);
}

bool MeasureDistanceTool::mouse_press(const MapPoint& point,
                                      const std::string& button,
                                      const Modifiers&) {
    if (button == "right") return cancel();
    if (button != "left") return false;
    if (!start.has_value()) {
        start = point;
        current = point;
        return true;
    }
    double distance = measure(*start, point);
    last_distance = distance;
    if (measurement_ready_) measurement_ready_(distance);
    start = point;
    current = point;
    return true;
}

bool MeasureDistanceTool::mouse_move(const MapPoint& point, const Modifiers&) {
    if (!start.has_value()) return false;
    current = point;
    return true;
}

bool MeasureDistanceTool::cancel() {
    bool had = start.has_value();
    start.reset();
    current.reset();
    last_distance.reset();
    return had;
}

// ---------------------------------------------------------------------------
// SelectTool
// ---------------------------------------------------------------------------

bool SelectTool::mouse_press(const MapPoint& point, const std::string& button,
                             const Modifiers& modifiers) {
    if (button != "left") return false;
    auto feature_id = identify_(point);
    if (!feature_id.has_value()) {
        if (modifiers.empty()) layer_->set_selection({});
        return true;
    }
    if (modifiers.count("ctrl") || modifiers.count("shift"))
        layer_->toggle_selection(*feature_id);
    else
        layer_->set_selection({*feature_id});
    return true;
}

bool SelectTool::commit_selection(
    const std::vector<std::string>& feature_ids, const Modifiers& modifiers) {
    std::set<std::string> ids(feature_ids.begin(), feature_ids.end());
    std::set<std::string> current = layer_->selection();
    std::set<std::string> next;
    bool ctrl = modifiers.count("ctrl"), shift = modifiers.count("shift");
    if (ctrl && shift) {
        for (const auto& id : current)
            if (ids.count(id)) next.insert(id);
    } else if (ctrl) {
        next = current;
        next.insert(ids.begin(), ids.end());
    } else if (shift) {
        for (const auto& id : current)
            if (!ids.count(id)) next.insert(id);
    } else {
        next = ids;
    }
    layer_->set_selection(std::vector<std::string>(next.begin(), next.end()));
    return true;
}

// ---------------------------------------------------------------------------
// RectangleSelectTool
// ---------------------------------------------------------------------------

bool RectangleSelectTool::mouse_press(const MapPoint& point,
                                      const std::string& button,
                                      const Modifiers&) {
    if (button != "left") return false;
    start_ = point;
    return true;
}

bool RectangleSelectTool::mouse_release(const MapPoint& point,
                                        const std::string& button,
                                        const Modifiers& modifiers) {
    if (button != "left" || !start_.has_value()) return false;
    MapPoint start = *start_;
    start_.reset();
    std::set<std::string> selected = select_rectangle_(start, point);
    std::set<std::string> current = layer_->selection();
    std::set<std::string> next;
    bool ctrl = modifiers.count("ctrl"), shift = modifiers.count("shift");
    if (ctrl && shift) {
        for (const auto& id : current)
            if (selected.count(id)) next.insert(id);
    } else if (ctrl) {
        next = current;
        next.insert(selected.begin(), selected.end());
    } else if (shift) {
        for (const auto& id : current)
            if (!selected.count(id)) next.insert(id);
    } else {
        next = selected;
    }
    layer_->set_selection(std::vector<std::string>(next.begin(), next.end()));
    return true;
}

bool RectangleSelectTool::cancel() {
    bool had = start_.has_value();
    start_.reset();
    return had;
}

// ---------------------------------------------------------------------------
// IdentifyTool
// ---------------------------------------------------------------------------

bool IdentifyTool::mouse_press(const MapPoint& point,
                               const std::string& button, const Modifiers&) {
    if (button != "left") return false;
    identify_(point);
    return true;
}

// ---------------------------------------------------------------------------
// CaptureTool
// ---------------------------------------------------------------------------

CaptureTool::CaptureTool(
    VectorEditSession* s, std::string id, std::string geometry,
    std::function<MapPoint(const MapPoint&)> snap, Json attributes,
    std::function<void(const std::string&)> on_captured,
    std::function<std::string()> feature_id_factory)
    : session(s),
      snap_(std::move(snap)),
      default_attributes_(std::move(attributes)),
      on_captured_(std::move(on_captured)),
      feature_id_factory_(std::move(feature_id_factory)) {
    tool_id = std::move(id);
    geometry_type = std::move(geometry);
    if (!feature_id_factory_) {
        std::string prefix = tool_id;
        feature_id_factory_ = [prefix] {
            return ui_data_core::new_feature_id(prefix);
        };
    }
}

void CaptureTool::notify_captured(const std::string& feature_id) {
    if (!on_captured_) return;
    try {
        on_captured_(feature_id);
    } catch (const std::exception&) {
        // 回调异常不得影响要素落地 (Python parity: logged, swallowed).
    }
}

bool CaptureTool::mouse_press(const MapPoint& point,
                              const std::string& button, const Modifiers&) {
    if (button == "right") return finish();
    if (button != "left") return false;
    points.push_back(point_or_raw(snap_, point));
    if (geometry_type == "Point") return finish();
    return true;
}

bool CaptureTool::mouse_move(const MapPoint&, const Modifiers&) {
    return !points.empty();
}

bool CaptureTool::double_click(const MapPoint& point, const Modifiers&) {
    points.push_back(point_or_raw(snap_, point));
    return finish();
}

bool CaptureTool::cancel() {
    bool had = !points.empty();
    points.clear();
    return had;
}

bool CaptureTool::finish() {
    Json geometry;
    if (geometry_type == "Point") {
        if (points.size() != 1) return false;
        geometry = {{"type", "Point"},
                    {"coordinates", {points[0][0], points[0][1]}}};
    } else if (geometry_type == "LineString") {
        if (points.size() < 2) return false;
        Json coords = Json::array();
        for (const auto& p : points) coords.push_back({p[0], p[1]});
        geometry = {{"type", "LineString"}, {"coordinates", coords}};
    } else {
        if (points.size() < 3) return false;
        Json ring = Json::array();
        for (const auto& p : points) ring.push_back({p[0], p[1]});
        if (points.front() != points.back())
            ring.push_back({points.front()[0], points.front()[1]});
        geometry = {{"type", "Polygon"}, {"coordinates", {ring}}};
    }
    return finish_with_geometry(std::move(geometry));
}

bool CaptureTool::finish_with_geometry(Json geometry) {
    if (!session) return false;
    std::string feature_id;
    {
        auto guard = session->edit_source(tool_id + "(python-fallback)");
        feature_id = feature_id_factory_();
        session->add_feature(
            VectorFeature(feature_id, std::move(geometry),
                          default_attributes_));
    }
    points.clear();
    notify_captured(feature_id);
    return true;
}

bool CaptureTool::commit_geometry(const Json& geometry) {
    if (!session) return false;
    if (!geometry.is_object() || !geometry.contains("type")) return false;
    std::string gtype = geometry.value("type", "");
    const std::string expected = geometry_type;
    if (gtype != expected && gtype != "Multi" + expected) return false;
    std::string feature_id;
    {
        auto guard = session->edit_source(tool_id + "(native)");
        feature_id = feature_id_factory_();
        session->add_feature(
            VectorFeature(feature_id, geometry, default_attributes_));
    }
    points.clear();
    notify_captured(feature_id);
    return true;
}

AddPointTool::AddPointTool(
    VectorEditSession* s, std::function<MapPoint(const MapPoint&)> snap,
    Json attributes, std::function<void(const std::string&)> on_captured)
    : CaptureTool(s, "add_point", "Point", std::move(snap),
                  std::move(attributes), std::move(on_captured)) {}
AddLineTool::AddLineTool(
    VectorEditSession* s, std::function<MapPoint(const MapPoint&)> snap,
    Json attributes, std::function<void(const std::string&)> on_captured)
    : CaptureTool(s, "add_line", "LineString", std::move(snap),
                  std::move(attributes), std::move(on_captured)) {}
AddPolygonTool::AddPolygonTool(
    VectorEditSession* s, std::function<MapPoint(const MapPoint&)> snap,
    Json attributes, std::function<void(const std::string&)> on_captured)
    : CaptureTool(s, "add_polygon", "Polygon", std::move(snap),
                  std::move(attributes), std::move(on_captured)) {}

// ---------------------------------------------------------------------------
// Shape tools
// ---------------------------------------------------------------------------

bool TwoClickShapeTool::mouse_press(const MapPoint& point,
                                    const std::string& button,
                                    const Modifiers& mods) {
    if (button == "right") return finish();
    if (button != "left") return false;
    points.push_back(point_or_raw(snap_, point));
    return points.size() == 2 ? finish() : true;
}

bool ThreeClickShapeTool::mouse_press(const MapPoint& point,
                                      const std::string& button,
                                      const Modifiers& mods) {
    if (button == "right") return finish();
    if (button != "left") return false;
    points.push_back(point_or_raw(snap_, point));
    return points.size() == 3 ? finish() : true;
}

RectangleCaptureTool::RectangleCaptureTool(
    VectorEditSession* s, std::function<MapPoint(const MapPoint&)> snap,
    Json attributes, std::function<void(const std::string&)> on_captured)
    : TwoClickShapeTool(s, "add_rectangle", "Polygon", std::move(snap),
                        std::move(attributes), std::move(on_captured)) {}

bool RectangleCaptureTool::finish() {
    if (points.size() != 2) return false;
    double x0 = points[0][0], y0 = points[0][1];
    double x1 = points[1][0], y1 = points[1][1];
    double xmin = std::min(x0, x1), xmax = std::max(x0, x1);
    double ymin = std::min(y0, y1), ymax = std::max(y0, y1);
    if (xmax - xmin <= 0.0 || ymax - ymin <= 0.0) {
        points.clear();
        return false;
    }
    Json ring = Json::array({Json::array({xmin, ymin}),
                             Json::array({xmax, ymin}),
                             Json::array({xmax, ymax}),
                             Json::array({xmin, ymax}),
                             Json::array({xmin, ymin})});
    return finish_with_geometry(
        {{"type", "Polygon"}, {"coordinates", {ring}}});
}

CircleCaptureTool::CircleCaptureTool(
    VectorEditSession* s, std::function<MapPoint(const MapPoint&)> snap,
    Json attributes, std::function<void(const std::string&)> on_captured)
    : TwoClickShapeTool(s, "add_circle", "Polygon", std::move(snap),
                        std::move(attributes), std::move(on_captured)) {}

bool CircleCaptureTool::finish() {
    if (points.size() != 2) return false;
    double cx = points[0][0], cy = points[0][1];
    double radius =
        std::hypot(points[1][0] - cx, points[1][1] - cy);
    if (radius <= 0.0) {
        points.clear();
        return false;
    }
    Json ring = Json::array();
    for (int i = 0; i < kSegments; ++i) {
        double a = 2.0 * M_PI * i / kSegments;
        ring.push_back({cx + radius * std::cos(a),
                        cy + radius * std::sin(a)});
    }
    ring.push_back(ring[0]);
    return finish_with_geometry(
        {{"type", "Polygon"}, {"coordinates", {ring}}});
}

ArcCaptureTool::ArcCaptureTool(
    VectorEditSession* s, std::function<MapPoint(const MapPoint&)> snap,
    Json attributes, std::function<void(const std::string&)> on_captured)
    : ThreeClickShapeTool(s, "add_arc", "LineString", std::move(snap),
                          std::move(attributes), std::move(on_captured)) {}

bool ArcCaptureTool::finish() {
    if (points.size() != 3) return false;
    double x0 = points[0][0], y0 = points[0][1];
    double x1 = points[1][0], y1 = points[1][1];
    double x2 = points[2][0], y2 = points[2][1];
    double divisor =
        2.0 * (x0 * (y1 - y2) + x1 * (y2 - y0) + x2 * (y0 - y1));
    Json coords = Json::array();
    if (std::abs(divisor) < 1e-12) {
        coords = Json::array({Json::array({x0, y0}), Json::array({x1, y1}),
                              Json::array({x2, y2})});
    } else {
        auto sq = [](double x, double y) { return x * x + y * y; };
        double ux = (sq(x0, y0) * (y1 - y2) + sq(x1, y1) * (y2 - y0) +
                     sq(x2, y2) * (y0 - y1)) /
                    divisor;
        double uy = (sq(x0, y0) * (x2 - x1) + sq(x1, y1) * (x0 - x2) +
                     sq(x2, y2) * (x1 - x0)) /
                    divisor;
        double r0 = std::hypot(x0 - ux, y0 - uy);
        double a0 = std::atan2(y0 - uy, x0 - ux);
        double a1 = std::atan2(y1 - uy, x1 - ux);
        double a2 = std::atan2(y2 - uy, x2 - ux);
        double two_pi = 2.0 * M_PI;
        double sweep_ccw = std::fmod(a2 - a0, two_pi);
        if (sweep_ccw < 0) sweep_ccw += two_pi;
        double mid_ccw = std::fmod(a1 - a0, two_pi);
        if (mid_ccw < 0) mid_ccw += two_pi;
        double sweep = (mid_ccw <= sweep_ccw) ? sweep_ccw
                                              : sweep_ccw - two_pi;
        for (int i = 0; i <= kSegments; ++i) {
            double a = a0 + sweep * i / kSegments;
            coords.push_back({ux + r0 * std::cos(a),
                              uy + r0 * std::sin(a)});
        }
    }
    return finish_with_geometry(
        {{"type", "LineString"}, {"coordinates", coords}});
}

RegularPolygonCaptureTool::RegularPolygonCaptureTool(
    VectorEditSession* s, std::function<MapPoint(const MapPoint&)> snap,
    Json attributes, std::function<void(const std::string&)> on_captured,
    int sides_)
    : TwoClickShapeTool(s, "add_regular_polygon", "Polygon",
                        std::move(snap), std::move(attributes),
                        std::move(on_captured)) {
    sides = std::max(3, sides_);
}

bool RegularPolygonCaptureTool::finish() {
    if (points.size() != 2) return false;
    double cx = points[0][0], cy = points[0][1];
    double radius = std::hypot(points[1][0] - cx, points[1][1] - cy);
    if (radius <= 0.0) {
        points.clear();
        return false;
    }
    double base = std::atan2(points[1][1] - cy, points[1][0] - cx);
    Json ring = Json::array();
    for (int i = 0; i < sides; ++i) {
        double a = base + 2.0 * M_PI * i / sides;
        ring.push_back({cx + radius * std::cos(a),
                        cy + radius * std::sin(a)});
    }
    ring.push_back(ring[0]);
    return finish_with_geometry(
        {{"type", "Polygon"}, {"coordinates", {ring}}});
}

EllipseCaptureTool::EllipseCaptureTool(
    VectorEditSession* s, std::function<MapPoint(const MapPoint&)> snap,
    Json attributes, std::function<void(const std::string&)> on_captured)
    : ThreeClickShapeTool(s, "add_ellipse", "Polygon", std::move(snap),
                          std::move(attributes), std::move(on_captured)) {}

bool EllipseCaptureTool::finish() {
    if (points.size() != 3) return false;
    double cx = points[0][0], cy = points[0][1];
    double px = points[1][0], py = points[1][1];
    double qx = points[2][0], qy = points[2][1];
    double ux = px - cx, uy = py - cy;
    double a = std::hypot(ux, uy);
    if (a <= 0.0) {
        points.clear();
        return false;
    }
    ux /= a;
    uy /= a;
    double wx = qx - cx, wy = qy - cy;
    double nx = -uy, ny = ux;
    double b = std::abs(wx * nx + wy * ny);
    if (b <= 0.0) {
        points.clear();
        return false;
    }
    Json ring = Json::array();
    for (int i = 0; i < kSegments; ++i) {
        double t = 2.0 * M_PI * i / kSegments;
        ring.push_back({cx + a * std::cos(t) * ux - b * std::sin(t) * uy,
                        cy + a * std::cos(t) * uy + b * std::sin(t) * ux});
    }
    ring.push_back(ring[0]);
    return finish_with_geometry(
        {{"type", "Polygon"}, {"coordinates", {ring}}});
}

SectorCaptureTool::SectorCaptureTool(
    VectorEditSession* s, std::function<MapPoint(const MapPoint&)> snap,
    Json attributes, std::function<void(const std::string&)> on_captured)
    : ThreeClickShapeTool(s, "add_sector", "Polygon", std::move(snap),
                          std::move(attributes), std::move(on_captured)) {}

bool SectorCaptureTool::finish() {
    if (points.size() != 3) return false;
    double cx = points[0][0], cy = points[0][1];
    double sx = points[1][0], sy = points[1][1];
    double ex = points[2][0], ey = points[2][1];
    double radius = std::hypot(sx - cx, sy - cy);
    if (radius <= 0.0) {
        points.clear();
        return false;
    }
    double a0 = std::atan2(sy - cy, sx - cx);
    double a1 = std::atan2(ey - cy, ex - cx);
    double two_pi = 2.0 * M_PI;
    double sweep = std::fmod(a1 - a0, two_pi);
    if (sweep <= 0.0) sweep += two_pi;  // 起止同方位 = 整圆
    Json ring = Json::array({Json::array({cx, cy})});
    for (int i = 0; i <= kSegments; ++i) {
        double a = a0 + sweep * i / kSegments;
        ring.push_back({cx + radius * std::cos(a),
                        cy + radius * std::sin(a)});
    }
    ring.push_back(ring[0]);
    return finish_with_geometry(
        {{"type", "Polygon"}, {"coordinates", {ring}}});
}

// ---------------------------------------------------------------------------
// SnapGeometriesTool
// ---------------------------------------------------------------------------

bool SnapGeometriesTool::run(VectorLayer& layer) {
    if (!session) return false;
    bool changed = false;
    auto guard = session->edit_source(tool_id + "(command)");
    std::set<std::string> selection = layer.selection();
    std::vector<std::string> ids(selection.begin(), selection.end());
    std::sort(ids.begin(), ids.end());
    for (const auto& fid : ids) changed |= apply_to_feature(fid);
    return changed;
}

bool SnapGeometriesTool::apply_to_feature(const std::string& feature_id) {
    if (!session) return false;
    const VectorFeature& before = session->feature(feature_id);
    Json geometry = before.as_record().value("geometry", Json());
    moved_points = 0;

    std::function<Json(const Json&)> snap_coords =
        [&](const Json& node) -> Json {
        if (node.is_array()) {
            if (!node.empty() && node[0].is_number()) {
                MapPoint p{node[0].get<double>(), node[1].get<double>()};
                MapPoint snapped = snap_vertex_ ? snap_vertex_(p) : p;
                if (std::abs(snapped[0] - p[0]) > 1e-9 ||
                    std::abs(snapped[1] - p[1]) > 1e-9)
                    moved_points += 1;
                return Json::array({snapped[0], snapped[1]});
            }
            Json out = Json::array();
            for (const auto& child : node)
                out.push_back(snap_coords(child));
            return out;
        }
        return node;
    };

    Json coordinates = snap_coords(geometry.value("coordinates", Json()));
    if (moved_points == 0) return false;  // 全部吸附到自身——无变更
    Json after = geometry;
    after["coordinates"] = std::move(coordinates);
    session->set_geometry(feature_id, after);
    return true;
}

// ---------------------------------------------------------------------------
// MoveFeatureTool
// ---------------------------------------------------------------------------

bool MoveFeatureTool::mouse_press(const MapPoint& point,
                                  const std::string& button,
                                  const Modifiers&) {
    if (button != "left") return false;
    feature_id_ = identify_(point);
    origin_ = feature_id_ ? std::optional<MapPoint>(point) : std::nullopt;
    return feature_id_.has_value();
}

bool MoveFeatureTool::mouse_release(const MapPoint& point,
                                    const std::string& button,
                                    const Modifiers&) {
    if (!session) return false;
    if (button != "left" || !feature_id_ || !origin_) return false;
    std::string fid = *feature_id_;
    MapPoint origin = *origin_;
    feature_id_.reset();
    origin_.reset();
    auto guard = session->edit_source(tool_id + "(python-fallback)");
    session->move_feature(fid, point[0] - origin[0], point[1] - origin[1]);
    return true;
}

bool MoveFeatureTool::cancel() {
    bool had = feature_id_.has_value();
    feature_id_.reset();
    origin_.reset();
    return had;
}

bool MoveFeatureTool::commit_move(const std::string& feature_id, double dx,
                                  double dy) {
    if (!session) return false;
    try {
        auto guard = session->edit_source(tool_id + "(native)");
        session->move_feature(feature_id, dx, dy);
    } catch (const std::exception&) {
        return false;
    }
    return true;
}

// ---------------------------------------------------------------------------
// ReshapeTool
// ---------------------------------------------------------------------------

bool ReshapeTool::commit_geometry(const Json& geometry) {
    if (!session) return false;
    if (!geometry.is_object()) return false;
    std::string gtype = geometry.value("type", "");
    if (gtype != "LineString" && gtype != "MultiLineString") return false;
    bool ok;
    {
        auto guard = session->edit_source(tool_id + "(native)");
        ok = apply_reshape_ && apply_reshape_(geometry);
    }
    return ok;
}

// ---------------------------------------------------------------------------
// VertexTool
// ---------------------------------------------------------------------------

bool VertexTool::mouse_press(const MapPoint& point, const std::string& button,
                             const Modifiers&) {
    if (!session) return false;
    if (button != "left") return false;
    target_ = identify_vertex_(point);
    if (target_) {
        const auto& [fid, path] = *target_;
        try {
            const VectorFeature& f = session->feature(fid);
            const Json* current = &f.geometry["coordinates"];
            if (path.empty() && f.geometry.value("type", "") == "Point") {
                origin_ = MapPoint{(*current)[0].get<double>(),
                                   (*current)[1].get<double>()};
            } else {
                for (int index : path) current = &(*current)[index];
                origin_ = MapPoint{(*current)[0].get<double>(),
                                   (*current)[1].get<double>()};
            }
        } catch (const std::exception&) {
            origin_.reset();
        }
    }
    return target_.has_value();
}

bool VertexTool::mouse_release(const MapPoint& point,
                               const std::string& button, const Modifiers&) {
    if (!session) return false;
    if (button != "left" || !target_) return false;
    auto [fid, path] = *target_;
    target_.reset();
    origin_.reset();
    return commit_vertex(*session, fid, path, point, "python-fallback");
}

bool VertexTool::cancel() {
    bool had = target_.has_value();
    target_.reset();
    origin_.reset();
    return had;
}

bool VertexTool::commit_vertex_move(const std::string& feature_id,
                                    const std::vector<int>& path,
                                    const MapPoint& point) {
    if (!session) return false;
    return commit_vertex(*session, feature_id, path, point, "native");
}

bool VertexTool::commit_vertex_insert(const std::string& feature_id,
                                      const std::vector<int>& path,
                                      const MapPoint& point) {
    if (!session) return false;
    try {
        session->begin_edit_command();
        auto guard = session->edit_source("vertex(native)");
        session->insert_vertex(feature_id, path, point_json(point));
    } catch (const std::exception&) {
        session->destroy_edit_command();
        return false;
    }
    session->end_edit_command();
    return true;
}

bool VertexTool::commit_vertex_delete(const std::string& feature_id,
                                      const std::vector<int>& path) {
    if (!session) return false;
    try {
        session->begin_edit_command();
        auto guard = session->edit_source("vertex(native)");
        session->delete_vertex(feature_id, path);
    } catch (const std::exception&) {
        session->destroy_edit_command();
        return false;
    }
    session->end_edit_command();
    return true;
}

// ---------------------------------------------------------------------------
// RingCaptureTool / PartCaptureTool
// ---------------------------------------------------------------------------

bool RingCaptureTool::commit_geometry(const Json& geometry) {
    if (!session) return false;
    if (!geometry.is_object()) return false;
    std::string gtype = geometry.value("type", "");
    if (gtype != "Polygon" && gtype != "MultiPolygon") return false;
    bool ok;
    {
        auto guard = session->edit_source(tool_id + "(native)");
        ok = apply_ring_ && apply_ring_(geometry);
    }
    return ok;
}

bool PartCaptureTool::commit_geometry(const Json& geometry) {
    if (!session) return false;
    if (!geometry.is_object() || !geometry.contains("type")) return false;
    bool ok;
    {
        auto guard = session->edit_source(tool_id + "(native)");
        ok = apply_part_ && apply_part_(geometry);
    }
    return ok;
}

}  // namespace pwb::ui_composite
