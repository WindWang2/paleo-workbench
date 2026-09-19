#pragma once

// VIZ-B — cross-well section canvas geometry (Qt-free, testable).
// Port of the coordinate contract spread over geoviz_well_log's
// CrossWellWidget/ConnectionOverlay and geoviz_cross_well's canvas.py:
//   * one depth column per well; shared viewport (depth_top/bottom);
//   * depth -> Y: header_h + (depth - top) / span * content_h;
//   * Y -> depth is the exact inverse and is NOT clipped (clicks in the
//     header region return depths above depth_top, Python parity);
//   * degenerate spans / non-positive content height return nullopt on
//     the inverse map and the header height on the forward map;
//   * pick hit tolerance is in SCREEN pixels (10 px), converted per the
//     current zoom via depth_tol = tol_px * span / content_h;
//   * snapping: max/min of the active curve inside a ±window (m) depth
//     band, falling back to the clicked depth.
// The default header height is 56 px (CrossWellWidget contract).

#include <optional>
#include <string>
#include <vector>

namespace pwb::viz::cross_well {

inline constexpr double kDefaultHeaderHeightPx = 56.0;
inline constexpr double kDefaultPickTolerancePx = 10.0;
inline constexpr double kDefaultSnapWindowM = 1.5;

// One well column's viewport mapping inputs.
struct WellColumnGeometry {
    double depth_top = 0.0;
    double depth_bottom = 100.0;
    double header_height_px = kDefaultHeaderHeightPx;
    double canvas_height_px = 0.0;  // content + header
    double canvas_left_px = 0.0;    // section-space left edge
    double canvas_right_px = 0.0;   // section-space right edge

    [[nodiscard]] double span() const { return depth_bottom - depth_top; }
    [[nodiscard]] double content_height() const {
        return canvas_height_px - header_height_px;
    }
    // Forward map; degenerate span -> header height, non-positive content
    // -> 0 (Python ConnectionOverlay parity).
    [[nodiscard]] double depth_to_y(double depth) const;
    // Inverse map; nullopt when no tracks / content<=0 / span<=0 (the
    // caller's "no tracks" case is represented by an unset geometry).
    [[nodiscard]] std::optional<double> y_to_depth(double y) const;
};

enum class SnapType { kNone, kMax, kMin };

struct SnapInput {
    std::vector<double> depths;  // ascending samples of the active curve
    std::vector<double> values;
};

// Window is [clicked - window_m, clicked + window_m]; max/min picks the
// extreme SAMPLE depth inside the window; empty window / snap none ->
// clicked depth unchanged.
[[nodiscard]] double snapped_depth(const SnapInput& curve, double clicked,
                                   SnapType type, double window_m);

// Pick hit-test: smallest |pick_depth - depth_at_click| (strict <, first
// wins on exact ties) among candidates, converted through the screen
// tolerance. Returns the index of the hit pick.
struct PickHitCandidate {
    double depth = 0.0;
    std::string pick_id;
};
[[nodiscard]] std::optional<std::string> pick_hit_test(
    const std::vector<PickHitCandidate>& candidates, double click_depth,
    const WellColumnGeometry& geometry,
    double tolerance_px = kDefaultPickTolerancePx);

// Curve extraction preference order (canvas.py _extract_curve): first
// curve whose upper-cased name is in preferred (scanning in column
// order), else the first curve of the well. Returns nullopt when the
// well has no curves.
struct WellCurve {
    std::string name;
    std::vector<double> depths;
    std::vector<double> values;
};
[[nodiscard]] std::optional<WellCurve> extract_curve(
    const std::vector<WellCurve>& curves,
    const std::vector<std::string>& preferred);

// Display range of a curve: finite min/max; empty/no-finite -> (0, 1).
[[nodiscard]] std::pair<double, double> curve_display_range(
    const WellCurve& curve);

// One display column of the section (value type shared by the widget
// and the export path).
struct WellColumnData {
    std::string name;
    std::vector<WellCurve> curves;
    // The curve drawn in this column (already extracted); display
    // range comes from curve_display_range.
    WellCurve display_curve;
};

}  // namespace pwb::viz::cross_well
