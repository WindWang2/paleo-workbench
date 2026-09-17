#include <pwb/mapping/geometry_units.hpp>

#include <cctype>
#include <cmath>
#include <cstddef>
#include <string>
#include <vector>

#include <pwb/mapping/crs_policy.hpp>

namespace pwb::mapping {
namespace {

std::string trim(const std::string& s) {
    std::size_t a = 0;
    while (a < s.size() &&
           std::isspace(static_cast<unsigned char>(s[a]))) {
        ++a;
    }
    std::size_t b = s.size();
    while (b > a &&
           std::isspace(static_cast<unsigned char>(s[b - 1]))) {
        --b;
    }
    return s.substr(a, b - a);
}

// Python str.__repr__ for warning payloads — same rules as the
// crs_policy error-message helper, kept local so the frozen crs_policy
// sources stay untouched (both are pinned by their own oracles).
std::string python_str_repr(const std::string& s) {
    const bool use_double = s.find('\'') != std::string::npos &&
                            s.find('"') == std::string::npos;
    const char quote = use_double ? '"' : '\'';
    std::string out(1, quote);
    for (unsigned char c : s) {
        if (c == '\\' || c == static_cast<unsigned char>(quote)) {
            out.push_back('\\');
            out.push_back(static_cast<char>(c));
        } else if (c == '\n') {
            out += "\\n";
        } else if (c == '\r') {
            out += "\\r";
        } else if (c == '\t') {
            out += "\\t";
        } else {
            out.push_back(static_cast<char>(c));
        }
    }
    out.push_back(quote);
    return out;
}

// Python `crs!r` where the argument may be None.
std::string crs_repr(const std::optional<std::string>& crs) {
    return crs.has_value() ? python_str_repr(*crs) : std::string("None");
}

// Python: math.radians(sum(lats) / len(lats)) if lats else 0.0 — an empty
// geometry gets the full equator scale, matching the Python branch.
// math.radians(x) is x * degToRad with degToRad = π/180 (CPython).
double mean_lat_radians(const std::vector<double>& lats) {
    constexpr double kDegToRad = 3.14159265358979323846 / 180.0;
    if (lats.empty()) {
        return 0.0;
    }
    double sum = 0.0;
    for (double lat : lats) {
        sum += lat;
    }
    return (sum / static_cast<double>(lats.size())) * kDegToRad;
}

std::vector<double> collect_y(const std::vector<std::array<double, 2>>& pts) {
    std::vector<double> lats;
    lats.reserve(pts.size());
    for (const std::array<double, 2>& pt : pts) {
        // Python filters len(pt) >= 2; the C++ Ring/Polyline element type
        // is a fixed (x, y) pair, so every vertex participates.
        lats.push_back(pt[1]);
    }
    return lats;
}

std::string stripped_crs(const std::optional<std::string>& crs) {
    return trim(crs.value_or(""));
}

}  // namespace

bool is_geographic_crs(const std::optional<std::string>& crs) {
    return crs_is_geographic(crs).value_or(false);
}

std::string area_unit_label(const std::optional<std::string>& crs) {
    if (is_geographic_crs(crs)) {
        return "deg²";
    }
    const std::string stripped = stripped_crs(crs);
    if (!stripped.empty()) {
        return stripped + "-unit²";
    }
    return "unknown-unit²";
}

AreaWithUnit ring_area_with_unit(const Ring& ring,
                                 const std::optional<std::string>& crs) {
    const double raw = shoelace_area(ring);
    AreaWithUnit out;
    if (is_geographic_crs(crs)) {
        const double mean_lat = mean_lat_radians(collect_y(ring));
        const double scale =
            (kMetresPerDegreeLat * std::cos(mean_lat)) * kMetresPerDegreeLat;
        out.area = raw * scale;
        out.unit_label = "≈m² (local-scale approx, geographic CRS)";
        out.warning =
            "CRS " + crs_repr(crs) +
            " is geographic: area is a local-scale approximation "
            "from the ring's mean latitude; reproject to a projected CRS for "
            "exact areas";
        return out;
    }
    out.area = raw;
    const std::string stripped = stripped_crs(crs);
    if (!stripped.empty()) {
        out.unit_label = stripped + "-unit²";
    } else {
        out.unit_label = "unknown-unit²";
        out.warning = "CRS undeclared: area unit is unknown (not metres)";
    }
    return out;
}

LengthWithUnit polyline_length_with_unit(
    const Polyline& vertices, const std::optional<std::string>& crs) {
    LengthWithUnit out;
    if (is_geographic_crs(crs)) {
        const double mean_lat = mean_lat_radians(collect_y(vertices));
        const double scale_x = kMetresPerDegreeLat * std::cos(mean_lat);
        double total = 0.0;
        for (std::size_t i = 0; i + 1 < vertices.size(); ++i) {
            const double dx =
                (vertices[i + 1][0] - vertices[i][0]) * scale_x;
            const double dy =
                (vertices[i + 1][1] - vertices[i][1]) * kMetresPerDegreeLat;
            total += std::hypot(dx, dy);
        }
        out.length = total;
        out.unit_label = "≈m (local-scale approx, geographic CRS)";
        out.warning = "CRS " + crs_repr(crs) +
                      " is geographic: length is a local-scale approximation";
        return out;
    }
    out.length = polyline_length(vertices);
    const std::string stripped = stripped_crs(crs);
    if (!stripped.empty()) {
        out.unit_label = stripped + "-unit";
    } else {
        out.unit_label = "unknown-unit";
        out.warning = "CRS undeclared: length unit is unknown (not metres)";
    }
    return out;
}

}  // namespace pwb::mapping
