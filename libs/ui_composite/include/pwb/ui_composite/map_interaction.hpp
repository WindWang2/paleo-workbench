#pragma once

// Port of paleo_workbench/mapping/map_interaction.py (UI-13):
// cached host-side hit testing, selection and snapping for map tools.
//
// FeatureSpatialIndex is deliberately a small reusable geometry service:
// it caches feature bounds per data/edit revision and never asks a
// renderer (or a graphics item) to answer authoritative selection or
// snapping questions. SnappingService is the map-level configurable
// facade sharing those cached layer indexes.
//
// Qt-free.

#include <cstdint>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <utility>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/ui_data_core/map_edit_geometry.hpp>
#include <pwb/ui_composite/vector_layer.hpp>

namespace pwb::ui_composite {

using pwb::domain::Json;
using pwb::ui_data_core::MapPoint;

struct SnapMatch {
    std::string feature_id;
    MapPoint point;
    std::string mode;
    double distance = 0.0;

    bool operator==(const SnapMatch&) const = default;
};

// Revision-cached, cell-indexed feature/vertex/segment candidates.
class FeatureSpatialIndex {
public:
    explicit FeatureSpatialIndex(VectorLayer* layer) : layer_(layer) {}

    VectorLayer* layer() const { return layer_; }

    // identify: top-most feature under point within tolerance (reverse
    // draw order); nullopt when nothing hits.
    std::optional<std::string> identify(const MapPoint& point,
                                        double tolerance);

    // identify_vertex: nearest vertex within tolerance → (feature_id,
    // path); Point geometry reports the empty path accepted by
    // VectorEditSession::set_vertex.
    std::optional<std::pair<std::string, std::vector<int>>> identify_vertex(
        const MapPoint& point, double tolerance);

    // select_rectangle: feature ids whose bounds intersect the rect.
    std::set<std::string> select_rectangle(const MapPoint& start,
                                           const MapPoint& end);

    // snap: nearest snap candidate among the enabled modes
    // (default vertex+segment+midpoint); nullopt when nothing in range.
    std::optional<SnapMatch> snap(
        const MapPoint& point, double tolerance,
        const std::set<std::string>& modes = {"vertex", "segment",
                                              "midpoint"});

private:
    void ensure();
    std::pair<int64_t, int64_t> current_revision() const;
    std::pair<int64_t, int64_t> cell(const MapPoint& point) const;
    // Cells covered by bounds; nullopt when the range spans more than
    // _MAX_QUERY_CELLS → callers scan every bucket (FeatureQueryIndex
    // parity).
    std::optional<std::vector<std::pair<int64_t, int64_t>>> query_cells(
        const std::array<double, 4>& bounds) const;

    VectorLayer* layer_;
    std::pair<int64_t, int64_t> revision_ = {-1, -2};  // never equal
    std::vector<VectorFeature> features_;
    std::map<std::string, size_t> draw_order_;
    std::map<std::string, std::array<double, 4>> bounds_;
    std::map<std::string,
             std::vector<std::pair<MapPoint, std::vector<int>>>> vertices_;
    double cell_size_ = 1.0;
    std::map<std::pair<int64_t, int64_t>, std::set<std::string>>
        feature_cells_;
    struct VertexEntry {
        std::string feature_id;
        MapPoint point;
        std::vector<int> path;
        bool endpoint;
    };
    std::map<std::pair<int64_t, int64_t>, std::vector<VertexEntry>>
        vertex_cells_;
    struct SegmentEntry {
        std::string feature_id;
        MapPoint start;
        MapPoint end;
        bool operator<(const SegmentEntry& other) const {
            return std::tie(feature_id, start, end) <
                   std::tie(other.feature_id, other.start, other.end);
        }
        bool operator==(const SegmentEntry&) const = default;
    };
    std::map<std::pair<int64_t, int64_t>, std::set<SegmentEntry>>
        segment_cells_;
};

// Map-level configurable snapping facade sharing cached layer indexes.
class SnappingService {
public:
    explicit SnappingService(double pixel_tolerance = 10.0)
        : pixel_tolerance(pixel_tolerance < 0.0 ? 0.0 : pixel_tolerance) {}

    bool enabled = false;
    double pixel_tolerance;
    std::set<std::string> modes = {"vertex", "segment", "midpoint"};
    bool current_layer_only = false;
    // V12 M1-6：全局容差单位（"px" 像素 / "map" 地图单位 / "layer" 层单
    // 位）。缺省像素（历史语义）；单位随 snapshot_state 持久化。
    std::string tolerance_units = "px";
    // 逐层容差单位覆盖（layer id → 单位词表；缺省跟随全局）。
    std::map<std::string, std::string> layer_tolerance_units;
    // V12 M4-3a：比例依赖捕捉的最小比例尺分母（nullopt/<=0 = 关闭）。
    std::optional<double> scale_minimum;
    std::map<std::string, bool> layer_enabled;
    std::map<std::string, std::set<std::string>> layer_modes;
    // 每图层覆盖：容差（像素）与优先级（数值小者优先，仅作等距平手裁
    // 决）。
    std::map<std::string, double> layer_tolerance;
    std::map<std::string, int> layer_priority;
    MapPoint grid_origin = {0.0, 0.0};
    std::optional<MapPoint> grid_spacing;
    std::vector<MapPoint> reference_points;
    std::optional<SnapMatch> last_match;

    // Cached per-layer index (identity-keyed; rebuilt when the layer
    // object differs).
    FeatureSpatialIndex& index_for(VectorLayer* layer);

    void set_reference_points(const std::vector<MapPoint>& points);

    // 应用角色推荐 profile 到该层的 per-layer 覆盖（V9 W4）。推荐写进
    // 既有 layer_modes/layer_tolerance 覆盖通道（不建第二状态源）；全
    // 局开关/其它层配置不动。返回推荐解释（供状态条呈现），角色无
    // profile 时返回 nullopt 且不改动任何配置。
    std::optional<std::string> apply_role_profile(
        const std::string& layer_id, const std::string& role_value);

    // set_grid: spacing nullopt disables; non-positive spacing or
    // non-finite origin throws std::invalid_argument (Python ValueError).
    void set_grid(const std::optional<MapPoint>& spacing,
                  const MapPoint& origin = {0.0, 0.0});

    // snap: 按全局容差（调用方换算为地图单位）与每图层像素覆盖捕捉。
    // layer_tolerance 以像素存储（配置 UI 语义）；消费时乘
    // map_units_per_pixel 换算为地图单位。返回吸附后坐标（未吸附返回
    // 原点），last_match 记录命中的 SnapMatch。
    MapPoint snap(const MapPoint& point, double tolerance,
                  const std::vector<VectorLayer*>& layers,
                  double map_units_per_pixel = 1.0);

    // snapshot_state: 纯数据、可 JSON 序列化的完整状态快照（V10
    // Milestone N；schema_version=1 供工程文档持久化）。
    Json snapshot_state() const;

    // restore_state: 从快照恢复；schema_version 缺失或不认识返回 false
    //（严格版本门禁；字段缺失保持当前默认，类型不符的字段跳过）。
    bool restore_state(const Json& state);

    // Drop cached indexes (e.g. layer set replaced).
    void clear_indexes() { indexes_.clear(); }
    void forget_index(const std::string& layer_id) {
        indexes_.erase(layer_id);
    }

private:
    std::map<std::string, FeatureSpatialIndex> indexes_;
};

}  // namespace pwb::ui_composite
