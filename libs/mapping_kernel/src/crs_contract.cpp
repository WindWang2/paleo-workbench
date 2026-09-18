#include <pwb/mapping/crs_contract.hpp>

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstddef>
#include <cstdio>
#include <string>

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

// Python `\b` after the digit run: the next character must not be a word
// character. ASCII [A-Za-z0-9_] is the practical class for CRS strings;
// bytes >= 0x80 are conservatively treated as word characters (Python's
// unicode \w includes non-ASCII letters/digits), so an exotic suffix
// leaves the text unchanged rather than splitting it.
bool is_word_char(char c) {
    const unsigned char u = static_cast<unsigned char>(c);
    return std::isalnum(u) != 0 || c == '_' || u >= 0x80;
}

// Python f"{x:g}" and C "%g" share one formatting origin (6 significant
// digits, trailing zeros stripped, exponent thresholds equal).
std::string format_g(double v) {
    char buf[64];
    std::snprintf(buf, sizeof buf, "%g", v);
    return buf;
}

}  // namespace

std::string normalize_crs(const std::optional<std::string>& crs) {
    const std::string text = trim(crs.value_or(""));
    if (text.empty()) {
        return "";
    }
    // re.match(r"^(EPSG:\d+)\b", text, re.IGNORECASE)
    static constexpr char kPrefix[5] = {'E', 'P', 'S', 'G', ':'};
    bool head_ok = text.size() >= 5;
    for (std::size_t i = 0; head_ok && i < 5; ++i) {
        const char c = text[i];
        head_ok = c == kPrefix[i] ||
                  (c >= 'a' && c <= 'z' &&
                   static_cast<char>(c - 'a') + 'A' == kPrefix[i]);
    }
    if (head_ok) {
        std::size_t digits_end = 5;
        while (digits_end < text.size() && text[digits_end] >= '0' &&
               text[digits_end] <= '9') {
            ++digits_end;
        }
        // `\d+\b`: every shorter digit run would end right before a digit
        // (a word char), so only the full run can satisfy the boundary.
        if (digits_end > 5 &&
            (digits_end == text.size() || !is_word_char(text[digits_end]))) {
            return "EPSG:" + text.substr(5, digits_end - 5);
        }
    }
    return text;
}

CRSResolution resolve_crs(const std::optional<std::string>& value,
                          const std::string& purpose,
                          const std::optional<std::string>& fallback) {
    const std::string normalized = normalize_crs(value);
    if (!normalized.empty()) {
        CRSResolution out;
        out.crs = normalized;
        out.declared = true;
        return out;
    }
    const std::string fallback_text = normalize_crs(fallback);
    if (!fallback_text.empty()) {
        CRSResolution out;
        out.crs = fallback_text;
        out.declared = false;
        out.degraded_reason =
            purpose + ": CRS 未声明，按记录在案的默认 " + fallback_text +
            " 处理（降级）";
        return out;
    }
    CRSResolution out;
    out.declared = false;
    out.degraded_reason =
        purpose + ": CRS 未声明且无默认——按未知坐标处理（降级）";
    return out;
}

std::string panel_publish_crs(const std::optional<std::string>& value,
                              const std::string& purpose) {
    const CRSResolution resolution = resolve_crs(value, purpose);
    if (!resolution.declared) {
        // Python logs the degraded reason here; the kernel returns the
        // honest "" and leaves surfacing to the caller.
        return "";
    }
    return resolution.crs;
}

std::optional<bool> crs_axis_unit_metres(const std::optional<std::string>& crs) {
    const std::string text = trim(crs.value_or(""));
    if (text.empty()) {
        return std::nullopt;
    }
    // Python parses the CRS with pyproj and inspects the first horizontal
    // axis unit (metre/meter/m). The kernel has no pyproj — this is the
    // ImportError path: unverifiable, never guessed.
    return std::nullopt;
}

double scale_denominator_from_pixels(double map_units_per_pixel,
                                     double pixels_per_inch,
                                     const std::optional<std::string>& crs) {
    const std::optional<bool> axis_metres = crs_axis_unit_metres(crs);
    if (!axis_metres.has_value() || !*axis_metres) {
        return 0.0;
    }
    if (map_units_per_pixel <= 0.0 || pixels_per_inch <= 0.0) {
        return 0.0;
    }
    // Unreachable in the kernel today (no pyproj → axes never verifiably
    // metres) but kept line-faithful: any future axis authority lands
    // directly on the QGIS pixel-canvas formula.
    return map_units_per_pixel * 39.370078740157481 * pixels_per_inch;
}

std::optional<Domain> crs_coordinate_domain(const std::optional<std::string>& crs) {
    const std::string text = normalize_crs(crs);
    if (text.empty()) {
        return std::nullopt;
    }
    if (crs_is_geographic(text) == true) {
        // Axis-analytic domain: exact, no slack.
        return kGeographicDegreeDomain;
    }
    // Python transforms the projected CRS's area_of_use corners back into
    // CRS units (+2% box slack). Kernel: no pyproj → cannot derive →
    // nullopt (cannot-verify ≠ pass).
    return std::nullopt;
}

std::string DomainMismatch::describe() const {
    return "声明 CRS " + crs + " 的有效坐标域为 x[" + format_g(domain[0]) +
           ", " + format_g(domain[2]) + "] / y[" + format_g(domain[1]) +
           ", " + format_g(domain[3]) + "]，数据实际坐标范围为 x[" +
           format_g(extent[0]) + ", " + format_g(extent[2]) + "] / y[" +
           format_g(extent[1]) + ", " + format_g(extent[3]) + "]";
}

std::optional<DomainMismatch> coordinate_domain_mismatch(
    const std::optional<std::string>& crs, const std::optional<Domain>& extent) {
    if (!extent.has_value()) {
        return std::nullopt;
    }
    const double xmin = (*extent)[0];
    const double ymin = (*extent)[1];
    const double xmax = (*extent)[2];
    const double ymax = (*extent)[3];
    if (!(xmin <= xmax && ymin <= ymax)) {
        return std::nullopt;
    }
    const std::optional<Domain> domain = crs_coordinate_domain(crs);
    if (!domain.has_value()) {
        return std::nullopt;
    }
    const double dminx = (*domain)[0];
    const double dminy = (*domain)[1];
    const double dmaxx = (*domain)[2];
    const double dmaxy = (*domain)[3];
    const double eps =
        kDomainEpsilon *
        std::max({1.0, std::fabs(dmaxx - dminx), std::fabs(dmaxy - dminy)});
    const bool fits = xmin >= dminx - eps && xmax <= dmaxx + eps &&
                      ymin >= dminy - eps && ymax <= dmaxy + eps;
    if (fits) {
        return std::nullopt;
    }
    DomainMismatch out;
    const std::string normalized = normalize_crs(crs);
    out.crs = !normalized.empty() ? normalized : crs.value_or("");
    out.extent = *extent;
    out.domain = *domain;
    return out;
}

CRSInference infer_crs_from_extent(const std::optional<Domain>& extent) {
    if (!extent.has_value() ||
        !((*extent)[0] <= (*extent)[2] && (*extent)[1] <= (*extent)[3])) {
        return {"", "数据坐标范围不可用——不推断"};
    }
    if (!coordinate_domain_mismatch(std::string("EPSG:4326"), extent)
             .has_value()) {
        return {"EPSG:4326", "数据坐标完全落在经纬度域内（地理坐标）"};
    }
    return {"", "数据坐标超出经纬度域（本地/投影坐标）——保持本地"};
}

}  // namespace pwb::mapping
