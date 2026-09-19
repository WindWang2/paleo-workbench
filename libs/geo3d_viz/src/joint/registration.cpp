// registration.cpp — survey IL/XL/sample ↔ loaded volume indices
// (registration.py @ 08851951, Wayfinder #81/#84).
#include "pwb/geo3d_viz/joint/registration.hpp"

#include <cmath>

namespace pwb::geo3d_viz::joint {

namespace {
// ceil(n/f) == loaded; grow until the implied preview length fits.
std::int64_t infer_stride(std::int64_t native, std::int64_t loaded) {
    native = native < 1 ? 1 : native;
    loaded = loaded < 1 ? 1 : loaded;
    if (loaded >= native) return 1;
    std::int64_t stride =
        static_cast<std::int64_t>(std::ceil(static_cast<double>(native) /
                                            static_cast<double>(loaded)));
    while (static_cast<double>(native) / static_cast<double>(stride) >
               static_cast<double>(loaded) ||
           std::ceil(static_cast<double>(native) /
                     static_cast<double>(stride)) > loaded) {
        ++stride;
    }
    return stride;
}
}  // namespace

std::array<std::int64_t, 3> infer_strides(
    std::int64_t n_inline_native, std::int64_t n_crossline_native,
    std::int64_t n_sample_native, std::int64_t n_inline_loaded,
    std::int64_t n_crossline_loaded, std::int64_t n_sample_loaded) {
    return {infer_stride(n_inline_native, n_inline_loaded),
            infer_stride(n_crossline_native, n_crossline_loaded),
            infer_stride(n_sample_native, n_sample_loaded)};
}

VolumeRegistration::VolumeRegistration(SurveySpec survey,
                                       std::int64_t n_inline,
                                       std::int64_t n_crossline,
                                       std::int64_t n_sample,
                                       std::array<std::int64_t, 3> strides)
    : survey_(std::move(survey)),
      n_inline_(n_inline),
      n_crossline_(n_crossline),
      n_sample_(n_sample),
      strides_(strides) {
    for (std::int64_t s : strides_) {
        if (s < 1) {
            throw std::invalid_argument(
                "strides must be three positive ints");
        }
    }
    const std::int64_t native[3] = {survey_.n_inlines, survey_.n_crosslines,
                                    survey_.n_samples};
    const std::int64_t loaded[3] = {n_inline_, n_crossline_, n_sample_};
    for (int axis = 0; axis < 3; ++axis) {
        if (loaded[axis] < 1 || loaded[axis] > native[axis]) {
            throw std::invalid_argument(
                "axis " + std::to_string(axis) + ": loaded size " +
                std::to_string(loaded[axis]) + " outside native 1.." +
                std::to_string(native[axis]));
        }
        const double implied =
            std::ceil(static_cast<double>(native[axis]) /
                      static_cast<double>(strides_[axis]));
        if (static_cast<std::int64_t>(implied) != loaded[axis]) {
            throw std::invalid_argument(
                "axis " + std::to_string(axis) + ": stride " +
                std::to_string(strides_[axis]) + " implies " +
                std::to_string(static_cast<std::int64_t>(implied)) +
                " samples, loaded " + std::to_string(loaded[axis]));
        }
    }
}

VolumeRegistration VolumeRegistration::from_survey_and_shape(
    const SurveySpec& survey, const std::array<std::int64_t, 3>& shape,
    const std::optional<std::array<std::int64_t, 3>>& strides) {
    std::array<std::int64_t, 3> resolved = {1, 1, 1};
    if (strides.has_value()) {
        resolved = *strides;
    } else {
        // Legacy caller: infer the stride the preview length implies.
        resolved = infer_strides(survey.n_inlines, survey.n_crosslines,
                                 survey.n_samples, shape[0], shape[1],
                                 shape[2]);
    }
    return VolumeRegistration(survey, shape[0], shape[1], shape[2], resolved);
}

std::pair<double, double> VolumeRegistration::il_xl_to_volume_idx(
    double iline, double xline) const {
    const SurveySpec& s = survey_;
    const double il_step =
        s.iline_step != 0 ? static_cast<double>(s.iline_step) : 1.0;
    const double xl_step =
        s.xline_step != 0 ? static_cast<double>(s.xline_step) : 1.0;
    const double native_il =
        (iline - static_cast<double>(s.iline_start)) / il_step;
    const double native_xl =
        (xline - static_cast<double>(s.xline_start)) / xl_step;
    return {static_cast<double>(native_il) /
                static_cast<double>(strides_[0]),
            static_cast<double>(native_xl) /
                static_cast<double>(strides_[1])};
}

std::pair<double, double> VolumeRegistration::xy_to_volume_idx(
    double x, double y) const {
    const auto [il, xl] = survey_.xy_to_il_xl(x, y);
    return il_xl_to_volume_idx(il, xl);
}

double VolumeRegistration::time_ms_to_sample_idx(double time_ms) const {
    const SurveySpec& s = survey_;
    // #147: treating TWT milliseconds as sample indices silently maps
    // 2500 ms to sample 2500. Fail closed — the sample domain is unusable
    // without a parsed sample interval.
    if (!(s.dt_ms > 0.0)) {
        throw std::invalid_argument(
            "survey dt_ms is missing or non-positive; cannot convert TWT ms "
            "to sample indices (fail-closed, #147)");
    }
    const double native_t = (time_ms - s.t0_ms) / s.dt_ms;
    return native_t / static_cast<double>(strides_[2]);
}

double VolumeRegistration::sample_idx_to_time_ms(
    double sample_index) const {
    const double native_index = sample_index * static_cast<double>(strides_[2]);
    return survey_.t0_ms + native_index * survey_.dt_ms;
}

std::int64_t VolumeRegistration::sample_idx_to_native(
    std::int64_t sample_index) const {
    return sample_index * strides_[2];
}

double VolumeRegistration::native_to_sample_idx(double native_index) const {
    return native_index / static_cast<double>(strides_[2]);
}

std::pair<double, double> VolumeRegistration::volume_idx_to_il_xl(
    double il_idx, double xl_idx) const {
    const SurveySpec& s = survey_;
    const double native_il = il_idx * static_cast<double>(strides_[0]);
    const double native_xl = xl_idx * static_cast<double>(strides_[1]);
    const double il_step =
        s.iline_step != 0 ? static_cast<double>(s.iline_step) : 1.0;
    const double xl_step =
        s.xline_step != 0 ? static_cast<double>(s.xline_step) : 1.0;
    return {static_cast<double>(s.iline_start) + native_il * il_step,
            static_cast<double>(s.xline_start) + native_xl * xl_step};
}

std::array<std::int64_t, 3> VolumeRegistration::clamp_indices(
    double il_idx, double xl_idx, double t_idx) const {
    auto clamp = [](double v, std::int64_t hi) {
        // Python round() is half-to-even; nearbyint under the default
        // FE_TONEAREST mode matches it exactly (llround would not).
        const double rounded = std::nearbyint(v);
        double bounded = rounded < 0 ? 0 : rounded;
        bounded = bounded > static_cast<double>(hi - 1)
                      ? static_cast<double>(hi - 1)
                      : bounded;
        return static_cast<std::int64_t>(bounded);
    };
    return {clamp(il_idx, n_inline_), clamp(xl_idx, n_crossline_),
            clamp(t_idx, n_sample_)};
}

std::array<std::int64_t, 3> VolumeRegistration::world_xyz_to_volume(
    double x, double y, double z) const {
    const auto [vi, vx] = xy_to_volume_idx(x, y);
    const double vt = time_ms_to_sample_idx(z);
    return clamp_indices(vi, vx, vt);
}

}  // namespace pwb::geo3d_viz::joint
