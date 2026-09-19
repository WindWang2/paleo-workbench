// Survey / bin-grid construction for Local Rectangular well–seismic
// alignment — port of geoviz_well_seismic_3d/survey.py @ 08851951. The
// bin-grid struct itself is reused from libs/seismic_io (identical math,
// already oracle-frozen there); this header adds the survey line-number
// layer (IL/XL starts, steps, counts) on top of it.
#pragma once

#include <array>
#include <optional>
#include <stdexcept>
#include <string>

#include <pwb/seismic_io/volume_descriptor.hpp>

namespace pwb::geo3d_viz::joint {

// Corner tuple: (inline, crossline, x, y).
using Corner = std::array<double, 4>;

// Survey geometry mapping absolute IL/XL ↔ Local Rectangular XY.
struct SurveySpec {
    pwb::seismic_io::BinGridGeometry bin_grid;
    std::int64_t iline_start = 1;
    std::int64_t iline_step = 1;
    std::int64_t xline_start = 1;
    std::int64_t xline_step = 1;
    std::int64_t n_inlines = 1;
    std::int64_t n_crosslines = 1;
    std::int64_t n_samples = 1;
    double dt_ms = 1.0;
    double t0_ms = 0.0;

    // Absolute IL/XL numbers for a world XY (fractional).
    std::pair<double, double> xy_to_il_xl(double x, double y) const;
    // World XY for absolute IL/XL numbers (fractional).
    std::pair<double, double> il_xl_to_xy(double iline, double xline) const;
};

// Build a survey from three grid corners (horizon/SEGY text-header style).
//
//   p1: origin corner (il0, xl0, x0, y0)
//   p2: same inline as p1, opposite crossline (il0, xl1, x1, y1)
//   p3: same crossline as p2, opposite inline (il1, xl1, x2, y2)
//
// Line numbering defaults to step ±1 between the corner numbers. Real
// SEG-Y often numbers lines with a larger step (e.g. IL 1000, 1002, …):
// pass the loader's actual steps and counts so the grid has the right
// number of bins — deriving them from the corner numbers alone would
// double-count the axis and misregister every IL/XL↔XY conversion.
SurveySpec survey_from_corners(
    const Corner& p1, const Corner& p2, const Corner& p3,
    std::int64_t n_samples, double dt_ms, double t0_ms = 0.0,
    std::optional<std::int64_t> iline_step = std::nullopt,
    std::optional<std::int64_t> xline_step = std::nullopt,
    std::optional<std::int64_t> n_inlines = std::nullopt,
    std::optional<std::int64_t> n_crosslines = std::nullopt);

}  // namespace pwb::geo3d_viz::joint
