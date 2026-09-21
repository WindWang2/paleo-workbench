#include "pwb/ui_widgets/core/hud_sampling.hpp"

#include <algorithm>
#include <cmath>
#include <limits>

namespace pwb::ui_widgets::core {

namespace {

constexpr double kNaN = std::numeric_limits<double>::quiet_NaN();

bool is_nan(double v) { return std::isnan(v); }

}  // namespace

std::optional<std::size_t> axis_locate(const std::vector<double>& axis,
                                       double value) {
    if (axis.size() < 2) return std::nullopt;
    const bool ascending = axis.back() > axis.front();
    // probe = axis if ascending else axis[::-1]
    auto probe_at = [&](std::size_t i) -> double {
        return ascending ? axis[i] : axis[axis.size() - 1 - i];
    };
    if (value < probe_at(0) || value > probe_at(axis.size() - 1)) {
        return std::nullopt;
    }
    // np.searchsorted(probe, value, side="right") - 1 == upper_bound - 1
    std::size_t lo = 0, hi = axis.size();
    while (lo < hi) {
        const std::size_t mid = lo + (hi - lo) / 2;
        if (probe_at(mid) <= value) {
            lo = mid + 1;
        } else {
            hi = mid;
        }
    }
    long index = static_cast<long>(lo) - 1;
    index = std::max<long>(0, std::min<long>(index,
                                             static_cast<long>(axis.size()) - 2));
    if (ascending) return static_cast<std::size_t>(index);
    return axis.size() - 2 - static_cast<std::size_t>(index);
}

std::optional<double> bilinear_sample(const GridView& grid, double x,
                                      double y) {
    const auto col = axis_locate(grid.grid_x, x);
    const auto row = axis_locate(grid.grid_y, y);
    if (!col || !row) return std::nullopt;
    if (grid.grid_z.size() < grid.grid_x.size() * grid.grid_y.size()) {
        return std::nullopt;  // IndexError parity
    }
    const double x0 = grid.grid_x[*col], x1 = grid.grid_x[*col + 1];
    const double y0 = grid.grid_y[*row], y1 = grid.grid_y[*row + 1];
    const double tx = (x1 == x0) ? 0.0 : (x - x0) / (x1 - x0);
    const double ty = (y1 == y0) ? 0.0 : (y - y0) / (y1 - y0);
    // Nearest cell of the containing cell NaN -> no data (no extrapolation).
    const double nearest = grid.z_at(*row + (ty > 0.5 ? 1 : 0),
                                     *col + (tx > 0.5 ? 1 : 0));
    if (is_nan(nearest)) return std::nullopt;
    const double z00 = grid.z_at(*row, *col);
    const double z10 = grid.z_at(*row, *col + 1);
    const double z01 = grid.z_at(*row + 1, *col);
    const double z11 = grid.z_at(*row + 1, *col + 1);
    const double top = is_nan(z10)   ? z00
                       : is_nan(z00) ? z10
                                     : z00 * (1.0 - tx) + z10 * tx;
    const double bottom = is_nan(z11)   ? z01
                          : is_nan(z01) ? z11
                                        : z01 * (1.0 - tx) + z11 * tx;
    if (is_nan(top) && is_nan(bottom)) return std::nullopt;
    const double value = is_nan(bottom)   ? top
                         : is_nan(top)    ? bottom
                                          : top * (1.0 - ty) + bottom * ty;
    if (is_nan(value)) return std::nullopt;
    return value;
}

std::optional<double> local_slope_degrees(const GridView& grid, double x,
                                          double y) {
    if (grid.grid_x.size() < 2 || grid.grid_y.size() < 2) return std::nullopt;
    const double dx = std::abs(grid.grid_x[1] - grid.grid_x[0]);
    const double dy = std::abs(grid.grid_y[1] - grid.grid_y[0]);
    if (dx <= 0.0 || dy <= 0.0) return std::nullopt;
    // Python parity: clamps use axis back()/front() verbatim — on a
    // descending axis east_x can drop below range and bilinear_sample()
    // then refuses (None), matching the frozen behavior exactly.
    const double east_x = std::min(x + dx, grid.grid_x.back());
    const double west_x = std::max(x - dx, grid.grid_x.front());
    const double north_y = std::min(y + dy, grid.grid_y.back());
    const double south_y = std::max(y - dy, grid.grid_y.front());
    const auto east = bilinear_sample(grid, east_x, y);
    const auto west = bilinear_sample(grid, west_x, y);
    const auto north = bilinear_sample(grid, x, north_y);
    const auto south = bilinear_sample(grid, x, south_y);
    if (!east || !west || !north || !south) return std::nullopt;
    const double dz_dx = (*east - *west) / std::max(east_x - west_x, 1e-12);
    const double dz_dy = (*north - *south) / std::max(north_y - south_y, 1e-12);
    // PWB-V14-DATA-LINEAGE: M_PI is POSIX-only (MSVC needs
    // _USE_MATH_DEFINES before <cmath>); a local constant keeps the file
    // include-order-clean and identical on both platforms.
    constexpr double kPi = 3.14159265358979323846;
    return std::atan(std::hypot(dz_dx, dz_dy)) * 180.0 / kPi;
}

std::optional<double> confidence_from_variance(
    const GridView& grid, double x, double y,
    std::optional<double> sigma_ref) {
    if (grid.variance_grid.size() < grid.grid_x.size() * grid.grid_y.size()) {
        return std::nullopt;
    }
    const auto col = axis_locate(grid.grid_x, x);
    const auto row = axis_locate(grid.grid_y, y);
    if (!col || !row) return std::nullopt;
    const double variance = grid.variance_at(*row, *col);
    if (is_nan(variance)) return std::nullopt;
    double ref = sigma_ref.value_or(0.0);
    if (!sigma_ref || ref <= 0.0) ref = grid_sigma_reference(grid);
    if (ref <= 0.0) return std::nullopt;
    const double sigma = std::sqrt(std::max(variance, 0.0));
    return 1.0 / (1.0 + sigma / ref);
}

double grid_sigma_reference(const GridView& grid) {
    // np.nanstd parity: mean/std over non-NaN cells; all-NaN -> 0.
    double sum = 0.0;
    std::size_t count = 0;
    for (const double v : grid.grid_z) {
        if (!is_nan(v)) {
            sum += v;
            ++count;
        }
    }
    if (count == 0) return 0.0;
    const double mean = sum / static_cast<double>(count);
    double accum = 0.0;
    for (const double v : grid.grid_z) {
        if (!is_nan(v)) {
            const double d = v - mean;
            accum += d * d;
        }
    }
    const double sigma = std::sqrt(accum / static_cast<double>(count));
    return sigma > 0.0 ? sigma : 0.0;
}

std::optional<std::pair<std::string, double>> nearest_well(
    const std::vector<WellLocation>& wells, double x, double y,
    double max_distance) {
    std::optional<std::pair<std::string, double>> best;
    for (const WellLocation& well : wells) {
        const auto& coords = well.project ? well.project
                             : well.surface ? well.surface
                                            : well.plain;
        if (!coords) continue;
        const double distance =
            std::hypot(coords->first - x, coords->second - y);
        if (distance > max_distance) continue;
        if (!best || distance < best->second) {
            best = std::make_pair(well.name, distance);
        }
    }
    return best;
}

}  // namespace pwb::ui_widgets::core
