// segy_survey.cpp — SurveySpec from a real seismic volume descriptor
// (segy_survey.py mapping; see segy_survey.hpp for the port decision).
#include "pwb/geo3d_viz/joint/segy_survey.hpp"

#include <cmath>
#include <stdexcept>

namespace pwb::geo3d_viz::joint {

SurveySpec survey_from_volume_descriptor(
    const pwb::seismic_io::VolumeDescriptor& descriptor) {
    if (!descriptor.bin_grid.has_value()) {
        throw std::invalid_argument(
            "volume carries no bin-grid calibration (geometry source '" +
            descriptor.geometry_source + "') — refusing to fabricate "
            "survey geometry (fail-closed)");
    }
    if (descriptor.sample_domain !=
            pwb::seismic_io::SampleDomain::time ||
        !(descriptor.sample_unit == "ms" ||
          descriptor.sample_unit.empty())) {
        // The joint scene's vertical axis is TWT milliseconds; unknown
        // units are never treated as ms.
        throw std::invalid_argument(
            "volume sample axis is not TWT milliseconds (unit '" +
            descriptor.sample_unit + "') — joint Time survey refused "
            "(fail-closed)");
    }
    if (descriptor.ni < 1 || descriptor.nc < 1 || descriptor.ns < 1) {
        throw std::invalid_argument("volume shape is empty");
    }
    if (!(descriptor.sample_step > 0.0)) {
        throw std::invalid_argument(
            "volume sample interval is missing or non-positive; cannot "
            "build a TWT survey (fail-closed, #147)");
    }

    SurveySpec spec;
    spec.bin_grid = *descriptor.bin_grid;
    spec.iline_start = static_cast<std::int64_t>(
        std::llround(descriptor.iline_start));
    spec.iline_step = static_cast<std::int64_t>(
        std::llround(descriptor.iline_step != 0.0
                         ? descriptor.iline_step
                         : 1.0));
    if (spec.iline_step == 0) spec.iline_step = 1;
    spec.xline_start = static_cast<std::int64_t>(
        std::llround(descriptor.xline_start));
    spec.xline_step = static_cast<std::int64_t>(
        std::llround(descriptor.xline_step != 0.0
                         ? descriptor.xline_step
                         : 1.0));
    if (spec.xline_step == 0) spec.xline_step = 1;
    spec.n_inlines = descriptor.ni;
    spec.n_crosslines = descriptor.nc;
    spec.n_samples = descriptor.ns;
    spec.dt_ms = descriptor.sample_step;
    spec.t0_ms = descriptor.sample_start;
    return spec;
}

std::tuple<Corner, Corner, Corner> survey_corners(
    const SurveySpec& survey) {
    const double il0 = static_cast<double>(survey.iline_start);
    const double xl0 = static_cast<double>(survey.xline_start);
    const double il1 =
        il0 + static_cast<double>(survey.n_inlines - 1) *
                  static_cast<double>(survey.iline_step);
    const double xl1 =
        xl0 + static_cast<double>(survey.n_crosslines - 1) *
                  static_cast<double>(survey.xline_step);
    const auto [x0, y0] = survey.il_xl_to_xy(il0, xl0);
    const auto [x1, y1] = survey.il_xl_to_xy(il0, xl1);
    const auto [x2, y2] = survey.il_xl_to_xy(il1, xl1);
    return {{{il0, xl0, x0, y0}},
            {{il0, xl1, x1, y1}},
            {{il1, xl1, x2, y2}}};
}

}  // namespace pwb::geo3d_viz::joint
