#include <pwb/ui_composite/crs_gate.hpp>

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdio>
#include <limits>

namespace pwb::ui_composite {
namespace {

constexpr double kDomainSlack = 1.0;  // 合法球面环绕不算失配

std::string normalized(const std::string& value) {
    std::string text = value;
    const auto first = text.find_first_not_of(" \t\n\r");
    const auto last = text.find_last_not_of(" \t\n\r");
    if (first == std::string::npos) {
        return {};
    }
    text = text.substr(first, last - first + 1);
    std::transform(text.begin(), text.end(), text.begin(),
                   [](unsigned char c) {
                       return static_cast<char>(std::tolower(c));
                   });
    return text;
}

std::string format_g(double value) {
    // Python f"{v:g}" — %g with default precision 6.
    char buf[64];
    std::snprintf(buf, sizeof(buf), "%g", value);
    return buf;
}

}  // namespace

const std::set<std::string>& geographic_authids() {
    static const std::set<std::string> authids = {
        "epsg:4326", "epsg:4490", "epsg:4214", "epsg:4610", "epsg:4269",
        "epsg:4267", "epsg:4230", "epsg:4314", "ogc:crs84",
    };
    return authids;
}

bool is_geographic_declaration(const std::string& declared_crs) {
    const std::string authid = normalized(declared_crs);
    if (authid.empty()) {
        return false;
    }
    if (geographic_authids().count(authid)) {
        return true;
    }
    return authid.rfind("+proj=longlat", 0) == 0 ||
           authid.rfind("+proj=latlong", 0) == 0;
}

std::optional<Bounds> feature_bounds(
    const std::vector<MapPoint>& coords) {
    double xmin = std::numeric_limits<double>::max();
    double ymin = std::numeric_limits<double>::max();
    double xmax = std::numeric_limits<double>::lowest();
    double ymax = std::numeric_limits<double>::lowest();
    bool has = false;
    for (const MapPoint& coord : coords) {
        const double x = coord[0], y = coord[1];
        if (!std::isfinite(x) || !std::isfinite(y)) {
            continue;
        }
        has = true;
        xmin = std::min(xmin, x);
        ymin = std::min(ymin, y);
        xmax = std::max(xmax, x);
        ymax = std::max(ymax, y);
    }
    if (!has) {
        return std::nullopt;
    }
    return Bounds{xmin, ymin, xmax, ymax};
}

CrsDomainCheck validate_crs_domain(
    const std::string& declared_crs,
    const std::optional<Bounds>& bounds) {
    std::string declared = declared_crs;
    const auto first = declared.find_first_not_of(" \t\n\r");
    const auto last = declared.find_last_not_of(" \t\n\r");
    declared = first == std::string::npos
                   ? std::string{}
                   : declared.substr(first, last - first + 1);
    const bool geographic = is_geographic_declaration(declared);
    if (!geographic) {
        return CrsDomainCheck{.ok = true,
                              .declared_crs = declared,
                              .geographic_declared = false,
                              .bounds = bounds};
    }
    if (!bounds.has_value()) {
        return CrsDomainCheck{.ok = true,
                              .declared_crs = declared,
                              .geographic_declared = true,
                              .bounds = std::nullopt};
    }
    const auto& [xmin, ymin, xmax, ymax] = *bounds;
    if (xmin < -180.0 - kDomainSlack || xmax > 180.0 + kDomainSlack ||
        ymin < -90.0 - kDomainSlack || ymax > 90.0 + kDomainSlack) {
        return CrsDomainCheck{
            .ok = false,
            .declared_crs = declared,
            .geographic_declared = true,
            .bounds = bounds,
            .reason = crs_mismatch_reason(declared, *bounds)};
    }
    return CrsDomainCheck{.ok = true,
                          .declared_crs = declared,
                          .geographic_declared = true,
                          .bounds = bounds};
}

std::string crs_mismatch_reason(const std::string& declared,
                                const Bounds& bounds) {
    const auto& [xmin, ymin, xmax, ymax] = bounds;
    return "声明 " + declared + "（经纬度域 ±180/±90），但数据坐标范围 x:[" +
           format_g(xmin) + ", " + format_g(xmax) + "]、y:[" +
           format_g(ymin) + ", " + format_g(ymax) +
           "] 为本地坐标——失配声明会污染编辑缓冲几何。";
}

std::map<std::string, CrsDomainCheck> collect_crs_mismatches(
    const std::vector<std::tuple<std::string, std::string,
                                 std::vector<MapPoint>>>& layers) {
    std::map<std::string, CrsDomainCheck> mismatches;
    for (const auto& [layer_id, declared, coords] : layers) {
        CrsDomainCheck check =
            validate_crs_domain(declared, feature_bounds(coords));
        if (!check.ok) {
            mismatches[layer_id] = std::move(check);
        }
    }
    return mismatches;
}

}  // namespace pwb::ui_composite
