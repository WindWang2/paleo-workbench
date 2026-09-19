#include <pwb/ui_visualqa/dual_volume.hpp>

#include <algorithm>
#include <cmath>

namespace pwb::ui_visualqa {

namespace {

constexpr double kPi = 3.14159265358979323846;

// numpy linspace parity (endpoint-inclusive).
double linspace(double lo, double hi, int n, int i) {
    if (n <= 1) return lo;
    return lo + (hi - lo) * (static_cast<double>(i) / (n - 1));
}

std::uint8_t to_u8(double v) {
    // numpy clip(...).astype(uint8) parity: clamp then truncate.
    return static_cast<std::uint8_t>(std::clamp(v, 0.0, 255.0));
}

}  // namespace

SyntheticVolumes generate_synthetic_seismic_volumes(int nx, int ny,
                                                    int nz) {
    SyntheticVolumes out;
    out.amplitude = ScalarVolume{nx, ny, nz,
                               std::vector<float>(
                                   static_cast<std::size_t>(nx) * ny * nz)};
    out.coherence = ScalarVolume{nx, ny, nz,
                                 std::vector<float>(
                                     static_cast<std::size_t>(nx) * ny * nz)};
    const double four_pi = 4.0 * kPi;
    for (int i = 0; i < nx; ++i) {
        const double x = linspace(-3.0, 3.0, nx, i);
        for (int j = 0; j < ny; ++j) {
            const double y = linspace(-3.0, 3.0, ny, j);
            const double dip = 0.3 * x + 0.2 * y;
            const double envelope = std::exp(-0.05 * (x * x + y * y));
            const double fault_base = (x - 0.5 * y);
            for (int k = 0; k < nz; ++k) {
                const double z = linspace(0.0, four_pi, nz, k);
                out.amplitude.data[(static_cast<std::size_t>(i) * ny + j) *
                                       nz +
                                   k] =
                    static_cast<float>(std::sin(z + dip) * envelope);
                const double fault_arg =
                    fault_base - 0.2 * z / four_pi;
                const double fault_mask =
                    std::exp(-15.0 * fault_arg * fault_arg);
                out.coherence.data[(static_cast<std::size_t>(i) * ny + j) *
                                       nz +
                                   k] =
                    static_cast<float>(1.0 - 0.8 * fault_mask);
            }
        }
    }
    return out;
}

const char* axis_display_name(int axis) {
    switch (axis) {
        case kAxisInline: return "Inline (0)";
        case kAxisCrossline: return "Crossline (1)";
        case kAxisTime: return "Time (2)";
        default: return "";
    }
}

const char* variant_display_name(OverlayVariant v) {
    switch (v) {
        case OverlayVariant::AlphaBlending:
            return "Variant A: Alpha Blending";
        case OverlayVariant::RgbFusion:
            return "Variant B: RGB Multi-Channel Fusion";
        case OverlayVariant::ThresholdMask:
            return "Variant C: Coherence Masking Overlay";
    }
    return "";
}

OverlayVariant variant_from_label(const std::string& label) {
    // Python: `if "Variant A" in self.variant ... elif "Variant B" ...
    // else` — substring match, C fallback.
    if (label.find("Variant A") != std::string::npos) {
        return OverlayVariant::AlphaBlending;
    }
    if (label.find("Variant B") != std::string::npos) {
        return OverlayVariant::RgbFusion;
    }
    return OverlayVariant::ThresholdMask;
}

Slice2D extract_slice(const ScalarVolume& vol, int axis, int slice_idx) {
    Slice2D out;
    if (vol.nx <= 0 || vol.ny <= 0 || vol.nz <= 0) {
        return out;
    }
    if (axis == kAxisInline) {
        const int idx =
            std::clamp(slice_idx, 0, vol.nx - 1);
        out.h = vol.ny;
        out.w = vol.nz;
        out.data.resize(static_cast<std::size_t>(out.h) * out.w);
        for (int y = 0; y < vol.ny; ++y) {
            for (int z = 0; z < vol.nz; ++z) {
                out.data[static_cast<std::size_t>(y) * out.w + z] =
                    vol.at(idx, y, z);
            }
        }
    } else if (axis == kAxisCrossline) {
        const int idx = std::clamp(slice_idx, 0, vol.ny - 1);
        out.h = vol.nx;
        out.w = vol.nz;
        out.data.resize(static_cast<std::size_t>(out.h) * out.w);
        for (int x = 0; x < vol.nx; ++x) {
            for (int z = 0; z < vol.nz; ++z) {
                out.data[static_cast<std::size_t>(x) * out.w + z] =
                    vol.at(x, idx, z);
            }
        }
    } else {
        const int idx = std::clamp(slice_idx, 0, vol.nz - 1);
        out.h = vol.nx;
        out.w = vol.ny;
        out.data.resize(static_cast<std::size_t>(out.h) * out.w);
        for (int x = 0; x < vol.nx; ++x) {
            for (int y = 0; y < vol.ny; ++y) {
                out.data[static_cast<std::size_t>(x) * out.w + y] =
                    vol.at(x, y, idx);
            }
        }
    }
    return out;
}

RgbaImage render_overlay_rgba(const Slice2D& amplitude,
                              const Slice2D& coherence,
                              OverlayVariant variant, double opacity,
                              double threshold) {
    RgbaImage img;
    img.h = amplitude.h;
    img.w = amplitude.w;
    img.rgba.assign(static_cast<std::size_t>(img.h) * img.w * 4, 0);
    // numpy dtype parity: the slice arrays are float32, so every
    // per-channel expression evaluates in float32 (e.g. (1-0.2f)*255 =
    // 204.0f -> trunc 204, NOT the float64 203.999...). Only the
    // variant-A blend runs in float64 — numpy promotes
    // uint8-array * python-float to float64 there.
    const float threshold_f = static_cast<float>(threshold);
    for (int r = 0; r < img.h; ++r) {
        for (int c = 0; c < img.w; ++c) {
            const float amp = amplitude.at(r, c);
            const float coh = coherence.at(r, c);
            // amp_norm / coh_red are uint8 arrays in Python — the blend
            // consumes the truncated values, not the floats.
            const std::uint8_t amp_norm =
                to_u8((amp + 1.0f) * 127.5f);
            std::uint8_t* px = img.rgba.data() +
                               (static_cast<std::size_t>(r) * img.w + c) * 4;
            if (variant == OverlayVariant::AlphaBlending) {
                const std::uint8_t coh_red =
                    to_u8((1.0f - coh) * 255.0f * 2.0f);
                px[0] = to_u8((1.0 - opacity) * amp_norm +
                              opacity * coh_red);
                px[1] = to_u8((1.0 - opacity) * amp_norm);
                px[2] = to_u8((1.0 - opacity) * amp_norm);
            } else if (variant == OverlayVariant::RgbFusion) {
                px[0] = to_u8(amp * 255.0f);
                px[1] = to_u8(-amp * 255.0f);
                px[2] = to_u8((1.0f - coh) * 255.0f);
            } else {
                px[0] = amp_norm;
                px[1] = amp_norm;
                px[2] = amp_norm;
                if (coh < threshold_f) {
                    px[0] = 0;
                    px[1] = 240;
                    px[2] = 255;
                }
            }
            px[3] = 255;
        }
    }
    return img;
}

}  // namespace pwb::ui_visualqa
