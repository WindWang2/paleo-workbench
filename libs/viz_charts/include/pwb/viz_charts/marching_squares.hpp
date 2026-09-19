// Vector contour line and filled band extraction — marching-squares port of
// geoviz_plots/surface/marching_squares.py (contourpy serial backend
// replaced; geometric parity is frozen with tolerances in the viz_e oracle —
// vertex-by-vertex equality with contourpy is not a contract).
#pragma once

#include <cstddef>
#include <cstdint>
#include <functional>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace pwb::viz_charts {

struct Polyline {
    std::vector<double> xs;
    std::vector<double> ys;
};

struct PackedRings {
    // points[i] holds ring coordinates for polygon i; offsets[i] delimits
    // ring boundaries inside points[i] (contourpy OuterOffset shape:
    // exterior ring first, hole rings follow).
    std::vector<Polyline> points;          // per polygon: concatenated rings
    std::vector<std::vector<std::size_t>> offsets;
};

// One filled-contour band between adjacent levels.
struct BandedFill {
    double level_min = 0.0;
    double level_max = 0.0;
    PackedRings rings;
    int color_r = 0;
    int color_g = 0;
    int color_b = 0;
    std::string label;
};

// Cooperative cancellation: checked before work, per level, and per band.
using CancelCheck = std::function<bool()>;  // true → cancelled

// Contour lines per level for grid_z of shape (len(grid_y), len(grid_x));
// non-finite z cells are treated as masked (no crossing is emitted through
// them). Returns nullopt when the cancellation check fires.
std::optional<std::vector<std::pair<double, std::vector<Polyline>>>>
extract_contour_lines(const std::vector<double>& grid_x,
                      const std::vector<double>& grid_y,
                      const std::vector<double>& grid_z,
                      const std::vector<double>& levels,
                      const CancelCheck& cancelled = nullptr);

// Filled bands for adjacent sorted-level pairs; band color is sampled at the
// pair midpoint over the [min(levels), max(levels)] range with `palette`.
// Python's shapely study-area clip degrades to "no clip" when shapely is
// absent; this port implements that documented fallback only (see ledger).
std::optional<std::vector<BandedFill>> extract_filled_contours(
    const std::vector<double>& grid_x, const std::vector<double>& grid_y,
    const std::vector<double>& grid_z, const std::vector<double>& levels,
    std::string_view palette = "viridis", const CancelCheck& cancelled = nullptr);

}  // namespace pwb::viz_charts
