// survey.cpp — SurveySpec + survey_from_corners (survey.py @ 08851951).
#include "pwb/geo3d_viz/joint/survey.hpp"

#include <cmath>

namespace pwb::geo3d_viz::joint {

std::pair<double, double> SurveySpec::xy_to_il_xl(double x, double y) const {
    const auto [il_frac, xl_frac] = bin_grid.xy_to_il_xl(x, y);
    return {static_cast<double>(iline_start) +
                il_frac * static_cast<double>(iline_step),
            static_cast<double>(xline_start) +
                xl_frac * static_cast<double>(xline_step)};
}

std::pair<double, double> SurveySpec::il_xl_to_xy(double iline,
                                                  double xline) const {
    const double il_step =
        iline_step != 0 ? static_cast<double>(iline_step) : 1.0;
    const double xl_step =
        xline_step != 0 ? static_cast<double>(xline_step) : 1.0;
    const double il_frac = (iline - static_cast<double>(iline_start)) / il_step;
    const double xl_frac =
        (xline - static_cast<double>(xline_start)) / xl_step;
    return bin_grid.il_xl_to_xy(il_frac, xl_frac);
}

namespace {

// Resolve (step, count) for one axis from the corner span.
std::pair<std::int64_t, std::int64_t> resolve(std::int64_t corner_span,
                                              std::optional<std::int64_t> step,
                                              std::optional<std::int64_t> count,
                                              const char* label) {
    std::int64_t resolved_step = 1;
    if (step.has_value()) {
        resolved_step = *step != 0 ? *step : 1;
    } else {
        resolved_step = corner_span >= 0 ? 1 : -1;
    }
    std::int64_t resolved_count = 0;
    if (count.has_value()) {
        resolved_count = *count < 1 ? 1 : *count;
    } else {
        resolved_count =
            static_cast<std::int64_t>(std::llround(std::fabs(
                static_cast<double>(corner_span)))) + 1;
    }
    const std::int64_t span =
        (resolved_count - 1) * (resolved_step < 0 ? -resolved_step
                                                  : resolved_step);
    if (std::llround(std::fabs(static_cast<double>(corner_span))) != span &&
        resolved_step != 0) {
        throw std::invalid_argument(
            std::string(label) + ": corner numbers span " +
            std::to_string(corner_span) + " but " +
            std::to_string(resolved_count) + " lines x step " +
            std::to_string(resolved_step) + " span " + std::to_string(span));
    }
    if ((corner_span < 0) != (resolved_step < 0) && corner_span != 0) {
        resolved_step = -resolved_step;
    }
    return {resolved_step, resolved_count};
}

}  // namespace

SurveySpec survey_from_corners(const Corner& p1, const Corner& p2,
                               const Corner& p3, std::int64_t n_samples,
                               double dt_ms, double t0_ms,
                               std::optional<std::int64_t> iline_step,
                               std::optional<std::int64_t> xline_step,
                               std::optional<std::int64_t> n_inlines,
                               std::optional<std::int64_t> n_crosslines) {
    const double il0 = p1[0], xl0 = p1[1], x0 = p1[2], y0 = p1[3];
    const double il0b = p2[0], xl1 = p2[1], x1 = p2[2], y1 = p2[3];
    const double il1 = p3[0], xl1b = p3[1], x2 = p3[2], y2 = p3[3];

    if (std::fabs(il0 - il0b) > 1e-6) {
        throw std::invalid_argument(
            "p1 and p2 must share the same inline number");
    }
    if (std::fabs(xl1 - xl1b) > 1e-6) {
        throw std::invalid_argument(
            "p2 and p3 must share the same crossline number");
    }

    auto [il_step_resolved, n_il] = resolve(
        static_cast<std::int64_t>(std::llround(il1 - il0)), iline_step,
        n_inlines, "inline");
    auto [xl_step_resolved, n_xl] = resolve(
        static_cast<std::int64_t>(std::llround(xl1 - xl0)), xline_step,
        n_crosslines, "crossline");

    // Distance along the XL edge (p1→p2) and IL edge (p2→p3): the physical
    // edge length spans (count-1) bins regardless of the line-number step.
    const double xl_len = std::hypot(x1 - x0, y1 - y0);
    const double il_len = std::hypot(x2 - x1, y2 - y1);
    // V6 §9 (P0): all-zero/degenerate SourceX/Y must not become a
    // valid-looking survey — refuse instead of fabricating 1 m bins.
    if (xl_len <= 1e-6 || il_len <= 1e-6) {
        throw std::invalid_argument(
            "survey corners carry no coordinate extent (XL edge " +
            std::to_string(xl_len) + " m, IL edge " + std::to_string(il_len) +
            " m; SourceX/Y all zero or missing) — refusing to fabricate "
            "survey geometry");
    }
    double xl_spacing = n_xl > 1 ? xl_len / static_cast<double>(n_xl - 1)
                                 : 1.0;
    double il_spacing = n_il > 1 ? il_len / static_cast<double>(n_il - 1)
                                 : 1.0;

    // Azimuth of the inline axis from north (+Y), clockwise
    // (BinGridGeometry convention). IL direction: p2→p3. For classic
    // IL=+Y/XL=+X, az=0. BinGrid with positive spacing has
    // IL unit = (-sin az, cos az); flip spacing signs when the corners
    // require the opposite direction (wayfinder #84, e.g. IL along +X).
    const double il_dx = x2 - x1;
    const double il_dy = y2 - y1;
    const double az_deg = il_dx != 0.0 || il_dy != 0.0
                              ? std::atan2(il_dx, il_dy) * 180.0 / M_PI
                              : 0.0;
    const double sin_a = std::sin(az_deg * M_PI / 180.0);
    const double cos_a = std::cos(az_deg * M_PI / 180.0);
    const double pred_il[2] = {-sin_a, cos_a};
    const double pred_xl[2] = {cos_a, sin_a};
    const double des_il[2] = {il_dx, il_dy};
    const double des_xl[2] = {x1 - x0, y1 - y0};
    if (pred_il[0] * des_il[0] + pred_il[1] * des_il[1] < 0) {
        il_spacing = -il_spacing;
    }
    if (pred_xl[0] * des_xl[0] + pred_xl[1] * des_xl[1] < 0) {
        xl_spacing = -xl_spacing;
    }

    SurveySpec spec;
    spec.bin_grid.x_origin = x0;
    spec.bin_grid.y_origin = y0;
    spec.bin_grid.il_azimuth_deg = az_deg;
    spec.bin_grid.il_spacing_m = il_spacing;
    spec.bin_grid.xl_spacing_m = xl_spacing;
    spec.iline_start = static_cast<std::int64_t>(std::llround(il0));
    spec.iline_step = il_step_resolved;
    spec.xline_start = static_cast<std::int64_t>(std::llround(xl0));
    spec.xline_step = xl_step_resolved;
    spec.n_inlines = n_il;
    spec.n_crosslines = n_xl;
    spec.n_samples = n_samples;
    spec.dt_ms = dt_ms;
    spec.t0_ms = t0_ms;
    return spec;
}

}  // namespace pwb::geo3d_viz::joint
