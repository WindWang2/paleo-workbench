#include <pwb/mapping/crs_policy.hpp>

#include <cctype>
#include <cstddef>
#include <stdexcept>
#include <string_view>
#include <utility>

namespace pwb::mapping {
namespace {

// Well-known geographic CRS ids recognised without pyproj. EPSG:3857 is
// in this set in Python but is projected; _PROJECTED_EXCEPTIONS wins.
constexpr std::string_view kKnownGeographic[] = {
    "EPSG:4326",
    "EPSG:4269",  // NAD83
    "EPSG:4267",  // NAD27
    "EPSG:4214",  // Beijing 1954
    "EPSG:4610",  // Xian 1980
    "EPSG:4490",  // CGCS2000
    "EPSG:3857",  // Web Mercator — projected metres, not degrees
};

constexpr std::string_view kProjectedExceptions[] = {
    "EPSG:3857",
};

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

std::string ascii_upper(std::string s) {
    for (char& c : s) {
        c = static_cast<char>(std::toupper(static_cast<unsigned char>(c)));
    }
    return s;
}

template <std::size_t N>
bool contains_token(const std::string_view (&ids)[N], std::string_view token) {
    for (std::string_view id : ids) {
        if (id == token) return true;
    }
    return false;
}

// Python: token = crs.split("/")[0].strip().upper()
std::string crs_token(const std::string& crs) {
    const auto slash = crs.find('/');
    const std::string head =
        slash == std::string::npos ? crs : crs.substr(0, slash);
    return ascii_upper(trim(head));
}

bool is_known_policy(std::string_view s) {
    for (std::string_view p : kDistancePolicies) {
        if (p == s) return true;
    }
    return false;
}

// Python 3 str.__repr__ for the ValueError payload (simple tokens).
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

}  // namespace

std::optional<bool> crs_is_geographic(const std::optional<std::string>& crs) {
    // Python: `if not crs: return None` — None and "" only, not whitespace.
    if (!crs.has_value() || crs->empty()) {
        return std::nullopt;
    }
    const std::string token = crs_token(*crs);
    if (contains_token(kProjectedExceptions, token)) {
        return false;
    }
    if (contains_token(kKnownGeographic, token)) {
        return true;
    }
    // C++ has no pyproj. This is the Python `except Exception: return None`
    // path: unknown ids are unverifiable rather than guessed.
    return std::nullopt;
}

DistancePolicy resolve_distance_policy(
    const std::optional<std::string>& crs,
    const std::optional<std::string>& distance_policy) {
    const std::optional<bool> axes_known = crs_is_geographic(crs);

    // declared = (distance_policy or "").strip() or None
    std::optional<std::string> declared;
    {
        const std::string stripped = trim(distance_policy.value_or(""));
        if (!stripped.empty()) declared = stripped;
    }
    if (declared.has_value() && !is_known_policy(*declared)) {
        throw std::invalid_argument(
            "distance_policy must be one of ('planar', 'planar_degrees', "
            "'projected'), got " +
            python_str_repr(*declared));
    }

    // Python `if crs is None` is identity-None, not `if not crs`: an empty
    // CRS string falls through to the unverifiable-axis path.
    if (!crs.has_value()) {
        const std::string policy = declared.value_or(kPolicyPlanar);
        return DistancePolicy{
            policy,
            std::nullopt,
            std::nullopt,
            "distance_policy=" + policy +
                "; CRS undeclared — planar assumption unverified",
            std::nullopt,
        };
    }

    const std::optional<bool> geographic = axes_known;
    const bool geographic_true =
        geographic.has_value() && *geographic;

    if (declared.has_value() && *declared == kPolicyPlanarDegrees) {
        // `None if geographic else "..."` — warning unless geographic is True.
        std::optional<std::string> warning;
        if (!geographic_true) {
            warning = "planar_degrees declared for a non-geographic CRS";
        }
        return DistancePolicy{
            kPolicyPlanarDegrees,
            *crs,
            geographic,
            "distance_policy=planar_degrees; operator explicitly accepted "
            "degree-as-planar distances",
            std::move(warning),
        };
    }
    if (declared.has_value() && *declared == kPolicyProjected) {
        // warning only when geographic is True (None/False → no warning).
        std::optional<std::string> warning;
        if (geographic_true) {
            warning = "projected policy declared but CRS is geographic";
        }
        return DistancePolicy{
            kPolicyProjected,
            *crs,
            geographic,
            "distance_policy=projected; CRS " + *crs +
                " declared projected by operator",
            std::move(warning),
        };
    }

    // Default policy: planar (including an explicit declared "planar").
    // Honest only when axes are known-projected.
    if (geographic_true) {
        const std::string warning =
            "CRS " + *crs +
            " is geographic (degree axes); interpolation distances "
            "treat degrees as planar metres. For large extents reproject to a "
            "projected CRS or declare distance_policy='planar_degrees'.";
        return DistancePolicy{
            kPolicyPlanarDegrees,
            *crs,
            true,
            "distance_policy=planar_degrees; geographic CRS " + *crs +
                " — degree-as-planar assumption APPLIED and recorded",
            warning,
        };
    }
    if (!geographic.has_value()) {
        return DistancePolicy{
            kPolicyPlanar,
            *crs,
            std::nullopt,
            "distance_policy=planar; CRS " + *crs +
                " axis units unverifiable (unknown id or pyproj unavailable) "
                "— planar assumption unconfirmed",
            "CRS " + *crs +
                " axis units could not be verified; distance "
                "policy applied without confirmation",
        };
    }
    return DistancePolicy{
        kPolicyPlanar,
        *crs,
        geographic,
        "distance_policy=planar; CRS " + *crs +
            " projected/verified planar metres",
        std::nullopt,
    };
}

}  // namespace pwb::mapping
