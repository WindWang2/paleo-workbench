// Map survey IL/XL/sample ↔ loaded volume indices (preview-safe) — port
// of geoviz_well_seismic_3d/registration.py @ 08851951 (Wayfinder
// #81/#84: registration carries the per-axis downsample stride and maps
// through it — never through an endpoint-normalised shape ratio).
#pragma once

#include <array>
#include <optional>
#include <stdexcept>
#include <utility>

#include "survey.hpp"

namespace pwb::geo3d_viz::joint {

// Stride implied by a loaded axis length (ceil(n/f) == loaded).
std::array<std::int64_t, 3> infer_strides(std::int64_t n_inline_native,
                                          std::int64_t n_crossline_native,
                                          std::int64_t n_sample_native,
                                          std::int64_t n_inline_loaded,
                                          std::int64_t n_crossline_loaded,
                                          std::int64_t n_sample_loaded);

// Linear map from survey absolute IL/XL/time to volume array indices.
// n_* match the loaded array shape (preview or native) while survey still
// describes the full native geometry: native_index = preview_index *
// stride, exact at every sampled position and invertible on the stride
// lattice.
class VolumeRegistration {
public:
    VolumeRegistration(SurveySpec survey, std::int64_t n_inline,
                       std::int64_t n_crossline, std::int64_t n_sample,
                       std::array<std::int64_t, 3> strides = {1, 1, 1});

    static VolumeRegistration from_survey_and_shape(
        const SurveySpec& survey,
        const std::array<std::int64_t, 3>& shape,
        const std::optional<std::array<std::int64_t, 3>>& strides =
            std::nullopt);

    const SurveySpec& survey() const { return survey_; }
    std::int64_t n_inline() const { return n_inline_; }
    std::int64_t n_crossline() const { return n_crossline_; }
    std::int64_t n_sample() const { return n_sample_; }
    const std::array<std::int64_t, 3>& strides() const { return strides_; }

    // Survey coordinates → fractional loaded volume indices, exact on the
    // stride lattice.
    std::pair<double, double> il_xl_to_volume_idx(double iline,
                                                  double xline) const;
    std::pair<double, double> xy_to_volume_idx(double x, double y) const;
    // #147 fail-closed: a missing/non-positive dt must never turn TWT ms
    // into sample indices.
    double time_ms_to_sample_idx(double time_ms) const;
    double sample_idx_to_time_ms(double sample_index) const;

    // Stride lattice helpers.
    std::int64_t sample_idx_to_native(std::int64_t sample_index) const;
    double native_to_sample_idx(double native_index) const;
    // Inverse of il_xl_to_volume_idx (loaded indices → survey numbers).
    std::pair<double, double> volume_idx_to_il_xl(double il_idx,
                                                  double xl_idx) const;
    std::array<std::int64_t, 3> clamp_indices(double il_idx, double xl_idx,
                                              double t_idx) const;
    std::array<std::int64_t, 3> world_xyz_to_volume(double x, double y,
                                                    double z) const;

private:
    SurveySpec survey_;
    std::int64_t n_inline_;
    std::int64_t n_crossline_;
    std::int64_t n_sample_;
    std::array<std::int64_t, 3> strides_;
};

}  // namespace pwb::geo3d_viz::joint
