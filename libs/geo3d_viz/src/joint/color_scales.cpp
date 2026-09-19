// color_scales.cpp — frozen stop tables + robust colorization
// (color_scales.py @ 08851951).
#include "pwb/geo3d_viz/joint/color_scales.hpp"

#include <algorithm>
#include <cmath>
#include <map>

namespace pwb::geo3d_viz::joint {

namespace {

const std::map<std::string, std::vector<RgbStop>>& seismic_scales() {
    static const std::map<std::string, std::vector<RgbStop>> scales = {
        {"blue-white-red",
         {{33, 102, 172}, {255, 255, 255}, {178, 24, 43}}},
        {"gray", {{0, 0, 0}, {128, 128, 128}, {255, 255, 255}}},
        {"red-white-blue",
         {{178, 24, 43}, {255, 255, 255}, {33, 102, 172}}},
    };
    return scales;
}

const std::map<std::string, std::vector<RgbStop>>& gr_scales() {
    static const std::map<std::string, std::vector<RgbStop>> scales = {
        {"viridis",
         {{68, 1, 84},
          {59, 82, 139},
          {33, 145, 140},
          {94, 201, 98},
          {253, 231, 37}}},
        {"cividis",
         {{0, 34, 78},
          {66, 64, 134},
          {122, 123, 120},
          {188, 174, 108},
          {254, 232, 56}}},
        {"plasma",
         {{13, 8, 135},
          {126, 3, 168},
          {204, 71, 120},
          {248, 148, 65},
          {240, 249, 33}}},
        {"turbo",
         {{48, 18, 59},
          {70, 107, 227},
          {26, 228, 182},
          {249, 231, 33},
          {234, 42, 20}}},
    };
    return scales;
}

// numpy percentile(method="linear") on a sorted copy.
double percentile_linear(std::vector<double> sorted, double q) {
    if (sorted.empty()) return std::numeric_limits<double>::quiet_NaN();
    std::sort(sorted.begin(), sorted.end());
    const double pos = q / 100.0 *
                       static_cast<double>(sorted.size() - 1);
    const std::size_t lo = static_cast<std::size_t>(std::floor(pos));
    const std::size_t hi = static_cast<std::size_t>(
        std::min<double>(std::ceil(pos),
                         static_cast<double>(sorted.size() - 1)));
    const double frac = pos - static_cast<double>(lo);
    return sorted[lo] + frac * (sorted[hi] - sorted[lo]);
}

}  // namespace

const std::vector<RgbStop>& seismic_color_scale(const std::string& name) {
    const auto& scales = seismic_scales();
    const auto it = scales.find(name);
    return it != scales.end() ? it->second
                              : scales.at("blue-white-red");
}

const std::vector<RgbStop>& gr_color_scale(const std::string& name) {
    const auto& scales = gr_scales();
    const auto it = scales.find(name);
    return it != scales.end() ? it->second : scales.at("viridis");
}

std::vector<std::uint8_t> colorize_amplitude(
    const std::vector<float>& amplitude, const std::string& color_scale) {
    // limit = P98 of |finite| values, robust symmetric range.
    std::vector<double> finite;
    finite.reserve(amplitude.size());
    for (float v : amplitude) {
        if (std::isfinite(v)) finite.push_back(std::fabs(static_cast<double>(v)));
    }
    // Python computes the percentile over a float32 array, so the limit
    // itself carries float32 quantization; reproduce it exactly.
    double limit =
        finite.empty()
            ? 1.0
            : static_cast<double>(static_cast<float>(
                  percentile_linear(finite, 98.0)));
    if (!std::isfinite(limit) || limit <= 1e-12) limit = 1.0;

    const std::vector<RgbStop>& stops = seismic_color_scale(color_scale);
    std::vector<std::uint8_t> rgba(amplitude.size() * 4);
    for (std::size_t i = 0; i < amplitude.size(); ++i) {
        const double value = static_cast<double>(amplitude[i]);
        std::uint8_t rgb[3] = {128, 128, 128};
        if (std::isfinite(value)) {
            const double normalized =
                std::max(-1.0, std::min(1.0, value / limit));
            double t = 0.0;
            const RgbStop* a = nullptr;
            const RgbStop* b = nullptr;
            if (normalized <= 0.0) {
                a = &stops[0];
                b = &stops[1];
                t = std::max(0.0, std::min(1.0, normalized + 1.0));
            } else {
                a = &stops[1];
                b = &stops[2];
                t = std::max(0.0, std::min(1.0, normalized));
            }
            for (int k = 0; k < 3; ++k) {
                const double channel =
                    static_cast<double>((*a)[k]) +
                    t * (static_cast<double>((*b)[k]) -
                         static_cast<double>((*a)[k]));
                // np.rint = round-half-to-even = nearbyint(FE_TONEAREST).
                rgb[k] = static_cast<std::uint8_t>(
                    std::nearbyint(channel));
            }
        }
        std::size_t o = i * 4;
        rgba[o] = rgb[0];
        rgba[o + 1] = rgb[1];
        rgba[o + 2] = rgb[2];
        rgba[o + 3] = 255;
    }
    return rgba;
}

std::vector<std::uint8_t> colorize_gr(
    const std::vector<double>& values, std::pair<double, double> value_range,
    const std::string& color_scale) {
    double lo = value_range.first;
    double hi = value_range.second;
    if (!std::isfinite(lo) || !std::isfinite(hi) || hi <= lo) {
        lo = 0.0;
        hi = 1.0;
    }
    const std::vector<RgbStop>& stops = gr_color_scale(color_scale);
    const double last = static_cast<double>(stops.size() - 1);
    std::vector<std::uint8_t> rgba(values.size() * 4);
    for (std::size_t i = 0; i < values.size(); ++i) {
        const double sample = values[i];
        if (!std::isfinite(sample)) {
            rgba[i * 4 + 0] = kMissingGrRgba[0];
            rgba[i * 4 + 1] = kMissingGrRgba[1];
            rgba[i * 4 + 2] = kMissingGrRgba[2];
            rgba[i * 4 + 3] = kMissingGrRgba[3];
            continue;
        }
        double normalized =
            (sample - lo) / (hi - lo);
        normalized = std::isfinite(normalized)
                         ? std::max(0.0, std::min(1.0, normalized))
                         : 0.0;
        const double position = normalized * last;
        const std::size_t left = static_cast<std::size_t>(
            std::floor(position));
        const std::size_t right =
            std::min(left + 1, stops.size() - 1);
        const double fraction = position - static_cast<double>(left);
        for (int k = 0; k < 3; ++k) {
            const double channel =
                static_cast<double>(stops[left][k]) +
                fraction * (static_cast<double>(stops[right][k]) -
                            static_cast<double>(stops[left][k]));
            rgba[i * 4 + k] = static_cast<std::uint8_t>(
                std::nearbyint(channel));
        }
        rgba[i * 4 + 3] = 255;
    }
    return rgba;
}

}  // namespace pwb::geo3d_viz::joint
