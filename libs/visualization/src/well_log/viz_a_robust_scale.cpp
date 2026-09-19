// VIZ-A — robust display-range port. Numeric-parity notes (frozen against
// the Python oracle): np.percentile default linear interpolation;
// math.isclose(p2, p98) uses rel_tol=1e-9; the null mask uses
// np.isclose(rtol=1e-5, atol=1e-3); Python round() is emulated via
// printf correctly-rounded decimal conversion + strtod (see py_round).

#include "pwb/viz/well_log_robust_scale.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdio>
#include <cstdlib>

namespace pwb::viz {

namespace {

// np.percentile(valid, q) with the default linear method over a sorted copy.
double percentile(std::vector<double> sorted, double q) {
    if (sorted.empty()) return 0.0;
    std::sort(sorted.begin(), sorted.end());
    if (sorted.size() == 1) return sorted.front();
    const double position = (q / 100.0) * static_cast<double>(sorted.size() - 1);
    const std::size_t lower = static_cast<std::size_t>(std::floor(position));
    const std::size_t upper = std::min(lower + 1, sorted.size() - 1);
    const double fraction = position - static_cast<double>(lower);
    return sorted[lower] + fraction * (sorted[upper] - sorted[lower]);
}

// Python round(x, digits) — correctly rounded at the decimal digit (CPython
// uses exact decimal conversion; glibc printf has the same property, and
// the strtod hop back keeps the double nearest to the decimal result). A
// scale-multiply + nearbyint is NOT equivalent: e.g. round(2.675, 2) must
// give 2.67 (the double is 2.67499...), while 2.675*100 rounds up to
// exactly 267.5 and would produce 2.68 (review R1-P1).
double py_round(double value, int digits) {
    char buf[64];
    std::snprintf(buf, sizeof(buf), "%.*f", digits, value);
    return std::strtod(buf, nullptr);
}

bool contains_any(const std::string& text, const char* const* keys) {
    for (const char* const* key = keys; *key != nullptr; ++key) {
        if (text.find(*key) != std::string::npos) return true;
    }
    return false;
}

DisplayRange general_quantile_range(const std::vector<double>& valid) {
    std::vector<double> sorted(valid);
    std::sort(sorted.begin(), sorted.end());
    double p2 = percentile(sorted, 2.0);
    double p98 = percentile(sorted, 98.0);

    const bool close = std::fabs(p2 - p98) <=
                       1e-9 * std::max(std::fabs(p2), std::fabs(p98));
    if (close || p2 >= p98) {
        const double vmin = sorted.front();
        const double vmax = sorted.back();
        if (std::fabs(vmin - vmax) <= 1e-9 * std::max(std::fabs(vmin), std::fabs(vmax))) {
            return DisplayRange{vmin, vmin + 10.0};
        }
        p2 = vmin;
        p98 = vmax;
    }

    const double span = p98 - p2;
    double vmin = p2 - 0.05 * span;
    double vmax = p98 + 0.05 * span;
    if (span > 10) {
        vmin = std::floor(vmin * 10.0) / 10.0;
        vmax = std::ceil(vmax * 10.0) / 10.0;
    } else {
        vmin = py_round(vmin, 2);
        vmax = py_round(vmax, 2);
    }
    return DisplayRange{vmin, vmax};
}

}  // namespace

DisplayRange compute_robust_display_range(
    const std::vector<double>& values, const std::string& curve_name,
    std::optional<double> null_value) {
    std::vector<double> valid;
    valid.reserve(values.size());
    for (double value : values) {
        if (!std::isfinite(value)) continue;
        if (null_value.has_value() && std::isfinite(*null_value) &&
            std::fabs(value - *null_value) <=
                1e-3 + 1e-5 * std::fabs(*null_value)) {
            continue;  // np.isclose(arr, null, atol=1e-3)
        }
        valid.push_back(value);
    }
    if (valid.empty()) return DisplayRange{0.0, 100.0};

    std::string upper;
    upper.reserve(curve_name.size());
    for (char c : curve_name) {
        upper.push_back(static_cast<char>(std::toupper(
            static_cast<unsigned char>(c))));
    }
    // .strip() parity.
    const auto first = upper.find_first_not_of(" \t\r\n");
    const auto last = upper.find_last_not_of(" \t\r\n");
    upper = first == std::string::npos
                ? std::string()
                : upper.substr(first, last - first + 1);

    static const char* kGrKeys[] = {"GR", "\xE4\xBC\xBD\xE9\xA9\xAC", nullptr};  // 伽马
    static const char* kRhobKeys[] = {"RHOB", "DEN", "\xE5\xAF\x86\xE5\xBA\xA6",
                                      nullptr};  // 密度
    static const char* kNphiKeys[] = {"NPHI", "CNL", "\xE4\xB8\xAD\xE5\xAD\x90",
                                      nullptr};  // 中子

    std::optional<DisplayRange> preset;
    if (contains_any(upper, kGrKeys)) {
        const double p1 = percentile(valid, 1.0);
        const double p99 = percentile(valid, 99.0);
        preset = DisplayRange{std::max(0.0, std::min(p1, 0.0)),
                              std::max(150.0, py_round(p99 + 10.0, 1))};
    } else if (contains_any(upper, kRhobKeys)) {
        const double p1 = percentile(valid, 1.0);
        const double p99 = percentile(valid, 99.0);
        preset = DisplayRange{std::max(1.5, py_round(p1 - 0.05, 2)),
                              std::min(3.0, py_round(p99 + 0.05, 2))};
    } else if (contains_any(upper, kNphiKeys)) {
        const double p1 = percentile(valid, 1.0);
        const double p99 = percentile(valid, 99.0);
        preset = DisplayRange{std::max(-0.05, py_round(p1 - 0.02, 2)),
                              std::min(1.0, py_round(p99 + 0.02, 2))};
    }

    // #113: an inverted preset (wrong units for the family) falls back to
    // the general quantile path instead of producing vmin > vmax.
    if (preset.has_value() && preset->vmin <= preset->vmax) {
        return *preset;
    }
    return general_quantile_range(valid);
}

}  // namespace pwb::viz
