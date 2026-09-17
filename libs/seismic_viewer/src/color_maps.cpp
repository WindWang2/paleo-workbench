#include <pwb/seismic_viewer/color_maps.hpp>

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

constexpr std::array<RgbStop, 2> kGrayscale{{
    {0.0, {0, 0, 0}},
    {1.0, {255, 255, 255}},
}};

// Classic seismic diverging map: blue (negative) -> white (zero) -> red.
constexpr std::array<RgbStop, 3> kSeismic{{
    {0.0, {0, 0, 132}},
    {0.5, {255, 255, 255}},
    {1.0, {132, 0, 0}},
}};

constexpr std::array<RgbStop, 4> kHeat{{
    {0.0, {0, 0, 0}},
    {0.35, {170, 20, 20}},
    {0.7, {255, 200, 0}},
    {1.0, {255, 255, 255}},
}};

constexpr auto kNames = std::to_array<std::string_view>({"grayscale", "seismic", "heat"});

} // namespace

std::vector<std::string_view> color_map_names() { return {kNames.begin(), kNames.end()}; }

ColorLut color_lut(std::string_view name) {
    ColorLut lut;
    lut.reserve(256);
    if (name == "grayscale") {
        for (int i = 0; i < 256; ++i) {
            const auto v = static_cast<std::uint8_t>(i);
            lut.push_back({v, v, v});
        }
    } else if (name == "seismic") {
        for (int i = 0; i < 256; ++i) {
            lut.push_back(sample_stops(std::span{kSeismic}, i / 255.0));
        }
    } else if (name == "heat") {
        for (int i = 0; i < 256; ++i) {
            lut.push_back(sample_stops(std::span{kHeat}, i / 255.0));
        }
    }
    return lut; // empty for unknown names
}

} // namespace pwb::seismic_viewer
