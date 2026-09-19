// probe.cpp — shared probe state for 2D↔3D↔slice linkage (probe.py #64).
#include "pwb/geo3d_viz/joint/probe.hpp"

#include <algorithm>
#include <cmath>
#include <numeric>
#include <stdexcept>

namespace pwb::geo3d_viz::joint {

std::array<std::int64_t, 3> ProbeState::slice_indices(
    const SurveySpec* survey) const {
    if (survey == nullptr) {
        return {0, 0, static_cast<std::int64_t>(std::nearbyint(z))};
    }
    const double il_step = survey->iline_step != 0
                               ? static_cast<double>(survey->iline_step)
                               : 1.0;
    const double xl_step = survey->xline_step != 0
                               ? static_cast<double>(survey->xline_step)
                               : 1.0;
    // Python round() = half-to-even (nearbyint).
    const std::int64_t il_idx = static_cast<std::int64_t>(std::nearbyint(
        (il - static_cast<double>(survey->iline_start)) / il_step));
    const std::int64_t xl_idx = static_cast<std::int64_t>(std::nearbyint(
        (xl - static_cast<double>(survey->xline_start)) / xl_step));
    std::int64_t t_idx = 0;
    if (survey->dt_ms > 0 && domain == "time") {
        t_idx = static_cast<std::int64_t>(
            std::nearbyint((z - survey->t0_ms) / survey->dt_ms));
    } else {
        t_idx = static_cast<std::int64_t>(std::nearbyint(z));
    }
    return {std::max<std::int64_t>(0,
                                   std::min(survey->n_inlines - 1, il_idx)),
            std::max<std::int64_t>(
                0, std::min(survey->n_crosslines - 1, xl_idx)),
            std::max<std::int64_t>(0, std::min(survey->n_samples - 1, t_idx))};
}

ProbeState probe_from_fence_s(
    double s_m, double z, const std::vector<std::array<double, 2>>& vertices_xy,
    const SurveySpec* survey, const std::string& domain) {
    ProbeState state;
    state.domain = domain;
    state.z = z;
    if (vertices_xy.size() < 2) {
        throw std::invalid_argument(
            "probe needs a fence polyline with at least 2 vertices");
    }
    std::vector<double> seg_len;
    std::vector<double> cum{0.0};
    for (std::size_t i = 0; i + 1 < vertices_xy.size(); ++i) {
        const double len =
            std::hypot(vertices_xy[i + 1][0] - vertices_xy[i][0],
                       vertices_xy[i + 1][1] - vertices_xy[i][1]);
        seg_len.push_back(len);
        cum.push_back(cum.back() + len);
    }
    const double total =
        seg_len.empty() ? 1.0
                        : std::accumulate(seg_len.begin(), seg_len.end(), 0.0);
    const double s = std::max(0.0, std::min(total, s_m));
    state.s_m = s;
    std::size_t j = static_cast<std::size_t>(
        std::upper_bound(cum.begin(), cum.end(), s) - cum.begin());
    j = j == 0 ? 0 : j - 1;
    j = std::min(j, seg_len.size() - 1);
    const double len = seg_len[j] > 1e-12 ? seg_len[j] : 1.0;
    const double local = (s - cum[j]) / len;
    const double x =
        vertices_xy[j][0] +
        local * (vertices_xy[j + 1][0] - vertices_xy[j][0]);
    const double y =
        vertices_xy[j][1] +
        local * (vertices_xy[j + 1][1] - vertices_xy[j][1]);
    state.x = x;
    state.y = y;
    if (survey != nullptr) {
        const auto [il, xl] = survey->xy_to_il_xl(x, y);
        state.il = il;
        state.xl = xl;
    }
    return state;
}

}  // namespace pwb::geo3d_viz::joint
