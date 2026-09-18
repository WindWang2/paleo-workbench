// Null policy, frozen against well_science.py.
#include <cmath>
#include <limits>

#include <pwb/well_science/null_policy.hpp>

namespace pwb::well_science {
namespace {
constexpr double kNan = std::numeric_limits<double>::quiet_NaN();

// numpy.isclose(a, b, rtol=0, atol=NULL_MATCH_ABS_TOL)
bool isclose_exact(double a, double b) {
    if (std::isfinite(a) && std::isfinite(b)) return std::fabs(a - b) <= NULL_MATCH_ABS_TOL;
    if (!std::isfinite(a) && !std::isfinite(b)) return a == b;  // equal non-finite
    return false;
}
}  // namespace

std::vector<unsigned char> NullPolicy::matches(const std::vector<double>& values) const {
    std::vector<unsigned char> mask(values.size(), 0);
    for (std::size_t i = 0; i < values.size(); ++i) {
        const double v = values[i];
        bool hit = false;
        if (sentinel) hit = hit || isclose_exact(v, *sentinel);
        for (double s : inferred_sentinels) hit = hit || isclose_exact(v, s);
        mask[i] = hit ? 1 : 0;
    }
    return mask;
}

NullPolicy null_policy_from_declared(std::optional<std::string> declared_sentinel) {
    if (!declared_sentinel || *declared_sentinel == "") return NullPolicy{"none"};
    try {
        std::size_t pos = 0;
        const double value = std::stod(*declared_sentinel, &pos);
        if (pos != declared_sentinel->size()) return NullPolicy{"none"};
        return NullPolicy{"declared", value, {}};
    } catch (const std::exception&) {
        return NullPolicy{"none"};
    }
}

}  // namespace pwb::well_science
