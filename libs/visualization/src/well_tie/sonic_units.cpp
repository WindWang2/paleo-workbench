#include <pwb/viz/well_tie/sonic_units.hpp>

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdio>
#include <numeric>

namespace pwb::viz::well_tie {

namespace {

std::string lower_strip(const std::string& value) {
    const auto first = value.find_first_not_of(" \t\r\n");
    if (first == std::string::npos) return "";
    const auto last = value.find_last_not_of(" \t\r\n");
    std::string out = value.substr(first, last - first + 1);
    std::transform(out.begin(), out.end(), out.begin(),
                   [](unsigned char c) { return std::tolower(c); });
    return out;
}

bool ends_with(const std::string& value, const std::string& suffix) {
    return value.size() >= suffix.size() &&
           value.compare(value.size() - suffix.size(), suffix.size(),
                         suffix) == 0;
}

bool in_unit_set(const std::string& u, const SonicUnit unit) {
    switch (unit) {
        case SonicUnit::us_per_m:
            return u == "us/m" || u == "usm" || u == "um";
        case SonicUnit::us_per_ft:
            return u == "us/f" || u == "us/ft" || u == "usf" || u == "uf" ||
                   u == "usft" || u == "usecft" || u == "microsecft";
    }
    return false;
}

// np.nanmedian of the pre-filtered |finite| values (all finite here).
double median_abs(const std::vector<double>& finite) {
    std::vector<double> abs_values;
    abs_values.reserve(finite.size());
    for (double v : finite) abs_values.push_back(std::abs(v));
    std::sort(abs_values.begin(), abs_values.end());
    const std::size_t n = abs_values.size();
    if (n % 2 == 1) return abs_values[n / 2];
    return 0.5 * (abs_values[n / 2 - 1] + abs_values[n / 2]);
}

// Python f"{value:.1f}" — one decimal place, fixed.
std::string fmt_1(double value) {
    char buf[64];
    std::snprintf(buf, sizeof(buf), "%.1f", value);
    return buf;
}

// Python f"{value:.5f}".
std::string fmt_5(double value) {
    char buf[64];
    std::snprintf(buf, sizeof(buf), "%.5f", value);
    return buf;
}

}  // namespace

std::optional<SonicUnit> canonical_sonic_unit(const std::string& unit) {
    if (unit.empty()) return std::nullopt;
    std::string u = lower_strip(unit);
    // Micro-sign spellings normalize to plain "u" (Python
    // .replace("µ","u").replace("μ","u")): UTF-8 µ = C2 B5, μ = CE BC.
    std::string folded;
    folded.reserve(u.size());
    for (std::size_t i = 0; i < u.size(); ++i) {
        const unsigned char c = static_cast<unsigned char>(u[i]);
        if ((c == 0xC2 || c == 0xCE) && i + 1 < u.size()) {
            const unsigned char next =
                static_cast<unsigned char>(u[i + 1]);
            if (next == 0xB5 || next == 0xBC) {
                folded.push_back('u');
                ++i;
                continue;
            }
        }
        if (c < 0x80) folded.push_back(static_cast<char>(c));
    }
    u = folded;
    if (u.empty()) return std::nullopt;
    // Remove inner spaces ("us / m" -> "us/m").
    std::string compact;
    for (char c : u) {
        if (c != ' ') compact.push_back(c);
    }
    u = compact;
    if (in_unit_set(u, SonicUnit::us_per_m) || ends_with(u, "/m")) {
        return SonicUnit::us_per_m;
    }
    if (in_unit_set(u, SonicUnit::us_per_ft) || ends_with(u, "/f") ||
        ends_with(u, "/ft")) {
        return SonicUnit::us_per_ft;
    }
    return std::nullopt;
}

NormalizedSonic normalize_sonic_units(
    const std::vector<double>& sonic, const std::optional<std::string>& unit) {
    const std::optional<SonicUnit> resolved =
        canonical_sonic_unit(unit.value_or(""));
    if (resolved && *resolved == SonicUnit::us_per_m) {
        return {sonic, SonicUnit::us_per_m, std::nullopt};
    }
    if (resolved && *resolved == SonicUnit::us_per_ft) {
        std::vector<double> scaled;
        scaled.reserve(sonic.size());
        for (double v : sonic) scaled.push_back(v * kUsFtToUsM);
        return {std::move(scaled), SonicUnit::us_per_m, std::nullopt};
    }

    std::vector<double> finite;
    finite.reserve(sonic.size());
    for (double v : sonic) {
        if (std::isfinite(v)) finite.push_back(v);
    }
    // Python f-string of a None unit prints 'None' (parity).
    const std::string unit_text = unit.value_or("None");
    if (finite.empty()) {
        return {sonic, SonicUnit::us_per_m,
                std::optional<std::string>(
                    "sonic unit '" + unit_text +
                    "' unknown and no finite samples — assumed µs/m")};
    }
    const double median = median_abs(finite);
    if (median < 150.0) {
        std::vector<double> scaled;
        scaled.reserve(sonic.size());
        for (double v : sonic) scaled.push_back(v * kUsFtToUsM);
        return {std::move(scaled), SonicUnit::us_per_m,
                std::optional<std::string>(
                    "sonic unit '" + unit_text + "' unknown; median |sonic| " +
                    fmt_1(median) + " < 150 suggests µs/ft — scaled by " +
                    fmt_5(kUsFtToUsM))};
    }
    return {sonic, SonicUnit::us_per_m,
            std::optional<std::string>(
                "sonic unit '" + unit_text + "' unknown; median |sonic| " +
                fmt_1(median) + " >= 150 — assumed µs/m")};
}

}  // namespace pwb::viz::well_tie
