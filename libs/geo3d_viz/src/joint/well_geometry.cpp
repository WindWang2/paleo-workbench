// well_geometry.cpp — trajectory projection + curve overlays
// (well_geometry.py @ 08851951).
#include "pwb/geo3d_viz/joint/well_geometry.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <limits>
#include <stdexcept>
#include <string>

namespace pwb::geo3d_viz::joint {

namespace {

std::string truncated_warning(const std::string& name, double lo, double hi) {
    char buf[256];
    std::snprintf(buf, sizeof(buf), "%.1f", lo);
    std::string los(buf);
    std::snprintf(buf, sizeof(buf), "%.1f", hi);
    return "Well " + name +
           ": trajectory truncated to the TD table range [" + los + ", " +
           buf + "] m; deeper extent is not calibrated";
}

// frac = linspace(0, 1, n); xs/ys along head→bottom, md = frac * TD.
struct LinspacePath {
    std::vector<double> xs;
    std::vector<double> ys;
    std::vector<double> md;
};

LinspacePath linspace_path(const WellHead& well, std::size_t n_samples) {
    const std::size_t n = n_samples < 2 ? 2 : n_samples;
    LinspacePath path;
    path.xs.reserve(n);
    path.ys.reserve(n);
    path.md.reserve(n);
    for (std::size_t i = 0; i < n; ++i) {
        const double frac = static_cast<double>(i) /
                            static_cast<double>(n - 1);
        path.xs.push_back(well.x + frac * (well.bottom_x - well.x));
        path.ys.push_back(well.y + frac * (well.bottom_y - well.y));
        path.md.push_back(frac * well.total_depth_m);
    }
    return path;
}

bool all_finite(const std::vector<double>& v) {
    for (double x : v) {
        if (!std::isfinite(x)) return false;
    }
    return true;
}

WellTrajectory3D head_only(const WellHead& well,
                           std::optional<std::string> warning) {
    WellTrajectory3D traj;
    traj.name = well.name;
    traj.points = {{well.x, well.y, 0.0}};
    traj.has_td = false;
    traj.warning = std::move(warning);
    return traj;
}

}  // namespace

std::optional<std::pair<double, double>> pierce_xy_at_z(
    const std::vector<std::array<double, 3>>& points, double z, double atol) {
    if (points.empty()) return std::nullopt;
    const double zz = z;
    // Exact-hit pass first.
    for (const auto& p : points) {
        if (std::fabs(p[2] - zz) <= atol) {
            return std::make_pair(p[0], p[1]);
        }
    }
    if (points.size() < 2 || !std::isfinite(zz)) return std::nullopt;
    double lo = std::numeric_limits<double>::infinity();
    double hi = -std::numeric_limits<double>::infinity();
    bool any_finite = false;
    for (const auto& p : points) {
        if (std::isfinite(p[2])) {
            any_finite = true;
            lo = std::min(lo, p[2]);
            hi = std::max(hi, p[2]);
        }
    }
    if (!any_finite) return std::nullopt;
    if (zz < lo - atol || zz > hi + atol) return std::nullopt;
    for (std::size_t i = 0; i + 1 < points.size(); ++i) {
        const double z0 = points[i][2];
        const double z1 = points[i + 1][2];
        if (!std::isfinite(z0) || !std::isfinite(z1)) continue;
        if ((z0 - zz) * (z1 - zz) > 0) continue;
        const double denom = z1 - z0;
        double t = 0.0;
        if (std::fabs(denom) >= atol) t = (zz - z0) / denom;
        t = std::max(0.0, std::min(1.0, t));
        const double x = points[i][0] + t * (points[i + 1][0] - points[i][0]);
        const double y = points[i][1] + t * (points[i + 1][1] - points[i][1]);
        return std::make_pair(x, y);
    }
    return std::nullopt;
}

WellTrajectory3D project_well_trajectory(
    const WellHead& well, VerticalDomain domain, const TimeDepthTable* td,
    std::size_t n_samples, const DepthTransformState* depth_transform) {
    if (domain == VerticalDomain::Time) {
        if (td == nullptr) {
            return head_only(
                well, "Well " + well.name +
                          ": missing time-depth table; showing wellhead only "
                          "in Time domain");
        }
        auto path = linspace_path(well, n_samples);
        std::vector<double> twt = td->md_to_time_ms(path.md);
        // V6 §8: samples beyond the calibrated TD range are dropped (NaN),
        // never clamped — a fabricated constant-TWT tail misrepresented
        // the well.
        std::optional<std::string> warning;
        if (!all_finite(twt)) {
            const auto [lo, hi] = td->md_range();
            warning = truncated_warning(well.name, lo, hi);
        }
        WellTrajectory3D traj;
        traj.name = well.name;
        for (std::size_t i = 0; i < twt.size(); ++i) {
            if (!std::isfinite(twt[i])) continue;
            traj.points.push_back({path.xs[i], path.ys[i], twt[i]});
        }
        if (traj.points.empty()) {
            return head_only(well, warning);
        }
        traj.has_td = true;
        traj.warning = std::move(warning);
        return traj;
    }
    if (td == nullptr || depth_transform == nullptr ||
        !depth_transform->available()) {
        return head_only(
            well, "Well " + well.name +
                      ": missing time-depth table or transform; showing "
                      "wellhead only in Depth domain");
    }
    auto path = linspace_path(well, n_samples);
    const std::vector<double> twt = td->md_to_time_ms(path.md);
    const std::vector<double> z =
        depth_transform->time_ms_to_depth_m(twt);
    std::optional<std::string> warning;
    if (!all_finite(z)) {
        const auto [lo, hi] = td->md_range();
        warning = truncated_warning(well.name, lo, hi);
    }
    WellTrajectory3D traj;
    traj.name = well.name;
    for (std::size_t i = 0; i < z.size(); ++i) {
        if (!std::isfinite(z[i])) continue;
        traj.points.push_back({path.xs[i], path.ys[i], z[i]});
    }
    if (traj.points.empty()) {
        return head_only(well, warning);
    }
    traj.has_td = true;
    traj.warning = std::move(warning);
    return traj;
}

namespace {

// Shared horizontal-normal computation for the two curve overlays.
std::vector<std::array<float, 3>> horizontal_normals(
    const std::vector<std::array<float, 3>>& well_path) {
    const std::size_t n = well_path.size();
    std::vector<std::array<float, 3>> tangents(n);
    for (std::size_t i = 0; i + 1 < n; ++i) {
        for (int k = 0; k < 3; ++k) {
            tangents[i][k] = well_path[i + 1][k] - well_path[i][k];
        }
    }
    if (n == 1) {
        tangents[0] = {0.0f, 0.0f, 1.0f};
    } else {
        tangents[n - 1] = tangents[n - 2];
    }
    // Normalize first so the vertical-well threshold is independent of
    // station spacing.
    for (auto& t : tangents) {
        const float norm = std::sqrt(t[0] * t[0] + t[1] * t[1] + t[2] * t[2]);
        const float div = norm < 1e-5f ? 1.0f : norm;
        for (float& k : t) k /= div;
    }
    // Horizontal normal: rotate the tangent's XY part by 90°, drop Z.
    std::vector<std::array<float, 3>> perp(n);
    for (std::size_t i = 0; i < n; ++i) {
        perp[i] = {-tangents[i][1], tangents[i][0], 0.0f};
        const float norm = std::sqrt(perp[i][0] * perp[i][0] +
                                     perp[i][1] * perp[i][1]);
        if (norm < 1e-5f) {
            perp[i] = {1.0f, 0.0f, 0.0f};
        } else {
            for (float& k : perp[i]) k /= norm;
        }
    }
    return perp;
}

}  // namespace

std::vector<std::array<float, 3>> offset_curve_along_trajectory(
    const std::vector<std::array<float, 3>>& well_path,
    const std::vector<float>& curve_values, float scale) {
    const std::size_t n = well_path.size();
    if (n == 0) return {};
    if (curve_values.size() < n) {
        throw std::invalid_argument(
            "curve_values has " + std::to_string(curve_values.size()) +
            " samples but well_path has " + std::to_string(n) + " points");
    }
    const auto perp = horizontal_normals(well_path);
    std::vector<std::array<float, 3>> out(n);
    for (std::size_t i = 0; i < n; ++i) {
        const float amount = curve_values[i] * scale;
        out[i] = {well_path[i][0] + perp[i][0] * amount,
                  well_path[i][1] + perp[i][1] * amount,
                  well_path[i][2] + perp[i][2] * amount};
    }
    return out;
}

std::vector<std::array<float, 3>> build_synthetic_seismogram_overlay(
    const std::vector<std::array<float, 3>>& well_path,
    const std::vector<float>& synthetic_trace, float scale) {
    const std::size_t n = well_path.size();
    if (n == 0) return {};
    if (synthetic_trace.empty()) {
        // No trace -> zero deflection -> overlay coincides with the path.
        return well_path;
    }
    std::vector<float> trace;
    trace.reserve(synthetic_trace.size());
    for (float v : synthetic_trace) {
        // Guard against NaN/inf blowing up the geometry.
        trace.push_back(std::isfinite(v) ? v : 0.0f);
    }
    // Resample the trace to the station count (linear interp; the trace
    // has one fewer sample than the logs upstream).
    if (trace.size() != n) {
        std::vector<float> resampled(n);
        for (std::size_t i = 0; i < n; ++i) {
            const double pos =
                static_cast<double>(i) * static_cast<double>(trace.size() - 1) /
                static_cast<double>(n - 1);
            const std::size_t lo = static_cast<std::size_t>(pos);
            const std::size_t hi = std::min(lo + 1, trace.size() - 1);
            const double t = pos - static_cast<double>(lo);
            resampled[i] =
                static_cast<float>(trace[lo] + t * (trace[hi] - trace[lo]));
        }
        trace = std::move(resampled);
    }
    const auto perp = horizontal_normals(well_path);
    std::vector<std::array<float, 3>> out(n);
    for (std::size_t i = 0; i < n; ++i) {
        const float amount = trace[i] * scale;
        out[i] = {well_path[i][0] + perp[i][0] * amount,
                  well_path[i][1] + perp[i][1] * amount,
                  well_path[i][2] + perp[i][2] * amount};
    }
    return out;
}

}  // namespace pwb::geo3d_viz::joint
