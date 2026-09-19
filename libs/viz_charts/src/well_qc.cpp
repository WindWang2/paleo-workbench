#include <pwb/viz_charts/well_qc.hpp>

#include <algorithm>
#include <cmath>
#include <limits>

namespace pwb::viz_charts {
namespace {

constexpr double kMadZScale = 0.6745;
constexpr double kEps = 1e-15;

// np.median: mean of the two middle samples for even counts.
double median_of(std::vector<double> sorted) {
    std::sort(sorted.begin(), sorted.end());
    if (sorted.empty()) {
        return std::nan("");
    }
    const std::size_t n = sorted.size();
    if (n % 2 == 1) {
        return sorted[n / 2];
    }
    return (sorted[n / 2 - 1] + sorted[n / 2]) / 2.0;
}

}  // namespace

double median_absolute_deviation(const std::vector<double>& values) {
    std::vector<double> finite;
    finite.reserve(values.size());
    for (const double v : values) {
        if (std::isfinite(v)) {
            finite.push_back(v);
        }
    }
    if (finite.empty()) {
        return std::nan("");
    }
    const double med = median_of(finite);
    std::vector<double> abs_dev;
    abs_dev.reserve(finite.size());
    for (const double v : finite) {
        abs_dev.push_back(std::fabs(v - med));
    }
    return median_of(std::move(abs_dev));
}

std::vector<double> modified_z_scores(const std::vector<double>& values) {
    std::vector<double> out(values.size(), std::nan(""));
    std::vector<double> samples;
    std::vector<std::size_t> idx;
    samples.reserve(values.size());
    for (std::size_t i = 0; i < values.size(); ++i) {
        if (std::isfinite(values[i])) {
            samples.push_back(values[i]);
            idx.push_back(i);
        }
    }
    if (samples.empty()) {
        return out;
    }
    const double median = median_of(samples);
    std::vector<double> deviation(samples.size());
    for (std::size_t i = 0; i < samples.size(); ++i) {
        deviation[i] = samples[i] - median;
    }
    std::vector<double> abs_dev;
    abs_dev.reserve(deviation.size());
    for (const double d : deviation) {
        abs_dev.push_back(std::fabs(d));
    }
    const double mad = median_of(std::move(abs_dev));
    if (mad < kEps) {
        for (std::size_t i = 0; i < samples.size(); ++i) {
            if (std::fabs(deviation[i]) >= kEps) {
                out[idx[i]] = std::copysign(std::numeric_limits<double>::infinity(),
                                            deviation[i]);
            }  // median-equal stays 0.0
            else {
                out[idx[i]] = 0.0;
            }
        }
        return out;
    }
    for (std::size_t i = 0; i < samples.size(); ++i) {
        out[idx[i]] = kMadZScale * deviation[i] / mad;
    }
    return out;
}

std::pair<std::optional<double>, std::string> compute_sand_ratio(
    std::optional<double> sand_thickness, std::optional<double> total_thickness) {
    if (!sand_thickness.has_value() || !total_thickness.has_value()) {
        return {std::nullopt, "ok"};
    }
    const double hs = *sand_thickness;
    const double ht = *total_thickness;
    if (!(std::isfinite(hs) && std::isfinite(ht))) {
        return {std::nullopt, "invalid_ratio"};
    }
    if (ht <= 0.0 || hs < 0.0 || hs > ht) {
        return {std::nullopt, "invalid_ratio"};
    }
    return {hs / ht, "ok"};
}

}  // namespace pwb::viz_charts
