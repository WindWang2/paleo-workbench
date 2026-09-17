#pragma once

// Named 256-entry RGB lookup tables applied to pwb::viz::IndexedSlice bytes.
// The viewer never re-implements stretch/NaN rules: map_slice_to_indexed8
// owns the numeric semantics (non-finite -> index 0, truncation, degenerate
// planes); this header only colors the resulting index stream. Index 0 is the
// lowest stretched value and also the color of every non-finite sample.

#include <array>
#include <cstdint>
#include <string_view>
#include <vector>

namespace pwb::seismic_viewer {

using ColorLut = std::vector<std::array<std::uint8_t, 3>>; // RGB triplets

// Canonical colormap registry (frozen v3): "grayscale", "seismic"
// (blue-white-red, classic seismic polarity), "heat" (black-red-yellow-white).
[[nodiscard]] std::vector<std::string_view> color_map_names();

// Returns the 256-entry LUT for `name`; empty vector for an unknown name.
[[nodiscard]] ColorLut color_lut(std::string_view name);

} // namespace pwb::seismic_viewer
