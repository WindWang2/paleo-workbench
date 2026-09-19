// Color-scale primitives shared by joint 2D and 3D renderers — port of
// geoviz_well_seismic_3d/color_scales.py @ 08851951 (frozen stop tables;
// the rounding follows numpy's rint = round-half-to-even, which is C++
// std::nearbyint under the default FE_TONEAREST mode).
#pragma once

#include <array>
#include <cstdint>
#include <string>
#include <vector>

namespace pwb::geo3d_viz::joint {

using RgbStop = std::array<std::uint8_t, 3>;

// SEISMIC_COLOR_SCALES lookup; unknown names resolve to blue-white-red.
const std::vector<RgbStop>& seismic_color_scale(
    const std::string& name);
// GR_COLOR_SCALES lookup; unknown names resolve to viridis.
const std::vector<RgbStop>& gr_color_scale(const std::string& name);

inline constexpr std::uint8_t kMissingGrAlpha = 255;
inline constexpr std::array<std::uint8_t, 4> kMissingGrRgba = {
    115, 115, 115, kMissingGrAlpha};

// Map amplitude to zero-centred RGBA using a robust symmetric range
// (P98 of |finite| values). Non-finite samples render as (128,128,128).
// Output: values.size() * 4 RGBA bytes.
std::vector<std::uint8_t> colorize_amplitude(
    const std::vector<float>& amplitude,
    const std::string& color_scale = "blue-white-red");

// Map GR values to sequential RGBA; missing samples stay neutral gray.
// value_range is the (lo, hi) normalization window.
std::vector<std::uint8_t> colorize_gr(
    const std::vector<double>& values, std::pair<double, double> value_range,
    const std::string& color_scale = "viridis");

}  // namespace pwb::geo3d_viz::joint
