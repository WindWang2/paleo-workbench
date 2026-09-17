#include <pwb/geomodel/fault_displacement.hpp>

#include <cmath>

namespace pwb::geomodel {

namespace {
// math.radians precomputes PI/180 and multiplies once; a two-step
// deg*PI/180 rounds differently on a measurable fraction of inputs.
constexpr double kDegToRad = 3.14159265358979323846 / 180.0;

// NEP-50 weak-scalar folding: python doubles enter float32 array ops as
// float (cast first, then float32 arithmetic).
template <typename T>
T fold(double v) {
    return static_cast<T>(v);
}
}  // namespace

template <typename T>
std::vector<std::array<T, 3>> apply_fault_throw(
    const std::vector<std::array<T, 3>>& vertices, FaultSpec spec) {
    // res = vertices.copy() — element type preserved.
    std::vector<std::array<T, 3>> res = vertices;

    const double rad_strike = spec.strike_deg * kDegToRad;
    const double nx = std::cos(rad_strike);
    const double ny = std::sin(rad_strike);

    // Signed distance to the fault plane's normal line, anchored at BOTH
    // (fault_line_x, fault_line_y) (#1038).
    std::vector<T> dist_normal(res.size());
    for (std::size_t i = 0; i < res.size(); ++i) {
        const T dx = res[i][0] - fold<T>(spec.fault_line_x);
        const T dy = res[i][1] - fold<T>(spec.fault_line_y);
        dist_normal[i] = fold<T>(nx) * dx + fold<T>(ny) * dy;
    }
    std::vector<bool> hanging_wall(res.size());
    for (std::size_t i = 0; i < res.size(); ++i) {
        hanging_wall[i] = dist_normal[i] >= T(0);
    }

    double effective_throw_x;
    if (spec.throw_x == 0.0 && spec.dip_deg > 0 && spec.dip_deg < 90) {
        const double rad_dip = spec.dip_deg * kDegToRad;
        // Heave carries the throw's SIGN (#846).
        effective_throw_x = spec.throw_z / std::tan(rad_dip);
    } else {
        effective_throw_x = spec.throw_x;
    }

    if (spec.decay_radius > 0.0) {
        for (std::size_t i = 0; i < res.size(); ++i) {
            const T dist = std::fabs(dist_normal[i]);
            const T q = dist / fold<T>(spec.decay_radius * 0.5);
            T w = std::exp(-(q * q));
            if (!hanging_wall[i]) {
                w = T(0);
            }
            res[i][0] += fold<T>(effective_throw_x * nx) * w;
            res[i][1] += fold<T>(effective_throw_x * ny) * w;
            res[i][2] += fold<T>(spec.throw_z) * w;
        }
    } else {
        for (std::size_t i = 0; i < res.size(); ++i) {
            if (!hanging_wall[i]) {
                continue;
            }
            res[i][0] += fold<T>(effective_throw_x * nx);
            res[i][1] += fold<T>(effective_throw_x * ny);
            res[i][2] += fold<T>(spec.throw_z);
        }
    }
    return res;
}

template std::vector<std::array<float, 3>> apply_fault_throw<float>(
    const std::vector<std::array<float, 3>>&, FaultSpec);
template std::vector<std::array<double, 3>> apply_fault_throw<double>(
    const std::vector<std::array<double, 3>>&, FaultSpec);

}  // namespace pwb::geomodel
