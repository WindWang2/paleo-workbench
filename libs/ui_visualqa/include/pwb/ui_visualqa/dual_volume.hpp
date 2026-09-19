#pragma once

// UI-16 — Qt-free core of proto_dual_volume_overlay.py (non-production
// prototype, honest port): the synthetic 3D volume generator, axis slice
// extraction and the three blending variants (alpha / RGB spectral fusion /
// coherence threshold mask) as pure math over std::vector<float>.
//
// The Qt widget + host window live in qt/dual_volume_overlay.hpp — this
// core is unit-testable headless and carries no engine seams (the
// prototype's data is generated in-memory, exactly like the Python).

#include <cstdint>
#include <string>
#include <vector>

namespace pwb::ui_visualqa {

// A dense float volume, dims (nx, ny, nz), index = (x*ny + y)*nz + z —
// the numpy `meshgrid(indexing='ij')` memory order parity.
struct ScalarVolume {
    int nx = 0;
    int ny = 0;
    int nz = 0;
    std::vector<float> data;

    float at(int x, int y, int z) const {
        return data[(static_cast<std::size_t>(x) * ny + y) * nz + z];
    }
};

// generate_synthetic_seismic_volumes(nx, ny, nz) parity: primary =
// sin(z + 0.3x + 0.2y) * exp(-0.05(x²+y²)) over x,y ∈ [-3,3], z ∈ [0,4π];
// secondary = 1 - 0.8 * exp(-15*((x - 0.5y) - 0.2z/4π)²).
struct SyntheticVolumes {
    ScalarVolume amplitude;
    ScalarVolume coherence;
};
SyntheticVolumes generate_synthetic_seismic_volumes(int nx = 200,
                                                    int ny = 200,
                                                    int nz = 200);

// Axis vocabulary (axis_names parity).
inline constexpr int kAxisInline = 0;
inline constexpr int kAxisCrossline = 1;
inline constexpr int kAxisTime = 2;
const char* axis_display_name(int axis);  // "Inline (0)"|…|"" for unknown

// The three blending variants — selected by prefix like the Python
// ("Variant A"/"Variant B"/else C) or by stable id.
enum class OverlayVariant { AlphaBlending, RgbFusion, ThresholdMask };
const char* variant_display_name(OverlayVariant v);
// Python's `"Variant A" in variant` substring dispatch parity.
OverlayVariant variant_from_label(const std::string& label);

// A clamped 2D slice (row-major h×w) pulled from the volume along `axis`
// at index `slice_idx` — numpy clamp+index parity.
struct Slice2D {
    int h = 0;
    int w = 0;
    std::vector<float> data;   // h*w row-major
    float at(int r, int c) const { return data[r * w + c]; }
};
Slice2D extract_slice(const ScalarVolume& vol, int axis, int slice_idx);

// render_rgba parity: amplitude slice -> greyscale base, coherence ->
// variant overlay, 255 alpha. `opacity` and `threshold` are the slider
// fractions (0..1); variant C masks coherence < threshold.
struct RgbaImage {
    int h = 0;
    int w = 0;
    std::vector<std::uint8_t> rgba;  // h*w*4
};
RgbaImage render_overlay_rgba(const Slice2D& amplitude,
                              const Slice2D& coherence,
                              OverlayVariant variant,
                              double opacity, double threshold);

}  // namespace pwb::ui_visualqa
