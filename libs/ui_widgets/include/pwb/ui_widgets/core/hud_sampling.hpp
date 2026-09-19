#pragma once

// UI-02 — O(1) HUD sampling core, ported from the pure half of
// paleo_workbench/ui/components/constraint_factor_hud.py (Qt-free).
//
// Contracts carried over verbatim:
//  - axis locate works on ascending AND descending axes, never extrapolates;
//  - bilinear sampling refuses when the NEAREST cell of the containing cell
//    is NaN (no data), with a half-NaN-neighborhood weight fallback;
//  - slope uses clamped central differences (edge cells shrink the stencil,
//    never read out of range);
//  - confidence = 1 / (1 + sigma / sigma_z); missing variance grid -> null
//    (no fabricated confidence); sigma_ref is computed once per grid by the
//    caller (O(grid) nanstd must never enter the 60 ms refresh loop);
//  - nearest well is a linear scan within max_distance (wells <= thousands).
//
// Missing values are std::optional::nullopt — the widget renders "—".

#include <cstddef>
#include <optional>
#include <string>
#include <vector>

namespace pwb::ui_widgets::core {

// Read-only view of one factor grid (FactorGridResult shape). z is
// row-major [row=y index][col=x index] with NaN marking no-data cells.
struct GridView {
    std::vector<double> grid_x;
    std::vector<double> grid_y;
    std::vector<double> grid_z;         // grid_y.size() * grid_x.size()
    std::vector<double> variance_grid;  // empty = no variance (e.g. IDW)
    std::string unit;                   // "%" switches sand-ratio formatting

    [[nodiscard]] std::size_t rows() const { return grid_y.size(); }
    [[nodiscard]] std::size_t cols() const { return grid_x.size(); }
    [[nodiscard]] double z_at(std::size_t row, std::size_t col) const {
        return grid_z[row * grid_x.size() + col];
    }
    [[nodiscard]] double variance_at(std::size_t row, std::size_t col) const {
        return variance_grid[row * grid_x.size() + col];
    }
};

// Well location candidate with the Python fallback chain built in:
// project_x/project_y -> surface_x/surface_y -> x/y (first complete pair
// wins; no pair -> the well is skipped by nearest_well()).
struct WellLocation {
    std::string name;
    std::optional<std::pair<double, double>> project;
    std::optional<std::pair<double, double>> surface;
    std::optional<std::pair<double, double>> plain;
};

// One-dimensional axis -> left-hand index; nullopt when the axis is
// degenerate or the value is out of range. Supports both directions.
[[nodiscard]] std::optional<std::size_t> axis_locate(
    const std::vector<double>& axis, double value);

// Bilinear sample at (x, y); nullopt on out-of-range / NaN nearest cell.
[[nodiscard]] std::optional<double> bilinear_sample(
    const GridView& grid, double x, double y);

// Local slope in degrees at (x, y): clamped central differences -> atan of
// the gradient magnitude. Nullopt when any stencil direction lacks data.
[[nodiscard]] std::optional<double> local_slope_degrees(
    const GridView& grid, double x, double y);

// Kriging variance -> confidence 1/(1 + sigma/sigma_z). Nullopt when the
// grid carries no variance or sigma_ref cannot be established.
[[nodiscard]] std::optional<double> confidence_from_variance(
    const GridView& grid, double x, double y,
    std::optional<double> sigma_ref = std::nullopt);

// Grid value standard deviation (population, ddof=0 — np.nanstd parity).
// Cache per grid identity; never inside the refresh loop.
[[nodiscard]] double grid_sigma_reference(const GridView& grid);

// Linear nearest well within max_distance; nullopt beyond tolerance.
[[nodiscard]] std::optional<std::pair<std::string, double>> nearest_well(
    const std::vector<WellLocation>& wells, double x, double y,
    double max_distance);

}  // namespace pwb::ui_widgets::core
