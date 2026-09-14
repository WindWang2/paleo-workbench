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
};

inline const char* error_code_string(ErrorCode code) {
    switch (code) {
        case ErrorCode::Ok: return "PWB-GT-000";
        case ErrorCode::InvalidInput: return "PWB-GT-001";
        case ErrorCode::InvalidTolerance: return "PWB-GT-002";
        case ErrorCode::MalformedJson: return "PWB-GT-003";
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

}  // namespace pwb::geotopo
