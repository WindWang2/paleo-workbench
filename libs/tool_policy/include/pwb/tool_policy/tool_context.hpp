#pragma once

// Port of paleo_workbench/mapping/tool_context.py (contract_version=4).
// Immutable-by-convention snapshot of everything the evaluator may know;
// field defaults mirror the Python dataclass defaults exactly.

#include <optional>
#include <string>
#include <vector>

namespace pwb::tool_policy {

inline constexpr int kToolContextContractVersion = 4;

struct ToolContextSnapshot {
    // Project / environment
    bool project_open = true;
    bool qgis_available = false;
    bool native_canvas_available = false;
    std::string backend_mode = "unknown";   // native|degraded|unavailable|unknown
    std::string backend_reason;
    std::string blocking_task;

    // Stage semantics (unset = surface without stage semantics; ""/unknown
    // fails closed in the evaluator).
    std::optional<std::string> mapping_stage;
    bool write_granted = false;

    // Active layer facts
    std::string active_layer_id;
    std::string active_layer_kind;   // "point"|"line"|"polygon"|""
    std::string layer_name;
    std::string layer_role;
    std::string layer_role_label;
    bool layer_is_facies = false;
    std::string artifact_maturity;   // raw/draft/reviewed/frozen/published
    bool layer_frozen = false;
    bool layer_missing = false;
    bool layer_degraded = false;
    std::string qgis_layer_type;     // "vector"|"raster"|""
    std::string wkb_type;
    bool vector_writable = false;

    // Editing session
    bool editing = false;
    bool dirty = false;
    std::optional<bool> edit_gate_open;    // host gate verdict; unset = unknown
    std::string edit_gate_reason;
    bool raw_locked = false;
    bool stage_locked = false;
    bool can_undo = false;
    bool can_redo = false;

    // Selection
    int selection_count = 0;
    std::vector<std::string> selection_geometry_types;
    int compatible_polygon_count = 0;
    int topology_error_count = 0;

    // Split/merge/reshape inputs (host precomputed; rules stay pure)
    bool split_ready = false;
    bool merge_ready = false;
    bool reshape_ready = false;

    // V10 complex-geometry facts
    int selection_multipart_count = 0;
    bool collect_ready = false;

    // GIS state
    bool snapping_available = true;
    bool snapping_enabled = false;
    bool topology_available = true;
    bool topology_enabled = false;
    bool avoid_intersections_enabled = true;
    bool tracing_enabled = false;
    bool vertex_all_layers = true;
    bool crs_valid = true;
    std::string project_crs;
    std::string layer_crs;
    double scale_denominator = 0.0;

    // V10 M3 snapping-config/CRS presentation facts
    double snapping_tolerance_px = 0.0;
    std::vector<std::string> snapping_modes;
    int snapping_reference_count = 0;
    std::optional<bool> snapping_role_recommended;
    std::string canvas_destination_crs;
    std::optional<bool> crs_mismatch;
    int reference_failed_count = 0;
    int running_task_count = 0;

    // V10 map-settings facts and provider introspection
    std::string canvas_crs;
    std::string map_units;
    double output_dpi = 0.0;
    std::optional<bool> provider_writable;
    std::string provider_name;
    bool provider_writable_approximate = false;

    // Tool state
    std::string current_tool = "pan";
    std::vector<std::string> capability_flags;
    int queryable_layer_count = 0;

    // Extent history
    bool can_previous_extent = false;
    bool can_next_extent = false;

    int contract_version = kToolContextContractVersion;

    bool has_active_layer() const { return !active_layer_id.empty(); }
    bool has_active_vector_layer() const {
        return has_active_layer() && qgis_layer_type != "raster";
    }
    bool has_capability(const std::string& flag) const;
};

}  // namespace pwb::tool_policy
