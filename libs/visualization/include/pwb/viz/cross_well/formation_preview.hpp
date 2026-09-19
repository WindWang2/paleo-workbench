#pragma once

// VIZ-B — formation tops preview geometry (Qt-free).
// Port of geoviz_cross_well/formation_preview.py's layout math:
//   margins left 64 / right 120 / top 38 / bottom 38 px;
//   connection lines only between ADJACENT wells (a formation missing in
//   an intermediate well breaks the line — no cross-well bridging);
//   per-well first-sighting dedup per formation;
//   view clamp rules and wheel-zoom anchor math are exact.

#include <optional>
#include <string>
#include <vector>

#include <pwb/viz/cross_well/tops_model.hpp>

namespace pwb::viz::cross_well {

inline constexpr double kPreviewMarginLeftPx = 64.0;
inline constexpr double kPreviewMarginRightPx = 120.0;
inline constexpr double kPreviewMarginTopPx = 38.0;
inline constexpr double kPreviewMarginBottomPx = 38.0;

struct PreviewTopSighting {
    std::size_t well_index = 0;
    FormationTop top;
};

// Connection line between adjacent wells (i, i+1).
struct PreviewConnection {
    std::size_t from_index = 0;
    std::size_t to_index = 0;
    FormationTop from_top;
    FormationTop to_top;
};

// Build the (dedup + adjacency filtered) connection list for a
// well-sorted top list. Wells must be pre-sorted (set_tops semantics:
// sorted unique well names).
[[nodiscard]] std::vector<PreviewConnection> build_preview_connections(
    const std::vector<std::vector<FormationTop>>& tops_per_well);

struct PreviewLayout {
    double width_px = 320.0;
    double height_px = 220.0;
    double full_min_depth = 0.0;
    double full_max_depth = 1.0;
    double view_min_depth = 0.0;
    double view_max_depth = 1.0;
};

// Full depth range of the tops (0, 1 when empty).
[[nodiscard]] std::pair<double, double> preview_full_range(
    const std::vector<std::vector<FormationTop>>& tops_per_well);

// Well x positions: single well -> centre of the plot band; otherwise
// left + i * (right - left) / (N-1), right = max(left, width - RIGHT).
[[nodiscard]] std::vector<double> preview_well_x_positions(
    std::size_t well_count, double width_px);

// Depth -> y in [TOP, height - BOTTOM]; span <= 0 -> vertical centre of
// the plot band (zero-thickness view).
[[nodiscard]] double preview_depth_to_y(const PreviewLayout& layout,
                                        double depth);

// View clamping: full span <= 0 -> full range; requested span < tiny ->
// smallest; span >= full -> reset to full; else pan-clamp the window
// inside the full range. Returns the clamped (min, max).
[[nodiscard]] std::pair<double, double> preview_clamped_view(
    const PreviewLayout& layout, double request_min, double request_max);

// Wheel zoom: factor 0.8 zoom-in on positive delta / 1.25 zoom-out; the
// depth under anchor_y stays put. No span -> no change.
[[nodiscard]] std::pair<double, double> preview_zoomed_view(
    const PreviewLayout& layout, double anchor_y, bool zoom_in);

// Drag pan: shift = -dy_px / plot_height * span (upward drag increases
// depth). No span -> no change.
[[nodiscard]] std::pair<double, double> preview_paned_view(
    const PreviewLayout& layout, double dy_px);

// Nearest visible top within 9 px (Euclidean) of (x, y); nullopt when
// none. visible_points is the caller's painted-point cache.
struct PreviewVisiblePoint {
    double x = 0.0;
    double y = 0.0;
    std::string well;
    std::string formation;
    double depth = 0.0;
};
inline constexpr double kPreviewHoverRadiusPx = 9.0;
[[nodiscard]] std::optional<PreviewVisiblePoint> preview_hover_hit(
    const std::vector<PreviewVisiblePoint>& visible_points, double x,
    double y);

}  // namespace pwb::viz::cross_well
