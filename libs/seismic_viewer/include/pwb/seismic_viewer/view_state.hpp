#pragma once

// VIZ-D seismic view-state schema (line 07 owns this schema).
//
// Persistence of the advanced display state so the SAME volume reopens with
// an identical view: display mode, SEG polarity, wiggle gain, percentile
// clip, colormap, slice axis/index, value range, zoom/pan transform, picking
// enablement and the horizon pick set (embedded, with its own binding
// block). Ports the intent of the frozen Python project state
// (geo-viz-engine@08851951, seismic_view.py:372 get_project_state ->
// file_path/slice_positions/colormap/render_mode) extended by the VIZ-D
// control surface the C++ widget actually exposes.
//
// Cross-volume restore is REJECTED (unlike horizon picks, which load with a
// mismatch note): from_json validates schema shape, and the widget refuses
// to apply a state whose volume_id differs from the current binding —
// a restored view of another body must never silently reshape this one.
//
// JSON conventions follow libs/domain (nlohmann::ordered_json, declared key
// order). The picks member embeds horizon::HorizonPickSet JSON verbatim
// (schema_version 1), so picks persist with the same codec as save_picks.

#include <cstdint>
#include <string>

#include <pwb/domain/json.hpp>

namespace pwb::seismic_viewer {

inline constexpr int kSeismicViewStateSchemaVersion = 1;

struct SeismicViewState {
    int schema_version{kSeismicViewStateSchemaVersion};
    // Volume binding: stable domain id ("" = anonymous test volume). Restore
    // is rejected when the stored non-empty id differs from the current
    // volume id; two anonymous (empty) bindings count as matching.
    std::string volume_id;
    std::uint64_t volume_version{0}; // diagnostic only, not compared
    // View (axis: "inline" | "crossline" | "sample").
    std::string axis{"inline"};
    std::int64_t slice_index{0};
    std::string color_map{"seismic"};
    // Display ("variable_density" | "wiggle").
    std::string display_mode{"variable_density"};
    bool polarity_normal{true};
    bool clip_enabled{false};
    double clip_percentile{99.0};
    double wiggle_gain{2.0};
    bool auto_range{true};
    double range_min{0.0};
    double range_max{1.0};
    double view_scale{1.0};
    double view_offset_x{0.0};
    double view_offset_y{0.0};
    bool picking_enabled{false};
    // Embedded horizon::HorizonPickSet JSON document (object, with its own
    // binding block; empty pick set allowed). Loading re-parses it through
    // horizon::from_json, so picks persist with the same codec as
    // save_picks.
    domain::Json picks = domain::Json::object();
};

// Serialize in the declared key order (Python-compatible dump: indent=2,
// trailing newline).
[[nodiscard]] std::string to_json_text(const SeismicViewState& state);

enum class ViewStateParse : std::uint8_t { ok, bad_json, bad_schema };

// Strict parse: unknown schema_version or missing/mistyped required keys are
// bad_schema (fail closed); JSON syntax errors are bad_json.
[[nodiscard]] ViewStateParse
from_json_text(std::string_view text, SeismicViewState& state, std::string& error);

} // namespace pwb::seismic_viewer
