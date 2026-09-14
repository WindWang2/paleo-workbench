// geological_topology_core.hpp — geological topology core (geotopo tickets).
//
// ZERO QGIS/Qt dependency on purpose: the planar-subdivision engine (control
// line noding → DCEL → minimal-cycle face tracing) is pure std:: so it stays
// unit-testable through qgis_render_bridge_selftest and honours the bridge
// POD-isolation rule (GeoJSON parsing/serialization lives in bindings.cpp).
// Contract: docs/development/geotopo-editor/02-interface-contracts.md.

#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace pwb::geotopo {

// Contract error codes (02-interface-contracts §3).  The numeric values are
// stable API: hosts parse the "PWB-GT-xxx" string, the enum only orders them.
enum class ErrorCode {
    Ok = 0,
    InvalidInput = 1,      // PWB-GT-001
    InvalidTolerance = 2,  // PWB-GT-002
    MalformedJson = 3,     // PWB-GT-003 (raised by the binding adapter)
    ArcNotFound = 201,     // PWB-GT-201（重塑：弧在容差内不唯一/未匹配）
    RingInvalid = 202,     // PWB-GT-202（重塑：新环非法）
    OverlapFailed = 203,   // PWB-GT-203（重塑：重叠校验失败）
    ConservationFailed = 204,  // PWB-GT-204（重塑：面积守恒失败）
    SessionState = 301,    // PWB-GT-301（会话/状态非法）
};

inline const char* error_code_string(ErrorCode code) {
    switch (code) {
        case ErrorCode::Ok: return "PWB-GT-000";
        case ErrorCode::InvalidInput: return "PWB-GT-001";
        case ErrorCode::InvalidTolerance: return "PWB-GT-002";
        case ErrorCode::MalformedJson: return "PWB-GT-003";
        case ErrorCode::ArcNotFound: return "PWB-GT-201";
        case ErrorCode::RingInvalid: return "PWB-GT-202";
        case ErrorCode::OverlapFailed: return "PWB-GT-203";
        case ErrorCode::ConservationFailed: return "PWB-GT-204";
        case ErrorCode::SessionState: return "PWB-GT-301";
    }
    return "PWB-GT-001";
}

// A control line: paleo shoreline, facies-change boundary or fault trace.
// Coordinates are flat CRS-plane doubles [[x0,y0,x1,y1,...]].
struct ControlLineInput {
    std::string id;
    std::vector<double> xy;
};

struct PolygonFace {
    std::vector<double> exterior_xy;  // closed ring [x0,y0,...,x0,y0], CCW
    double area = 0.0;
    double centroid_x = 0.0;
    double centroid_y = 0.0;
    std::vector<std::string> source_lines;  // parent control lines of the ring
};

struct PolygonizeOptions {
    double tolerance = 1e-6;
    bool has_clip = false;
    double clip_xmin = 0.0, clip_ymin = 0.0, clip_xmax = 0.0, clip_ymax = 0.0;
    double min_ring_area = 0.0;
};

struct PolygonizeResult {
    ErrorCode error = ErrorCode::Ok;
    std::string message;
    std::vector<PolygonFace> faces;
    std::size_t dropped_dangles = 0;  // pruned dangling edges (dead-end tips)
    std::size_t node_count = 0;
    std::size_t edge_count = 0;       // deduplicated undirected DCEL edges
    double elapsed_ms = 0.0;
};

// Builds the planar subdivision of the control-line network and returns every
// bounded face as a minimal cycle (unbounded outer face excluded, optional
// clip envelope drops faces not fully inside it).  Thread-safe, allocation
// confined to the returned result; no globals.
PolygonizeResult polygonize_control_lines(
    const std::vector<ControlLineInput>& lines,
    const PolygonizeOptions& options);

// JSON envelope serialization ({"status":"ok",...} / {"status":"error",...});
// std-only string building so the core stays Qt-free.
std::string polygonize_result_to_json(const PolygonizeResult& result);

// ---------------------------------------------------------------------------
// geotopo Ticket 3：共边查找与联动重塑（RFC §4）。环 = 平面坐标 flat
// [x0,y0,...]（闭合点可带可不带——内部一律按开链规范化）。

struct SharedArc {
    std::vector<double> arc_xy;  // 共享顶点链（开链，含首末）
    double length = 0.0;
    double start_x = 0.0, start_y = 0.0, end_x = 0.0, end_y = 0.0;
};

struct SharedArcsResult {
    ErrorCode error = ErrorCode::Ok;
    std::string message;
    std::vector<SharedArc> arcs;
};

// 两环在容差内的全部共享弧链（≥2 节点 = ≥1 边）；角点触碰不算弧。
SharedArcsResult find_shared_arcs(const std::vector<double>& ring_a_xy,
                                  const std::vector<double>& ring_b_xy,
                                  double tolerance);

struct ReshapePairResult {
    ErrorCode error = ErrorCode::Ok;
    std::string message;
    std::vector<double> polygon_a_xy;  // 闭合 CCW 外环
    std::vector<double> polygon_b_xy;
    double area_before = 0.0;
    double area_after = 0.0;
    double area_residual = 0.0;
};

// 把两环共享的 arc 段同曲线 curve 替换（一侧正向、一侧反向）。守恒三校验：
// 弧唯一匹配（201）、新环自交（202）、两新环跨交重叠（203）、面积和守恒
// （204）。拒绝式：任一失败两侧零变更（输出环为空）。
ReshapePairResult reshape_shared_arc(const std::vector<double>& ring_a_xy,
                                     const std::vector<double>& ring_b_xy,
                                     const std::vector<double>& arc_xy,
                                     const std::vector<double>& curve_xy,
                                     double tolerance);

std::string shared_arcs_result_to_json(const SharedArcsResult& result);
std::string reshape_pair_result_to_json(const ReshapePairResult& result);

}  // namespace pwb::geotopo
