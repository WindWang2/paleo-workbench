#pragma once

// pwb::geomodel — fault throw displacement kernel, a faithful C++ port of
// paleo_workbench/viz/fault_displacement.py (CONV-12). Frozen against
// tools/oracle/generate_geomodel_volume_fixtures.py:
//   * signed normal distance anchored at BOTH (fault_line_x, fault_line_y)
//     — the unanchored Y term displaced UTM surveys by hundreds of km
//     (#1038);
//   * hanging wall is dist_normal >= 0 (the fault plane itself belongs to
//     the hanging wall);
//   * heave carries the throw's SIGN (#846): effective_throw_x =
//     throw_z / tan(dip) only when throw_x == 0 and 0 < dip < 90;
//   * decay_radius > 0 applies a Gaussian weight exp(-(d/(r/2))^2) on the
//     hanging-wall side only; otherwise the hanging wall translates rigidly;
//   * array element type drives precision: float32 input stays float32 with
//     NEP-50 weak-scalar folding (python doubles cast to float per op).
// Qt-free, Python-free, numpy-free.

#include <array>
#include <vector>

namespace pwb::geomodel {

struct FaultSpec {
    double fault_line_x = 0.0;
    double throw_z = 0.0;
    double fault_line_y = 0.0;
    double throw_x = 0.0;
    double dip_deg = 60.0;
    double strike_deg = 0.0;
    double decay_radius = 0.0;
};

// Displace hanging-wall vertices; T is float or double (the element type of
// the input is preserved exactly like ndarray.copy()).
template <typename T>
std::vector<std::array<T, 3>> apply_fault_throw(
    const std::vector<std::array<T, 3>>& vertices, FaultSpec spec);

}  // namespace pwb::geomodel
