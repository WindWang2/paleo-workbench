#include <pwb/ui_composite/map_interaction.hpp>

#include <pwb/ui_composite/geometry.hpp>
#include <pwb/ui_composite/snapping_profiles.hpp>

#include <algorithm>
#include <cmath>
#include <limits>

namespace pwb::ui_composite {
namespace {

constexpr int64_t kMaxQueryCells = 4096;

std::string geometry_type(const Json& geometry) {
    if (!geometry.is_object()) {
        return {};
    }
    auto it = geometry.find("type");
    return it != geometry.end() && it->is_string()
               ? it->get<std::string>()
               : std::string{};
}

const Json& empty_json() {
    static const Json empty = Json::array();
    return empty;
}

const Json& coordinates_of(const Json& geometry) {
    if (!geometry.is_object()) {
        return empty_json();
    }
    auto it = geometry.find("coordinates");
    if (it == geometry.end() || !it->is_array()) {
        return empty_json();
    }
    return *it;
}

// _vertices: flatten leaf [x, y] points with their index paths.
void walk_vertices(const Json& node, std::vector<int>& path,
                   std::vector<std::pair<MapPoint, std::vector<int>>>& out) {
    if (auto point = json_point(node); point.has_value()) {
        out.emplace_back(*point, path);
        return;
    }
    if (!node.is_array()) {
        return;
    }
    for (size_t i = 0; i < node.size(); ++i) {
        path.push_back(static_cast<int>(i));
        walk_vertices(node[i], path, out);
        path.pop_back();
    }
}

std::vector<std::pair<MapPoint, std::vector<int>>> vertices_of(
    const Json& coordinates) {
    std::vector<std::pair<MapPoint, std::vector<int>>> out;
    std::vector<int> path;
    walk_vertices(coordinates, path, out);
    return out;
}

std::array<double, 4> bounds_of(const VectorFeature& feature) {
    const Json& coords = coordinates_of(feature.geometry);
    std::vector<MapPoint> points;
    for (const auto& [point, path] : vertices_of(coords)) {
        points.push_back(point);
    }
    auto extent = extent_of_coordinates(points);
    return extent.has_value() ? *extent
                              : MapExtent{0.0, 0.0, 0.0, 0.0};
}

// _rings: ring streams per geometry type (lines and polygon rings).
std::vector<std::vector<MapPoint>> rings_of(const Json& geometry) {
    std::vector<std::vector<MapPoint>> out;
    const std::string type = geometry_type(geometry);
    const Json& coords = coordinates_of(geometry);
    auto ring_of = [](const Json& node) {
        std::vector<MapPoint> ring;
        if (node.is_array()) {
            for (const Json& value : node) {
                if (auto point = json_point(value)) {
                    ring.push_back(*point);
                }
            }
        }
        return ring;
    };
    if (type == "LineString") {
        out.push_back(ring_of(coords));
    } else if (type == "MultiLineString" || type == "Polygon") {
        for (const Json& node : coords) {
            out.push_back(ring_of(node));
        }
    } else if (type == "MultiPolygon") {
        for (const Json& polygon : coords) {
            for (const Json& ring : polygon) {
                out.push_back(ring_of(ring));
            }
        }
    }
    return out;
}

// _contains_polygon: even-odd across polygon rings via the shared kernel.
bool contains_polygon(const MapPoint& point, const Json& geometry) {
    const std::string type = geometry_type(geometry);
    if (type != "Polygon" && type != "MultiPolygon") {
        return false;
    }
    try {
        return point_in_polygon_scalar(point, geometry);
    } catch (...) {
        return false;
    }
}

std::optional<MapPoint> project_to_segment(const MapPoint& point,
                                           const MapPoint& start,
                                           const MapPoint& end) {
    const double dx = end[0] - start[0];
    const double dy = end[1] - start[1];
    const double length_sq = dx * dx + dy * dy;
    if (length_sq <= 1e-18) {
        return std::nullopt;
    }
    const double factor = std::clamp(
        ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) /
            length_sq,
        0.0, 1.0);
    return MapPoint{start[0] + factor * dx, start[1] + factor * dy};
}

// _segment_intersection: one proper segment crossing; shared endpoints
// are vertex snaps.
std::optional<MapPoint> segment_intersection(const MapPoint& a,
                                             const MapPoint& b,
                                             const MapPoint& c,
                                             const MapPoint& d) {
    const double abx = b[0] - a[0], aby = b[1] - a[1];
    const double cdx = d[0] - c[0], cdy = d[1] - c[1];
    const double denom = abx * cdy - aby * cdx;
    if (std::abs(denom) <= 1e-15) {
        return std::nullopt;
    }
    const double acx = c[0] - a[0], acy = c[1] - a[1];
    const double left = (acx * cdy - acy * cdx) / denom;
    const double right = (acx * aby - acy * abx) / denom;
    if (left > 0.0 && left < 1.0 && right > 0.0 && right < 1.0) {
        return MapPoint{a[0] + left * abx, a[1] + left * aby};
    }
    return std::nullopt;
}

double dist(const MapPoint& a, const MapPoint& b) {
    return std::hypot(a[0] - b[0], a[1] - b[1]);
}

}  // namespace

// ---------------------------------------------------------------------------
// FeatureSpatialIndex
// ---------------------------------------------------------------------------

std::pair<int64_t, int64_t> FeatureSpatialIndex::current_revision() const {
    const VectorEditSession* session =
        layer_ != nullptr ? layer_->edit_session() : nullptr;
    return {layer_ != nullptr ? layer_->data_revision : 0,
            session != nullptr ? session->revision : -1};
}

void FeatureSpatialIndex::ensure() {
    const auto revision = current_revision();
    if (revision == revision_) {
        return;
    }
    features_.clear();
    draw_order_.clear();
    bounds_.clear();
    vertices_.clear();
    feature_cells_.clear();
    vertex_cells_.clear();
    segment_cells_.clear();
    if (layer_ == nullptr) {
        revision_ = revision;
        return;
    }
    VectorEditSession* session = layer_->edit_session();
    features_ = session != nullptr ? session->features()
                                   : layer_->features();
    for (size_t i = 0; i < features_.size(); ++i) {
        draw_order_[features_[i].feature_id] = i;
        bounds_[features_[i].feature_id] = bounds_of(features_[i]);
        vertices_[features_[i].feature_id] =
            vertices_of(coordinates_of(features_[i].geometry));
    }
    if (!bounds_.empty()) {
        double xmin = std::numeric_limits<double>::max();
        double ymin = std::numeric_limits<double>::max();
        double xmax = std::numeric_limits<double>::lowest();
        double ymax = std::numeric_limits<double>::lowest();
        for (const auto& [id, b] : bounds_) {
            xmin = std::min(xmin, b[0]);
            ymin = std::min(ymin, b[1]);
            xmax = std::max(xmax, b[2]);
            ymax = std::max(ymax, b[3]);
        }
        const double span = std::max(xmax - xmin, ymax - ymin);
        // Degenerate span (all features coincident) must not shrink the
        // cell size to ~0.
        cell_size_ = span > 0.0 ? span / 64.0 : 1.0;
    } else {
        cell_size_ = 1.0;
    }
    auto cells_of = [this](const std::array<double, 4>& bounds) {
        const auto [left, bottom] = cell({bounds[0], bounds[1]});
        const auto [right, top] = cell({bounds[2], bounds[3]});
        std::vector<std::pair<int64_t, int64_t>> cells;
        for (int64_t x = left; x <= right; ++x) {
            for (int64_t y = bottom; y <= top; ++y) {
                cells.emplace_back(x, y);
            }
        }
        return cells;
    };
    for (const VectorFeature& feature : features_) {
        const std::string& feature_id = feature.feature_id;
        for (const auto& cell_id : cells_of(bounds_[feature_id])) {
            feature_cells_[cell_id].insert(feature_id);
        }
        const std::string type = geometry_type(feature.geometry);
        std::set<MapPoint> endpoint_points;
        if (type == "Point" || type == "MultiPoint") {
            for (const auto& [point, path] : vertices_[feature_id]) {
                endpoint_points.insert(point);
            }
        } else if (type == "LineString" || type == "MultiLineString") {
            for (const auto& ring : rings_of(feature.geometry)) {
                if (!ring.empty()) {
                    endpoint_points.insert(ring.front());
                    endpoint_points.insert(ring.back());
                }
            }
        }
        for (const auto& [point, path] : vertices_[feature_id]) {
            vertex_cells_[cell(point)].push_back(VertexEntry{
                feature_id, point, path,
                endpoint_points.count(point) != 0});
        }
        for (const auto& ring : rings_of(feature.geometry)) {
            for (size_t i = 0; i + 1 < ring.size(); ++i) {
                const MapPoint& start = ring[i];
                const MapPoint& end = ring[i + 1];
                const std::array<double, 4> seg_bounds = {
                    std::min(start[0], end[0]),
                    std::min(start[1], end[1]),
                    std::max(start[0], end[0]),
                    std::max(start[1], end[1]),
                };
                for (const auto& cell_id : cells_of(seg_bounds)) {
                    segment_cells_[cell_id].insert(
                        SegmentEntry{feature_id, start, end});
                }
            }
        }
    }
    revision_ = revision;
}

std::pair<int64_t, int64_t> FeatureSpatialIndex::cell(
    const MapPoint& point) const {
    return {static_cast<int64_t>(std::floor(point[0] / cell_size_)),
            static_cast<int64_t>(std::floor(point[1] / cell_size_))};
}

std::optional<std::vector<std::pair<int64_t, int64_t>>>
FeatureSpatialIndex::query_cells(
    const std::array<double, 4>& bounds) const {
    const auto [left, bottom] = cell({bounds[0], bounds[1]});
    const auto [right, top] = cell({bounds[2], bounds[3]});
    if ((right - left + 1) * (top - bottom + 1) > kMaxQueryCells) {
        return std::nullopt;
    }
    std::vector<std::pair<int64_t, int64_t>> cells;
    for (int64_t x = left; x <= right; ++x) {
        for (int64_t y = bottom; y <= top; ++y) {
            cells.emplace_back(x, y);
        }
    }
    return cells;
}

namespace {

std::array<double, 4> search_bounds(const MapPoint& point,
                                    double tolerance) {
    return {point[0] - tolerance, point[1] - tolerance,
            point[0] + tolerance, point[1] + tolerance};
}

}  // namespace

std::optional<std::string> FeatureSpatialIndex::identify(
    const MapPoint& point, double tolerance) {
    ensure();
    const auto bounds = search_bounds(point, tolerance);
    const auto cells = query_cells(bounds);
    // Reverse draw order: top-most compatible vector is found first.
    std::vector<const VectorFeature*> candidates;
    if (cells.has_value()) {
        std::set<std::string> ids;
        for (const auto& cell_id : *cells) {
            auto it = feature_cells_.find(cell_id);
            if (it != feature_cells_.end()) {
                ids.insert(it->second.begin(), it->second.end());
            }
        }
        for (const auto& id : ids) {
            auto it = std::find_if(
                features_.begin(), features_.end(),
                [&id](const VectorFeature& f) {
                    return f.feature_id == id;
                });
            if (it != features_.end()) {
                candidates.push_back(&*it);
            }
        }
    } else {
        for (const VectorFeature& feature : features_) {
            candidates.push_back(&feature);
        }
    }
    std::sort(candidates.begin(), candidates.end(),
              [this](const VectorFeature* a, const VectorFeature* b) {
                  return draw_order_[a->feature_id] >
                         draw_order_[b->feature_id];
              });
    for (const VectorFeature* feature : candidates) {
        const auto& fb = bounds_[feature->feature_id];
        if (point[0] < fb[0] - tolerance || point[0] > fb[2] + tolerance ||
            point[1] < fb[1] - tolerance || point[1] > fb[3] + tolerance) {
            continue;
        }
        const std::string type = geometry_type(feature->geometry);
        if (type == "Polygon" || type == "MultiPolygon") {
            if (contains_polygon(point, feature->geometry)) {
                return feature->feature_id;
            }
        }
        for (const auto& ring : rings_of(feature->geometry)) {
            for (size_t i = 0; i + 1 < ring.size(); ++i) {
                if (distance_to_segment(point, ring[i], ring[i + 1]) <=
                    tolerance) {
                    return feature->feature_id;
                }
            }
        }
        for (const auto& [vertex, path] :
             vertices_[feature->feature_id]) {
            if (dist(point, vertex) <= tolerance) {
                return feature->feature_id;
            }
        }
    }
    return std::nullopt;
}

std::optional<std::pair<std::string, std::vector<int>>>
FeatureSpatialIndex::identify_vertex(const MapPoint& point,
                                     double tolerance) {
    ensure();
    const auto bounds = search_bounds(point, tolerance);
    const auto cells = query_cells(bounds);
    std::optional<std::tuple<double, std::string, std::vector<int>>>
        candidate;
    auto scan = [&](const std::vector<VertexEntry>& bucket) {
        for (const VertexEntry& entry : bucket) {
            const double distance = dist(point, entry.point);
            if (distance <= tolerance &&
                (!candidate.has_value() ||
                 distance < std::get<0>(*candidate))) {
                const std::string type = geometry_type(
                    features_[draw_order_[entry.feature_id]].geometry);
                candidate = std::make_tuple(
                    distance, entry.feature_id,
                    type == "Point" ? std::vector<int>{}
                                    : entry.path);
            }
        }
    };
    if (cells.has_value()) {
        for (const auto& cell_id : *cells) {
            auto it = vertex_cells_.find(cell_id);
            if (it != vertex_cells_.end()) {
                scan(it->second);
            }
        }
    } else {
        for (const auto& [cell_id, bucket] : vertex_cells_) {
            scan(bucket);
        }
    }
    if (!candidate.has_value()) {
        return std::nullopt;
    }
    return std::make_pair(std::get<1>(*candidate), std::get<2>(*candidate));
}

std::set<std::string> FeatureSpatialIndex::select_rectangle(
    const MapPoint& start, const MapPoint& end) {
    ensure();
    const double xmin = std::min(start[0], end[0]);
    const double xmax = std::max(start[0], end[0]);
    const double ymin = std::min(start[1], end[1]);
    const double ymax = std::max(start[1], end[1]);
    const std::array<double, 4> bounds = {xmin, ymin, xmax, ymax};
    const auto cells = query_cells(bounds);
    std::set<std::string> ids;
    if (cells.has_value()) {
        for (const auto& cell_id : *cells) {
            auto it = feature_cells_.find(cell_id);
            if (it != feature_cells_.end()) {
                ids.insert(it->second.begin(), it->second.end());
            }
        }
    } else {
        for (const auto& [id, b] : bounds_) {
            ids.insert(id);
        }
    }
    std::set<std::string> out;
    for (const std::string& id : ids) {
        const auto& fb = bounds_[id];
        if (!(fb[2] < xmin || fb[0] > xmax || fb[3] < ymin ||
              fb[1] > ymax)) {
            out.insert(id);
        }
    }
    return out;
}

std::optional<SnapMatch> FeatureSpatialIndex::snap(
    const MapPoint& point, double tolerance,
    const std::set<std::string>& modes) {
    ensure();
    std::vector<SnapMatch> candidates;
    const auto bounds = search_bounds(point, tolerance);
    const auto cells = query_cells(bounds);

    auto scan_vertices = [&](const std::vector<VertexEntry>& bucket) {
        for (const VertexEntry& entry : bucket) {
            const double distance = dist(point, entry.point);
            if (distance <= tolerance &&
                (modes.count("vertex") ||
                 (modes.count("endpoint") && entry.endpoint))) {
                candidates.push_back(SnapMatch{
                    entry.feature_id, entry.point,
                    entry.endpoint && !modes.count("vertex") ? "endpoint"
                                                           : "vertex",
                    distance});
            }
        }
    };
    if (cells.has_value()) {
        for (const auto& cell_id : *cells) {
            auto it = vertex_cells_.find(cell_id);
            if (it != vertex_cells_.end()) {
                scan_vertices(it->second);
            }
        }
    } else {
        for (const auto& [cell_id, bucket] : vertex_cells_) {
            scan_vertices(bucket);
        }
    }

    std::vector<SegmentEntry> segments;
    {
        std::set<SegmentEntry> unique;
        if (cells.has_value()) {
            for (const auto& cell_id : *cells) {
                auto it = segment_cells_.find(cell_id);
                if (it != segment_cells_.end()) {
                    unique.insert(it->second.begin(), it->second.end());
                }
            }
        } else {
            for (const auto& [cell_id, bucket] : segment_cells_) {
                unique.insert(bucket.begin(), bucket.end());
            }
        }
        segments.assign(unique.begin(), unique.end());
    }
    for (const SegmentEntry& segment : segments) {
        if (modes.count("midpoint")) {
            const MapPoint midpoint = {(segment.start[0] + segment.end[0]) /
                                           2.0,
                                       (segment.start[1] + segment.end[1]) /
                                           2.0};
            const double distance = dist(point, midpoint);
            if (distance <= tolerance) {
                candidates.push_back(SnapMatch{segment.feature_id,
                                               midpoint, "midpoint",
                                               distance});
            }
        }
        if (modes.count("segment")) {
            if (auto projected = project_to_segment(point, segment.start,
                                                    segment.end)) {
                const double distance = dist(point, *projected);
                if (distance <= tolerance) {
                    candidates.push_back(SnapMatch{segment.feature_id,
                                                   *projected, "segment",
                                                   distance});
                }
            }
        }
    }
    if (modes.count("intersection")) {
        for (size_t i = 0; i < segments.size(); ++i) {
            for (size_t j = i + 1; j < segments.size(); ++j) {
                auto crossing = segment_intersection(
                    segments[i].start, segments[i].end, segments[j].start,
                    segments[j].end);
                if (crossing.has_value()) {
                    const double distance = dist(point, *crossing);
                    if (distance <= tolerance) {
                        const std::string& winner =
                            segments[i].feature_id <= segments[j].feature_id
                                ? segments[i].feature_id
                                : segments[j].feature_id;
                        candidates.push_back(SnapMatch{
                            winner, *crossing, "intersection", distance});
                    }
                }
            }
        }
    }
    if (candidates.empty()) {
        return std::nullopt;
    }
    return *std::min_element(
        candidates.begin(), candidates.end(),
        [](const SnapMatch& a, const SnapMatch& b) {
            return a.distance < b.distance;
        });
}

// ---------------------------------------------------------------------------
// SnappingService
// ---------------------------------------------------------------------------

FeatureSpatialIndex& SnappingService::index_for(VectorLayer* layer) {
    auto it = indexes_.find(layer->id());
    if (it == indexes_.end() || it->second.layer() != layer) {
        it = indexes_.insert_or_assign(layer->id(),
                                       FeatureSpatialIndex(layer))
                 .first;
    }
    return it->second;
}

void SnappingService::set_reference_points(
    const std::vector<MapPoint>& points) {
    reference_points = points;
}

std::optional<std::string> SnappingService::apply_role_profile(
    const std::string& layer_id, const std::string& role_value) {
    const SnappingProfile* profile =
        recommended_profile_for_role(role_value);
    if (profile == nullptr) {
        return std::nullopt;
    }
    // 应用推荐即恢复该层参与捕捉（不复活历史禁用——推荐的语义是「该角
    // 色如此捕捉」，被禁用的层上推荐无从生效）。
    layer_enabled[layer_id] = true;
    layer_modes[layer_id] = profile->modes;
    layer_tolerance[layer_id] = profile->tolerance_px;
    return profile_summary(*profile);
}

void SnappingService::set_grid(const std::optional<MapPoint>& spacing,
                               const MapPoint& origin) {
    if (!spacing.has_value()) {
        grid_spacing = std::nullopt;
        return;
    }
    const double sx = (*spacing)[0], sy = (*spacing)[1];
    if (sx <= 0.0 || sy <= 0.0) {
        throw std::invalid_argument("grid snap spacing must be positive");
    }
    if (!std::isfinite(origin[0]) || !std::isfinite(origin[1])) {
        throw std::invalid_argument("grid snap origin must be finite");
    }
    grid_spacing = spacing;
    grid_origin = origin;
}

MapPoint SnappingService::snap(const MapPoint& point, double tolerance,
                               const std::vector<VectorLayer*>& layers,
                               double map_units_per_pixel) {
    last_match = std::nullopt;
    if (!enabled) {
        return point;
    }
    // (distance, priority, match) — 距离优先；等距按每图层优先级（小
    // 值优先）裁决。
    std::vector<std::tuple<double, int, SnapMatch>> ranked;
    for (VectorLayer* layer : layers) {
        if (layer == nullptr) {
            continue;
        }
        auto enabled_it = layer_enabled.find(layer->id());
        if (enabled_it != layer_enabled.end() && !enabled_it->second) {
            continue;
        }
        double layer_tol = tolerance;
        auto tol_it = layer_tolerance.find(layer->id());
        if (tol_it != layer_tolerance.end()) {
            layer_tol = std::max(0.0, tol_it->second) *
                        std::max(1e-12, map_units_per_pixel);
        }
        int priority = 0;
        auto prio_it = layer_priority.find(layer->id());
        if (prio_it != layer_priority.end()) {
            priority = prio_it->second;
        }
        auto modes_it = layer_modes.find(layer->id());
        const std::set<std::string>& layer_mode_set =
            modes_it != layer_modes.end() ? modes_it->second : modes;
        auto match =
            index_for(layer).snap(point, layer_tol, layer_mode_set);
        if (match.has_value()) {
            ranked.emplace_back(match->distance, priority, *match);
        }
    }
    if (modes.count("reference")) {
        for (const MapPoint& reference : reference_points) {
            const double distance = dist(point, reference);
            if (distance <= tolerance) {
                ranked.emplace_back(distance, 0,
                                    SnapMatch{"__reference__", reference,
                                              "reference", distance});
            }
        }
    }
    if (modes.count("grid") && grid_spacing.has_value()) {
        const double sx = (*grid_spacing)[0], sy = (*grid_spacing)[1];
        const double ox = grid_origin[0], oy = grid_origin[1];
        const MapPoint grid_point = {
            ox + std::round((point[0] - ox) / sx) * sx,
            oy + std::round((point[1] - oy) / sy) * sy};
        const double distance = dist(point, grid_point);
        if (distance <= tolerance) {
            ranked.emplace_back(distance, 0,
                                SnapMatch{"__grid__", grid_point, "grid",
                                          distance});
        }
    }
    if (ranked.empty()) {
        return point;
    }
    std::sort(ranked.begin(), ranked.end(),
              [](const auto& a, const auto& b) {
                  return std::tie(std::get<0>(a), std::get<1>(a)) <
                         std::tie(std::get<0>(b), std::get<1>(b));
              });
    last_match = std::get<2>(ranked.front());
    return last_match->point;
}

Json SnappingService::snapshot_state() const {
    std::set<std::string> layer_ids;
    for (const auto& [id, v] : layer_enabled) layer_ids.insert(id);
    for (const auto& [id, v] : layer_modes) layer_ids.insert(id);
    for (const auto& [id, v] : layer_tolerance) layer_ids.insert(id);
    for (const auto& [id, v] : layer_priority) layer_ids.insert(id);
    for (const auto& [id, v] : layer_tolerance_units) layer_ids.insert(id);
    Json overrides = Json::object();
    for (const std::string& layer_id : layer_ids) {
        Json entry = Json::object();
        if (auto it = layer_enabled.find(layer_id);
            it != layer_enabled.end()) {
            entry["enabled"] = it->second;
        }
        if (auto it = layer_modes.find(layer_id);
            it != layer_modes.end()) {
            entry["modes"] = Json(it->second);
        }
        if (auto it = layer_tolerance.find(layer_id);
            it != layer_tolerance.end()) {
            entry["tolerance"] = it->second;
        }
        if (auto it = layer_priority.find(layer_id);
            it != layer_priority.end()) {
            entry["priority"] = it->second;
        }
        if (auto it = layer_tolerance_units.find(layer_id);
            it != layer_tolerance_units.end()) {
            entry["units"] = it->second;
        }
        overrides[layer_id] = std::move(entry);
    }
    Json refs = Json::array();
    for (const MapPoint& point : reference_points) {
        refs.push_back({point[0], point[1]});
    }
    return {
        {"schema_version", 1},
        {"enabled", enabled},
        {"pixel_tolerance", pixel_tolerance},
        {"modes", Json(modes)},
        {"current_layer_only", current_layer_only},
        {"tolerance_units", tolerance_units},
        {"scale_minimum",
         scale_minimum.has_value() ? Json(*scale_minimum)
                                   : Json(nullptr)},
        {"layer_overrides", std::move(overrides)},
        {"grid_origin", {grid_origin[0], grid_origin[1]}},
        {"grid_spacing",
         grid_spacing.has_value()
             ? Json({(*grid_spacing)[0], (*grid_spacing)[1]})
             : Json(nullptr)},
        {"reference_points", std::move(refs)},
    };
}

bool SnappingService::restore_state(const Json& state) {
    if (!state.is_object()) {
        return false;
    }
    auto it = state.find("schema_version");
    if (it == state.end() || !it->is_number_integer() ||
        it->get<int>() != 1) {
        return false;
    }
    auto boolean = [](const Json& object, const char* key) -> const Json* {
        auto found = object.find(key);
        return found != object.end() && found->is_boolean() ? &*found
                                                            : nullptr;
    };
    auto number = [](const Json& object, const char* key) -> const Json* {
        auto found = object.find(key);
        return found != object.end() && found->is_number() ? &*found
                                                           : nullptr;
    };
    if (const Json* value = boolean(state, "enabled")) {
        enabled = value->get<bool>();
    }
    if (const Json* value = number(state, "pixel_tolerance")) {
        pixel_tolerance = std::max(0.0, value->get<double>());
    }
    if (auto found = state.find("modes");
        found != state.end() && found->is_array()) {
        std::set<std::string> parsed;
        bool all_strings = true;
        for (const Json& item : *found) {
            if (item.is_string()) {
                parsed.insert(item.get<std::string>());
            } else {
                all_strings = false;
                break;
            }
        }
        if (all_strings) {
            modes = std::move(parsed);
        }
    }
    if (const Json* value = boolean(state, "current_layer_only")) {
        current_layer_only = value->get<bool>();
    }
    if (auto found = state.find("tolerance_units");
        found != state.end() && found->is_string()) {
        const std::string units = found->get<std::string>();
        if (units == "px" || units == "map" || units == "layer") {
            tolerance_units = units;
        }
    }
    if (auto found = state.find("scale_minimum"); found != state.end()) {
        if (found->is_null()) {
            scale_minimum = std::nullopt;
        } else if (found->is_number() && found->get<double>() > 0.0) {
            scale_minimum = found->get<double>();
        }
    }
    if (auto found = state.find("layer_overrides");
        found != state.end() && found->is_object()) {
        for (const auto& [layer_id, override] : found->items()) {
            if (!override.is_object()) {
                continue;
            }
            if (const Json* value = boolean(override, "enabled")) {
                layer_enabled[layer_id] = value->get<bool>();
            }
            if (auto list = override.find("modes");
                list != override.end() && list->is_array()) {
                std::set<std::string> parsed;
                bool all_strings = true;
                for (const Json& item : *list) {
                    if (item.is_string()) {
                        parsed.insert(item.get<std::string>());
                    } else {
                        all_strings = false;
                        break;
                    }
                }
                if (all_strings) {
                    layer_modes[layer_id] = std::move(parsed);
                }
            }
            if (const Json* value = number(override, "tolerance")) {
                layer_tolerance[layer_id] =
                    std::max(0.0, value->get<double>());
            }
            if (auto prio = override.find("priority");
                prio != override.end() && prio->is_number_integer()) {
                layer_priority[layer_id] = prio->get<int>();
            }
            if (auto units = override.find("units");
                units != override.end() && units->is_string()) {
                const std::string value = units->get<std::string>();
                if (value == "px" || value == "map" || value == "layer") {
                    layer_tolerance_units[layer_id] = value;
                }
            }
        }
    }
    if (auto found = state.find("grid_origin"); found != state.end()) {
        if (auto origin = json_point(*found)) {
            grid_origin = *origin;
        }
    }
    if (auto found = state.find("grid_spacing"); found != state.end()) {
        if (found->is_null()) {
            grid_spacing = std::nullopt;
        } else if (auto spacing = json_point(*found);
                   spacing.has_value() && (*spacing)[0] > 0.0 &&
                   (*spacing)[1] > 0.0) {
            grid_spacing = spacing;
        }
    }
    if (auto found = state.find("reference_points");
        found != state.end() && found->is_array()) {
        std::vector<MapPoint> refs;
        for (const Json& value : *found) {
            if (auto point = json_point(value)) {
                refs.push_back(*point);
            }
        }
        reference_points = std::move(refs);
    }
    return true;
}

}  // namespace pwb::ui_composite
