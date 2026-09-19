#include <pwb/seismic_viewer/color_maps.hpp>

#include <algorithm>
#include <cmath>
#include <span>

namespace pwb::seismic_viewer {
namespace {

struct RgbStop {
    double t; // control point in [0, 1]
    std::array<std::uint8_t, 3> rgb;
};

// Linear interpolation over control points; t is clamped to [0, 1].
std::array<std::uint8_t, 3> sample_stops(std::span<const RgbStop> stops, double t) {
    if (t < 0.0) {
        t = 0.0;
    } else if (t > 1.0) {
        t = 1.0;
    }
    for (std::size_t i = 0; i + 1 < stops.size(); ++i) {
        if (t <= stops[i + 1].t) {
            const double span = stops[i + 1].t - stops[i].t;
            const double f = span > 0.0 ? (t - stops[i].t) / span : 0.0;
            const auto& a = stops[i].rgb;
            const auto& b = stops[i + 1].rgb;
            return {static_cast<std::uint8_t>(std::lround(a[0] + f * (b[0] - a[0]))),
                    static_cast<std::uint8_t>(std::lround(a[1] + f * (b[1] - a[1]))),
                    static_cast<std::uint8_t>(std::lround(a[2] + f * (b[2] - a[2])))};
        }
    }
    return stops.back().rgb;
}

// VIZ-D: the colormap.py (@08851951) builders quantize with astype(uint8) —
// a TRUNCATING cast — on np.interp ramps sampled at t = i/(n-1) (cyclic maps
// use i/n, endpoint=False). `sample_ramp` follows numpy's interp arithmetic
// (precomputed slope, fp_lo + slope*(t - xp_lo)) so boundary samples land on
// the same integer after truncation as the frozen Python LUTs.
struct XyStop {
    double t;
    double value;
};

[[nodiscard]] std::uint8_t sample_ramp(std::span<const XyStop> stops, double t) {
    if (t <= stops.front().t) {
        return static_cast<std::uint8_t>(stops.front().value);
    }
    if (t >= stops.back().t) {
        return static_cast<std::uint8_t>(stops.back().value);
    }
    for (std::size_t i = 0; i + 1 < stops.size(); ++i) {
        if (t <= stops[i + 1].t) {
            const double slope = (stops[i + 1].value - stops[i].value) /
                                 (stops[i + 1].t - stops[i].t);
            return static_cast<std::uint8_t>(stops[i].value +
                                             slope * (t - stops[i].t));
        }
    }
    return static_cast<std::uint8_t>(stops.back().value);
}

[[nodiscard]] std::uint8_t trunc_u8(double v) {
    if (!(v > 0.0)) { // NaN / negative -> 0
        return 0;
    }
    if (v > 255.0) {
        return 255;
    }
    return static_cast<std::uint8_t>(v);
}

// Classic seismic diverging map, Petrel/OpendTect style (colormap.py
// _build_seismic): dark blue -> blue -> white -> red -> dark red.
constexpr std::array<XyStop, 5> kSeismicR{{
    {0.0, 0.0},
    {0.25, 0.0},
    {0.5, 255.0},
    {0.75, 255.0},
    {1.0, 128.0},
}};
constexpr std::array<XyStop, 5> kSeismicG{{
    {0.0, 0.0},
    {0.25, 0.0},
    {0.5, 255.0},
    {0.75, 0.0},
    {1.0, 0.0},
}};
constexpr std::array<XyStop, 5> kSeismicB{{
    {0.0, 128.0},
    {0.25, 255.0},
    {0.5, 255.0},
    {0.75, 0.0},
    {1.0, 0.0},
}};

// viridis keypoint approximation (colormap.py _build_viridis).
constexpr std::array<XyStop, 5> kViridisR{{
    {0.0, 68.0},
    {0.25, 59.0},
    {0.5, 33.0},
    {0.75, 95.0},
    {1.0, 253.0},
}};
constexpr std::array<XyStop, 5> kViridisG{{
    {0.0, 1.0},
    {0.25, 82.0},
    {0.5, 145.0},
    {0.75, 180.0},
    {1.0, 231.0},
}};
constexpr std::array<XyStop, 5> kViridisB{{
    {0.0, 84.0},
    {0.25, 139.0},
    {0.5, 140.0},
    {0.75, 86.0},
    {1.0, 37.0},
}};

constexpr std::array<RgbStop, 4> kHeat{{
    {0.0, {0, 0, 0}},
    {0.35, {170, 20, 20}},
    {0.7, {255, 200, 0}},
    {1.0, {255, 255, 255}},
}};

constexpr auto kNames = std::to_array<std::string_view>(
    {"grayscale", "seismic", "seismic_r", "gray", "jet", "hsv", "viridis",
     "phase_wheel", "heat"});

std::array<std::uint8_t, 3> seismic_rgb(std::size_t i, std::size_t n) {
    // np.linspace rounds as i * (1/(n-1)), which differs from i/(n-1) by an
    // ulp on some i and flips the truncating cast at integer boundaries.
    const double t = static_cast<double>(i) * (1.0 / static_cast<double>(n - 1));
    return {sample_ramp(std::span{kSeismicR}, t), sample_ramp(std::span{kSeismicG}, t),
            sample_ramp(std::span{kSeismicB}, t)};
}

} // namespace

std::vector<std::string_view> color_map_names() { return {kNames.begin(), kNames.end()}; }

ColorLut color_lut(std::string_view name) {
    ColorLut lut;
    lut.reserve(256);
    if (name == "grayscale" || name == "gray") {
        // np.linspace(0, 255, 256).astype(uint8) — exact identity ramp;
        // "gray" is the colormap.py registry key, "grayscale" the v3 name.
        for (int i = 0; i < 256; ++i) {
            const auto v = static_cast<std::uint8_t>(i);
            lut.push_back({v, v, v});
        }
    } else if (name == "seismic") {
        for (std::size_t i = 0; i < 256; ++i) {
            const auto rgb = seismic_rgb(i, 256);
            lut.push_back({rgb[0], rgb[1], rgb[2]});
        }
    } else if (name == "seismic_r") {
        // _build_seismic_r: the reversed seismic LUT (red-negative).
        for (std::size_t i = 0; i < 256; ++i) {
            const auto rgb = seismic_rgb(255 - i, 256);
            lut.push_back({rgb[0], rgb[1], rgb[2]});
        }
    } else if (name == "viridis") {
        for (std::size_t i = 0; i < 256; ++i) {
            const double t = static_cast<double>(i) * (1.0 / 255.0);
            lut.push_back({sample_ramp(std::span{kViridisR}, t),
                           sample_ramp(std::span{kViridisG}, t),
                           sample_ramp(std::span{kViridisB}, t)});
        }
    } else if (name == "jet") {
        for (std::size_t i = 0; i < 256; ++i) {
            const double t = static_cast<double>(i) * (1.0 / 255.0);
            const auto channel = [t](double centre) {
                return trunc_u8(
                    std::clamp(1.5 - std::abs(4.0 * t - centre), 0.0, 1.0) * 255.0);
            };
            lut.push_back({channel(3.0), channel(2.0), channel(1.0)});
        }
    } else if (name == "hsv") {
        // Cyclic: t = i/n (endpoint=False); S = V = 1.
        for (std::size_t i = 0; i < 256; ++i) {
            const double h = static_cast<double>(i) / 256.0;
            const double h6 = h * 6.0;
            const int sector = static_cast<int>(std::floor(h6)) % 6;
            const double f = h6 - std::floor(h6);
            double r = 0.0, g = 0.0, b = 0.0;
            switch (sector) {
            case 0: r = 1.0; g = f; b = 0.0; break;
            case 1: r = 1.0 - f; g = 1.0; b = 0.0; break;
            case 2: r = 0.0; g = 1.0; b = f; break;
            case 3: r = 0.0; g = 1.0 - f; b = 1.0; break;
            case 4: r = f; g = 0.0; b = 1.0; break;
            default: r = 1.0; g = 0.0; b = 1.0 - f; break;
            }
            lut.push_back({trunc_u8(r * 255.0), trunc_u8(g * 255.0), trunc_u8(b * 255.0)});
        }
    } else if (name == "phase_wheel") {
        // Cyclic cos-based RGB phase wheel (endpoint=False).
        constexpr double two_pi = 6.283185307179586476925286766559;
        for (std::size_t i = 0; i < 256; ++i) {
            const double t = static_cast<double>(i) / 256.0;
            lut.push_back(
                {trunc_u8((0.5 + 0.5 * std::cos(two_pi * t)) * 255.0),
                 trunc_u8((0.5 + 0.5 * std::cos(two_pi * t - two_pi / 3.0)) * 255.0),
                 trunc_u8((0.5 + 0.5 * std::cos(two_pi * t - 2.0 * two_pi / 3.0)) * 255.0)});
        }
    } else if (name == "heat") {
        // C++-only extra retained from v3 (no colormap.py counterpart).
        for (int i = 0; i < 256; ++i) {
            lut.push_back(sample_stops(std::span{kHeat}, i / 255.0));
        }
    }
    return lut; // empty for unknown names
}

} // namespace pwb::seismic_viewer
