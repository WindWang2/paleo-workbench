#include <pwb/viz/cross_well/section_geometry.hpp>

#include <algorithm>
#include <cctype>
#include <cmath>
#include <limits>

namespace pwb::viz::cross_well {

double WellColumnGeometry::depth_to_y(double depth) const {
    const double content_h = content_height();
    if (content_h <= 0.0) return 0.0;
    const double s = span();
    if (s <= 0.0) return header_height_px;
    return header_height_px + (depth - depth_top) / s * content_h;
}

std::optional<double> WellColumnGeometry::y_to_depth(double y) const {
    const double content_h = content_height();
    if (content_h <= 0.0) return std::nullopt;
    const double s = span();
    if (s <= 0.0) return std::nullopt;
    const double ratio = (y - header_height_px) / content_h;
    return depth_top + ratio * s;
}

double snapped_depth(const SnapInput& curve, double clicked, SnapType type,
                     double window_m) {
    if (type == SnapType::kNone) return clicked;
    if (curve.depths.size() != curve.values.size()) return clicked;
    double best_depth = clicked;
    double best_value = std::numeric_limits<double>::quiet_NaN();
    bool found = false;
    for (std::size_t i = 0; i < curve.depths.size(); ++i) {
        // Python's depth window mask excludes non-finite depths
        // (NaN depth comparisons are False on both bounds).
        if (!std::isfinite(curve.depths[i])) continue;
        if (std::abs(curve.depths[i] - clicked) > window_m) continue;
        if (!found) {
            found = true;
            best_depth = curve.depths[i];
            best_value = curve.values[i];
            continue;
        }
        // numpy argmax/argmin propagates NaN: the FIRST NaN sample in
        // the window wins for both snap types.
        if (std::isnan(curve.values[i])) {
            if (!std::isnan(best_value)) {
                best_value = curve.values[i];
                best_depth = curve.depths[i];
            }
            continue;
        }
        if (std::isnan(best_value)) continue;
        // First extreme wins on ties (strict comparisons).
        if (type == SnapType::kMax && curve.values[i] > best_value) {
            best_value = curve.values[i];
            best_depth = curve.depths[i];
        } else if (type == SnapType::kMin && curve.values[i] < best_value) {
            best_value = curve.values[i];
            best_depth = curve.depths[i];
        }
    }
    // Empty window -> the clicked depth unchanged.
    return best_depth;
}

std::optional<std::string> pick_hit_test(
    const std::vector<PickHitCandidate>& candidates, double click_depth,
    const WellColumnGeometry& geometry, double tolerance_px) {
    const double content_h = geometry.content_height();
    const double s = geometry.span();
    if (content_h <= 0.0 || s <= 0.0) return std::nullopt;
    const double depth_tol = tolerance_px * s / content_h;
    std::optional<std::string> hit;
    double best = std::numeric_limits<double>::infinity();
    for (const PickHitCandidate& candidate : candidates) {
        const double delta = std::abs(candidate.depth - click_depth);
        if (delta > depth_tol) continue;
        if (delta < best) {  // strict <: first wins on ties
            best = delta;
            hit = candidate.pick_id;
        }
    }
    return hit;
}

std::optional<WellCurve> extract_curve(
    const std::vector<WellCurve>& curves,
    const std::vector<std::string>& preferred) {
    auto upper = [](const std::string& value) {
        std::string out;
        out.reserve(value.size());
        for (unsigned char c : value) {
            out.push_back(static_cast<char>(std::toupper(c)));
        }
        return out;
    };
    // Python iterates curves in track order and returns the FIRST whose
    // upper-cased name is in the preferred SET (not preference-priority
    // order).
    for (const WellCurve& curve : curves) {
        const std::string name = upper(curve.name);
        for (const std::string& want : preferred) {
            if (name == upper(want)) return curve;
        }
    }
    if (curves.empty()) return std::nullopt;
    return curves.front();
}

std::pair<double, double> curve_display_range(const WellCurve& curve) {
    double lo = std::numeric_limits<double>::infinity();
    double hi = -std::numeric_limits<double>::infinity();
    for (double v : curve.values) {
        if (!std::isfinite(v)) continue;
        lo = std::min(lo, v);
        hi = std::max(hi, v);
    }
    if (!(lo <= hi)) return {0.0, 1.0};
    return {lo, hi};
}

}  // namespace pwb::viz::cross_well
