#include <pwb/viz/cross_well/formation_preview.hpp>

#include <algorithm>
#include <cmath>
#include <limits>
#include <utility>

namespace pwb::viz::cross_well {

std::vector<PreviewConnection> build_preview_connections(
    const std::vector<std::vector<FormationTop>>& tops_per_well) {
    std::vector<PreviewConnection> connections;
    // last_seen: formation -> (well index, top), insertion ordered.
    std::vector<std::pair<std::string, PreviewTopSighting>> last_seen;
    for (std::size_t w = 0; w < tops_per_well.size(); ++w) {
        // Per-well dedup: only the FIRST top of each formation counts.
        std::vector<std::string> seen_formations;
        for (const FormationTop& top : tops_per_well[w]) {
            if (std::find(seen_formations.begin(), seen_formations.end(),
                          top.formation_name) != seen_formations.end()) {
                continue;
            }
            seen_formations.push_back(top.formation_name);
            PreviewTopSighting sighting{w, top};
            for (auto& [name, prev] : last_seen) {
                if (name != top.formation_name) continue;
                if (prev.well_index + 1 == w) {
                    PreviewConnection connection;
                    connection.from_index = prev.well_index;
                    connection.to_index = w;
                    connection.from_top = prev.top;
                    connection.to_top = top;
                    connections.push_back(connection);
                }
                break;
            }
            // Update (insert or replace) the last sighting.
            bool updated = false;
            for (auto& [name, prev] : last_seen) {
                if (name == top.formation_name) {
                    prev = sighting;
                    updated = true;
                    break;
                }
            }
            if (!updated) {
                last_seen.emplace_back(top.formation_name, sighting);
            }
        }
    }
    return connections;
}

std::pair<double, double> preview_full_range(
    const std::vector<std::vector<FormationTop>>& tops_per_well) {
    double min_depth = std::numeric_limits<double>::infinity();
    double max_depth = -std::numeric_limits<double>::infinity();
    for (const std::vector<FormationTop>& tops : tops_per_well) {
        for (const FormationTop& top : tops) {
            min_depth = std::min(min_depth, top.depth_m);
            max_depth = std::max(max_depth, top.depth_m);
        }
    }
    if (!(min_depth <= max_depth)) return {0.0, 1.0};
    return {min_depth, max_depth};
}

std::vector<double> preview_well_x_positions(std::size_t well_count,
                                             double width_px) {
    const double left = kPreviewMarginLeftPx;
    const double right = std::max(left, width_px - kPreviewMarginRightPx);
    std::vector<double> xs;
    if (well_count == 0) return xs;
    if (well_count == 1) {
        xs.push_back((left + right) / 2.0);
        return xs;
    }
    xs.resize(well_count);
    for (std::size_t i = 0; i < well_count; ++i) {
        xs[i] = left + static_cast<double>(i) * (right - left) /
                           static_cast<double>(well_count - 1);
    }
    return xs;
}

double preview_depth_to_y(const PreviewLayout& layout, double depth) {
    const double plot_height =
        std::max(1.0, layout.height_px - kPreviewMarginTopPx -
                          kPreviewMarginBottomPx);
    const double span = layout.view_max_depth - layout.view_min_depth;
    if (span <= 0.0) {
        return kPreviewMarginTopPx + plot_height / 2.0;
    }
    return kPreviewMarginTopPx +
           (depth - layout.view_min_depth) / span * plot_height;
}

std::pair<double, double> preview_clamped_view(const PreviewLayout& layout,
                                               double request_min,
                                               double request_max) {
    const double full_min = layout.full_min_depth;
    const double full_max = layout.full_max_depth;
    const double full_span = full_max - full_min;
    if (full_span <= 0.0) return {full_min, full_max};
    // Python: span = min(full_span, max(full_span*1e-6, max-min)) — the
    // min() applies BEFORE the >= comparison, which matters for the FP
    // noise pattern of wheel-zoom endpoints.
    double span = request_max - request_min;
    const double smallest = full_span * 1e-6;
    if (span < smallest) span = smallest;
    if (span > full_span) span = full_span;
    if (span >= full_span) return {full_min, full_max};
    double lo = std::max(full_min,
                         std::min(request_min, full_max - span));
    return {lo, lo + span};
}

std::pair<double, double> preview_zoomed_view(const PreviewLayout& layout,
                                              double anchor_y, bool zoom_in) {
    const double span = layout.view_max_depth - layout.view_min_depth;
    if (span <= 0.0) return {layout.view_min_depth, layout.view_max_depth};
    const double factor = zoom_in ? 0.8 : 1.25;
    const double full_span = layout.full_max_depth - layout.full_min_depth;
    const double plot_height =
        std::max(1.0, layout.height_px - kPreviewMarginTopPx -
                          kPreviewMarginBottomPx);
    // anchor depth under the cursor in the CURRENT view; ratio keeps it
    // fixed while the span resizes (wheelEvent parity — _depth_at_y
    // CLAMPS the ratio to [0, 1], so a cursor above/below the plot band
    // anchors at the view edge). new_span is pre-clamped to the full
    // span exactly like wheelEvent.
    const double clamped_ratio = std::clamp(
        (anchor_y - kPreviewMarginTopPx) / plot_height, 0.0, 1.0);
    const double anchor_depth =
        layout.view_min_depth + clamped_ratio * span;
    const double ratio = (anchor_depth - layout.view_min_depth) / span;
    double new_span = span * factor;
    const double smallest = full_span * 1e-6;
    if (new_span < smallest) new_span = smallest;
    if (new_span > full_span) new_span = full_span;
    return preview_clamped_view(
        layout, anchor_depth - ratio * new_span,
        anchor_depth + (1.0 - ratio) * new_span);
}

std::pair<double, double> preview_paned_view(const PreviewLayout& layout,
                                             double dy_px) {
    const double span = layout.view_max_depth - layout.view_min_depth;
    if (span <= 0.0) return {layout.view_min_depth, layout.view_max_depth};
    const double plot_height =
        std::max(1.0, layout.height_px - kPreviewMarginTopPx -
                          kPreviewMarginBottomPx);
    const double shift = -dy_px / plot_height * span;
    return preview_clamped_view(layout, layout.view_min_depth + shift,
                                layout.view_max_depth + shift);
}

std::optional<PreviewVisiblePoint> preview_hover_hit(
    const std::vector<PreviewVisiblePoint>& visible_points, double x,
    double y) {
    const PreviewVisiblePoint* best = nullptr;
    double best_dist = kPreviewHoverRadiusPx;
    for (const PreviewVisiblePoint& point : visible_points) {
        const double dist = std::hypot(point.x - x, point.y - y);
        if (dist < best_dist) {
            best_dist = dist;
            best = &point;
        }
    }
    if (best == nullptr) return std::nullopt;
    return *best;
}

}  // namespace pwb::viz::cross_well
