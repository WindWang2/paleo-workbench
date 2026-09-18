#pragma once

// pwb::science_service — resource guard vocabulary (CONV-28).
//
// The service layer is resource-aware by failing closed BEFORE a kernel
// allocates: every request is checked against these bounds and a violation
// maps to a stable "resource.*" diagnostic, never to an OOM or a swap death.
// Defaults target the repo's medium-scale contract (no 100 GB volume runs):
// they bound input records, grid resolution, curve lengths, DTW cost cells
// and the envelope payload size independently so one dimension cannot be
// inflated through another.

#include <cstddef>
#include <string>

namespace pwb::science_service {

struct ResourceLimits {
    // Maximum well-table records accepted by extract-based services.
    std::size_t max_input_records = 2'000'000;
    // Maximum grid cells (grid_n * grid_n) an interpolation may produce.
    std::size_t max_grid_cells = 4'000'000;
    // Upper bound for interpolate grid_n itself (grid resolution sanity).
    int max_grid_n = 2000;
    // Maximum samples on one curve operand (values/depth axis).
    std::size_t max_curve_samples = 20'000'000;
    // Maximum DTW cost cells before the service decimates (kernel constant
    // pwb::well_science::kMaxCostCells = 1'000'000 is the hard kernel bound;
    // the service mirrors it as its own bound).
    std::int64_t max_dtw_cost_cells = 1'000'000;
    // Maximum grid cells embedded as JSON lists into an envelope payload;
    // larger grids ship descriptor-only with a warning diagnostic.
    std::size_t max_envelope_grid_cells = 1'000'000;
    // Maximum samples returned in a curve/log-match envelope payload.
    std::size_t max_envelope_samples = 2'000'000;
    // Maximum geomodel vertices in one build/section request.
    std::size_t max_geomodel_vertices = 5'000'000;

    // Shared singleton used by services when the host injects nothing.
    static const ResourceLimits& defaults();
};

// Stable diagnostic code for a bound violation ("resource.<name>").
[[nodiscard]] std::string limit_code(const std::string& limit_name);

}  // namespace pwb::science_service
