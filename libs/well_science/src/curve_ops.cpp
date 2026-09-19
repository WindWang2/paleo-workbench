// Curve-ops kernels frozen against the Python oracle
// (tools/oracle/generate_curve_ops_fixtures.py). Message texts and edge
// semantics replicate curve_operations.py / curve_interpretation.py exactly.
#include <algorithm>
#include <cctype>
#include <charconv>
#include <cmath>
#include <cstdlib>
#include <limits>
#include <numeric>
#include <stdexcept>
#include <string>
#include <string_view>
#include <tuple>
#include <vector>

#include <pwb/well_science/curve_ops.hpp>
#include <pwb/well_science/depth_unit.hpp>
#include <pwb/well_science/errors.hpp>

namespace pwb::well_science {
namespace {

constexpr double kFtToM = 0.3048;

// Python str(float): shortest round-trip digits, scientific notation only
// when the decimal exponent is < -4 or >= 16, exponent like "e+07"/"e-05".
std::string py_repr_double(double v) {
    if (std::isnan(v)) return "nan";
    if (std::isinf(v)) return v > 0 ? "inf" : "-inf";
    bool negative = std::signbit(v);
    if (negative) v = -v;
    if (v == 0.0) return negative ? "-0.0" : "0.0";
    char buf[64];
    auto res = std::to_chars(buf, buf + sizeof(buf), v, std::chars_format::scientific);
    std::string sci(buf, res.ptr);  // like "1.2345e+07" or "1e+07"
    const auto e_pos = sci.find('e');
    std::string digits = sci.substr(0, e_pos);
    const auto dot = digits.find('.');
    if (dot != std::string::npos) digits.erase(dot, 1);  // mantissa digits only
    const int exp10 = std::atoi(sci.c_str() + e_pos + 1);
    std::string body;
    if (exp10 >= 16 || exp10 < -4) {
        body = digits.substr(0, 1);
        if (digits.size() > 1) body += "." + digits.substr(1);
        body += "e" + (exp10 < 0 ? std::string("-") : std::string("+")) +
                (std::abs(exp10) < 10 ? "0" : "") + std::to_string(std::abs(exp10));
    } else if (exp10 >= 0) {
        if (static_cast<std::size_t>(exp10) + 1 >= digits.size()) {
            body = digits + std::string(static_cast<std::size_t>(exp10) + 1 - digits.size(), '0') + ".0";
        } else {
            body = digits.substr(0, static_cast<std::size_t>(exp10) + 1) + "." +
                   digits.substr(static_cast<std::size_t>(exp10) + 1);
        }
    } else {
        body = "0." + std::string(static_cast<std::size_t>(-exp10) - 1, '0') + digits;
    }
    return negative ? "-" + body : body;
}

bool is_finite(double v) { return std::isfinite(v); }

// numpy median: middle element, or mean of the two middle elements.
double numpy_median(std::vector<double> v) {
    std::sort(v.begin(), v.end());
    const std::size_t n = v.size();
    if (n == 0) return std::numeric_limits<double>::quiet_NaN();
    if (n % 2 == 1) return v[n / 2];
    return (v[n / 2 - 1] + v[n / 2]) / 2.0;
}

// numpy percentile (default linear interpolation), including the
// t >= 0.5 lerp branch (b - (b-a)*(1-t)) that numpy uses for rounding.
double numpy_percentile(std::vector<double> v, double q) {
    std::sort(v.begin(), v.end());
    const std::size_t n = v.size();
    if (n == 1) return v[0];
    const double pos = static_cast<double>(n - 1) * (q / 100.0);
    const auto lo = static_cast<std::size_t>(std::floor(pos));
    const auto hi = static_cast<std::size_t>(std::ceil(pos));
    if (lo == hi) return v[lo];
    const double t = pos - static_cast<double>(lo);
    const double a = v[lo];
    const double b = v[hi];
    return t >= 0.5 ? b - (b - a) * (1.0 - t) : a + (b - a) * t;
}

// np.interp with clamping at the ends (xs strictly increasing).
double np_interp(double qx, const std::vector<double>& xs, const std::vector<double>& ys) {
    if (std::isnan(qx)) return std::numeric_limits<double>::quiet_NaN();
    if (qx <= xs.front()) return ys.front();
    if (qx >= xs.back()) return ys.back();
    const auto it = std::upper_bound(xs.begin(), xs.end(), qx);
    const std::size_t i = static_cast<std::size_t>(it - xs.begin()) - 1;
    if (qx == xs[i]) return ys[i];
    const double t = (qx - xs[i]) / (xs[i + 1] - xs[i]);
    return ys[i] + t * (ys[i + 1] - ys[i]);
}

// Symmetric mirror index (scipy median_filter mode="reflect" boundary):
// ... a b c d | a b c d | a b c d ... — the edge sample is duplicated.
std::size_t reflect_index(long p, std::size_t n) {
    if (n == 1) return 0;
    while (p < 0 || p >= static_cast<long>(n)) {
        if (p < 0) p = -p - 1;
        else p = 2 * static_cast<long>(n) - 1 - p;
    }
    return static_cast<std::size_t>(p);
}

std::vector<unsigned char> finite_mask(const std::vector<double>& v) {
    std::vector<unsigned char> m(v.size());
    for (std::size_t i = 0; i < v.size(); ++i) m[i] = is_finite(v[i]) ? 1 : 0;
    return m;
}

constexpr double kNan = std::numeric_limits<double>::quiet_NaN();

}  // namespace

// ---------------------------------------------------------------------------
// Smoothing / filtering
// ---------------------------------------------------------------------------

std::vector<double> moving_average(const std::vector<double>& values, int window) {
    const std::size_t n = values.size();
    if (n == 0) return values;
    const long w = std::min<long>(std::max(1L, static_cast<long>(window)),
                                  static_cast<long>(n));
    if (w == 1) return values;
    const auto mask = finite_mask(values);
    bool any_finite = false;
    for (unsigned char f : mask) any_finite = any_finite || f;
    if (!any_finite) return values;

    // np.convolve(..., "same") window offsets: [i - ceil((w-1)/2), i + (w-1)/2]
    const long half = (w - 1) / 2;        // floor
    const long lead = (w - 1) - half;     // ceil
    std::vector<double> out(n, kNan);
    for (std::size_t i = 0; i < n; ++i) {
        double sum = 0.0, count = 0.0;
        for (long j = static_cast<long>(i) - lead; j <= static_cast<long>(i) + half; ++j) {
            if (j < 0 || j >= static_cast<long>(n)) continue;  // conv zero padding
            if (mask[static_cast<std::size_t>(j)]) {
                sum += values[static_cast<std::size_t>(j)];
                count += 1.0;
            }
        }
        if (count > 0) out[i] = sum / count;
        if (!mask[i]) out[i] = kNan;
    }
    return out;
}

std::vector<double> median_filter_curve(const std::vector<double>& values, int window) {
    const std::size_t n = values.size();
    const auto mask = finite_mask(values);
    bool any_finite = false;
    for (unsigned char f : mask) any_finite = any_finite || f;
    if (n == 0 || !any_finite) return values;

    const int w = std::max(1, static_cast<int>(window) | 1);
    std::vector<double> finite_only;
    finite_only.reserve(n);
    for (std::size_t i = 0; i < n; ++i)
        if (mask[i]) finite_only.push_back(values[i]);
    const double fill = numpy_median(finite_only);

    std::vector<double> filled(n);
    for (std::size_t i = 0; i < n; ++i) filled[i] = mask[i] ? values[i] : fill;

    const long half = (w - 1) / 2;
    std::vector<double> out(n, kNan);
    std::vector<double> win(static_cast<std::size_t>(w));
    for (std::size_t i = 0; i < n; ++i) {
        for (long k = -half; k <= half; ++k)
            win[static_cast<std::size_t>(k + half)] =
                filled[reflect_index(static_cast<long>(i) + k, n)];
        out[i] = numpy_median(win);
    }
    for (std::size_t i = 0; i < n; ++i)
        if (!mask[i]) out[i] = kNan;
    return out;
}

// ---------------------------------------------------------------------------
// Normalization / outlier handling
// ---------------------------------------------------------------------------

std::vector<double> normalize_curve(const std::vector<double>& values,
                                    const std::string& method) {
    const auto mask = finite_mask(values);
    std::vector<double> out(values.size(), kNan);
    std::vector<double> data;
    for (std::size_t i = 0; i < values.size(); ++i)
        if (mask[i]) data.push_back(values[i]);
    if (data.empty()) return out;
    if (method == "zscore") {
        const double mean = std::accumulate(data.begin(), data.end(), 0.0) /
                            static_cast<double>(data.size());
        double sq = 0.0;
        for (double v : data) sq += (v - mean) * (v - mean);
        const double var = sq / static_cast<double>(data.size());
        const double std = std::sqrt(var);
        const double denom = std > 1e-12 ? std : 1.0;
        for (std::size_t i = 0; i < values.size(); ++i)
            if (mask[i]) out[i] = (values[i] - mean) / denom;
        return out;
    }
    if (method == "minmax") {
        const auto [lo_it, hi_it] = std::minmax_element(data.begin(), data.end());
        const double lo = *lo_it, hi = *hi_it;
        const double span = hi - lo;
        for (std::size_t i = 0; i < values.size(); ++i)
            if (mask[i]) out[i] = span <= 1e-12 ? 0.5 : (values[i] - lo) / span;
        return out;
    }
    throw CurveOpError("unknown normalization method '" + method + "' (zscore|minmax)");
}

std::vector<double> clip_outliers(const std::vector<double>& values,
                                  std::optional<double> lower,
                                  std::optional<double> upper,
                                  std::optional<double> percentile) {
    const auto mask = finite_mask(values);
    bool any_finite = false;
    for (unsigned char f : mask) any_finite = any_finite || f;
    if (!any_finite) return values;
    std::optional<double> lo = lower, hi = upper;
    if (percentile) {
        const double p = *percentile;
        if (!(p > 0.0 && p < 50.0))
            throw CurveOpError("percentile must be in (0, 50), got " + py_repr_double(p));
        std::vector<double> data;
        for (std::size_t i = 0; i < values.size(); ++i)
            if (mask[i]) data.push_back(values[i]);
        lo = numpy_percentile(data, p);
        hi = numpy_percentile(data, 100.0 - p);
    }
    if (!lo && !hi)
        throw CurveOpError("clip_outliers needs lower/upper bounds or a percentile");
    std::vector<double> out = values;
    const auto np_max = [](double a, double b) {
        if (std::isnan(a)) return a;
        if (std::isnan(b)) return b;
        return a < b ? b : a;
    };
    const auto np_min = [](double a, double b) {
        if (std::isnan(a)) return a;
        if (std::isnan(b)) return b;
        return a > b ? b : a;
    };
    for (std::size_t i = 0; i < out.size(); ++i) {
        if (!mask[i]) continue;
        // np.maximum/np.minimum semantics: a NaN bound propagates.
        if (lo) out[i] = np_max(out[i], *lo);
        if (hi) out[i] = np_min(out[i], *hi);
    }
    return out;
}

// ---------------------------------------------------------------------------
// Unit conversion (explicit whitelist)
// ---------------------------------------------------------------------------

std::optional<std::string> normalize_unit_name(std::optional<std::string> unit) {
    using namespace std::string_view_literals;
    static const std::vector<std::pair<std::string_view, std::string_view>> kAliases = {
        {"m"sv, "m"sv}, {"meter"sv, "m"sv}, {"meters"sv, "m"sv},
        {"metre"sv, "m"sv}, {"metres"sv, "m"sv},
        {"ft"sv, "ft"sv}, {"feet"sv, "ft"sv}, {"foot"sv, "ft"sv}, {"f"sv, "ft"sv},
        {"g/cc"sv, "g/cc"sv}, {"g/cm3"sv, "g/cc"sv}, {"g/cm\xC2\xB3"sv, "g/cc"sv},
        {"gm/cc"sv, "g/cc"sv},
        {"kg/m3"sv, "kg/m3"sv}, {"kg/m\xC2\xB3"sv, "kg/m3"sv},
        {"us/m"sv, "us/m"sv}, {"\xC2\xB5s/m"sv, "us/m"sv},
        {"us/ft"sv, "us/ft"sv}, {"\xC2\xB5s/ft"sv, "us/ft"sv},
        {"mm"sv, "mm"sv}, {"in"sv, "in"sv}, {"inch"sv, "in"sv}, {"inches"sv, "in"sv},
        {"mv"sv, "mv"sv}, {"millivolt"sv, "mv"sv}, {"v"sv, "v"sv}, {"volt"sv, "v"sv},
        {"ohmm"sv, "ohmm"sv}, {"ohm.m"sv, "ohmm"sv}, {"ohmm.m"sv, "ohmm"sv},
        {"ohm-m"sv, "ohmm"sv},
        {"%"sv, "percent"sv}, {"pct"sv, "percent"sv}, {"v/v"sv, "v/v"sv},
        {"api"sv, "api"sv},
    };
    if (!unit) return std::nullopt;
    std::string key = std::move(*unit);
    std::size_t b = 0, e = key.size();
    while (b < e && std::isspace(static_cast<unsigned char>(key[b]))) ++b;
    while (e > b && std::isspace(static_cast<unsigned char>(key[e - 1]))) --e;
    key = key.substr(b, e - b);
    std::transform(key.begin(), key.end(), key.begin(), [](unsigned char c) {
        return c >= 'A' && c <= 'Z' ? static_cast<char>(c - 'A' + 'a') : c;
    });
    for (const auto& [alias, canonical] : kAliases)
        if (key == alias) return std::string(canonical);
    return std::nullopt;
}

double conversion_factor(std::optional<std::string> from_unit,
                         std::optional<std::string> to_unit) {
    using namespace std::string_view_literals;
    // (from, to) -> multiplicative factor applied to VALUES.
    static const std::vector<std::tuple<std::string_view, std::string_view, double>> kPairs = {
        {"m"sv, "ft"sv, 1.0 / kFtToM},
        {"ft"sv, "m"sv, kFtToM},
        {"g/cc"sv, "kg/m3"sv, 1000.0},
        {"kg/m3"sv, "g/cc"sv, 0.001},
        {"us/m"sv, "us/ft"sv, kFtToM},
        {"us/ft"sv, "us/m"sv, 1.0 / kFtToM},
        {"mm"sv, "in"sv, 1.0 / 25.4},
        {"in"sv, "mm"sv, 25.4},
        {"mv"sv, "v"sv, 0.001},
        {"v"sv, "mv"sv, 1000.0},
        {"percent"sv, "v/v"sv, 0.01},
        {"v/v"sv, "percent"sv, 100.0},
    };

    // keep the originals for the frozen error text (repr: None → "None")
    // repr() in the frozen text: strings get quotes, None does not.
    const std::string from_repr = from_unit ? "'" + *from_unit + "'" : "None";
    const std::string to_repr = to_unit ? "'" + *to_unit + "'" : "None";
    const auto src = normalize_unit_name(std::move(from_unit));
    const auto dst = normalize_unit_name(std::move(to_unit));
    if (!src || !dst) {
        // sorted(set(_UNIT_ALIASES)) — byte order == codepoint order here.
        static const char* kSorted =
            "['%', 'api', 'f', 'feet', 'foot', 'ft', 'g/cc', 'g/cm3', 'g/cm\xC2\xB3', "
            "'gm/cc', 'in', 'inch', 'inches', 'kg/m3', 'kg/m\xC2\xB3', 'm', 'meter', "
            "'meters', 'metre', 'metres', 'millivolt', 'mm', 'mv', 'ohm-m', 'ohm.m', "
            "'ohmm', 'ohmm.m', 'pct', 'us/ft', 'us/m', 'v', 'v/v', 'volt', "
            "'\xC2\xB5s/ft', '\xC2\xB5s/m']";
        throw CurveOpError("unrecognized unit (" + from_repr + " -> " + to_repr +
                           "); supported: " + kSorted);
    }
    if (*src == *dst) return 1.0;
    for (const auto& [a, b, factor] : kPairs)
        if (a == *src && b == *dst) return factor;
    // sorted(UNIT_CONVERSIONS) — tuple lexicographic == byte order here.
    static const char* kSortedPairs =
        "[('ft', 'm'), ('g/cc', 'kg/m3'), ('in', 'mm'), ('kg/m3', 'g/cc'), "
        "('m', 'ft'), ('mm', 'in'), ('mv', 'v'), ('percent', 'v/v'), "
        "('us/ft', 'us/m'), ('us/m', 'us/ft'), ('v', 'mv'), ('v/v', 'percent')]";
    throw CurveOpError("no whitelisted conversion " + from_repr + " -> " + to_repr +
                       "; supported pairs: " + kSortedPairs);
}

std::vector<double> convert_values(const std::vector<double>& values,
                                   std::optional<std::string> from_unit,
                                   std::optional<std::string> to_unit) {
    const double factor = conversion_factor(std::move(from_unit), std::move(to_unit));
    std::vector<double> out = values;
    for (double& v : out)
        if (is_finite(v)) v = v * factor;
    return out;
}

// ---------------------------------------------------------------------------
// Resampling
// ---------------------------------------------------------------------------

std::vector<double> resample_axis(const std::vector<double>& depth, double step) {
    if (depth.size() < 2) return depth;
    const double step_val = step;
    if (!is_finite(step_val) || step_val <= 0.0)
        throw CurveOpError("resample step must be positive, got " + py_repr_double(step_val));
    if (depth.back() < depth.front())
        throw CurveOpError("resample needs a non-descending depth axis (got " +
                           py_repr_double(depth.front()) + " \xE2\x86\x92 " +
                           py_repr_double(depth.back()) +
                           "); reverse the axis explicitly first");
    const double start = depth.front(), stop = depth.back();
    const double ratio = (stop - start) / step_val;
    if (!is_finite(ratio))
        throw CurveOpError("resample axis span is not finite for step " +
                           py_repr_double(step_val));
    const long count = static_cast<long>(std::floor(ratio + 1e-9)) + 1;
    std::vector<double> out(static_cast<std::size_t>(count));
    for (long i = 0; i < count; ++i)
        out[static_cast<std::size_t>(i)] = start + static_cast<double>(i) * step_val;
    return out;
}

std::vector<double> interp_nan_aware(const std::vector<double>& new_x,
                                     const std::vector<double>& x,
                                     const std::vector<double>& y) {
    if (x.size() != y.size())
        throw CurveOpError("interp_nan_aware needs x and y of equal length (got " +
                           std::to_string(x.size()) + " and " +
                           std::to_string(y.size()) + ")");
    std::vector<double> out(new_x.size(), kNan);
    std::vector<std::pair<double, double>> pts;  // (x, y) of finite samples
    for (std::size_t i = 0; i < x.size(); ++i)
        if (is_finite(x[i]) && is_finite(y[i])) pts.emplace_back(x[i], y[i]);
    if (pts.empty()) return out;
    std::stable_sort(pts.begin(), pts.end(),
                     [](const auto& a, const auto& b) { return a.first < b.first; });
    std::vector<double> xs, ys;
    for (const auto& [xi, yi] : pts) {
        if (!xs.empty() && xs.back() == xi) continue;  // duplicate depth: keep first
        xs.push_back(xi);
        ys.push_back(yi);
    }
    for (std::size_t i = 0; i < new_x.size(); ++i) {
        const double q = new_x[i];
        if (q < xs.front() || q > xs.back()) continue;  // outside hull → NaN
        out[i] = np_interp(q, xs, ys);
    }
    return out;
}

std::vector<double> interp_gap_preserving(const std::vector<double>& new_x,
                                          const std::vector<double>& x,
                                          const std::vector<double>& y) {
    if (x.size() != y.size())
        throw CurveOpError("interp_gap_preserving needs x and y of equal length (got " +
                           std::to_string(x.size()) + " and " +
                           std::to_string(y.size()) + ")");
    std::vector<double> out(new_x.size(), kNan);
    // Refuse loudly on descending finite axes (review R3-P2).
    double first_finite_x = kNan, last_finite_x = kNan;
    bool seen = false;
    for (double v : x) {
        if (!is_finite(v)) continue;
        if (!seen) {
            first_finite_x = v;
            seen = true;
        }
        last_finite_x = v;
    }
    if (seen && last_finite_x < first_finite_x)
        throw CurveOpError(
            "interp_gap_preserving needs a non-descending depth axis; "
            "reverse the axis explicitly first");

    // Contiguous finite runs (index-consecutive in the ORIGINAL arrays).
    const std::size_t n = x.size();
    std::vector<std::pair<long, long>> runs;
    long run_start = -1;
    for (std::size_t i = 0; i < n; ++i) {
        const bool ok = is_finite(x[i]) && is_finite(y[i]);
        if (ok && run_start < 0) run_start = static_cast<long>(i);
        if (!ok && run_start >= 0) {
            runs.emplace_back(run_start, static_cast<long>(i) - 1);
            run_start = -1;
        }
    }
    if (run_start >= 0) runs.emplace_back(run_start, static_cast<long>(n) - 1);

    std::vector<std::pair<double, double>> seg;
    std::vector<double> sx, sy;
    for (const auto& [s, e] : runs) {
        // Segment mask: new_x within [x[s], x[e]] (NaN queries never match).
        std::vector<std::size_t> hit;
        for (std::size_t i = 0; i < new_x.size(); ++i)
            if (new_x[i] >= x[static_cast<std::size_t>(s)] &&
                new_x[i] <= x[static_cast<std::size_t>(e)])
                hit.push_back(i);
        if (hit.empty()) continue;
        seg.clear();
        for (long j = s; j <= e; ++j) seg.emplace_back(x[static_cast<std::size_t>(j)],
                                                       y[static_cast<std::size_t>(j)]);
        std::stable_sort(seg.begin(), seg.end(),
                         [](const auto& a, const auto& b) { return a.first < b.first; });
        sx.clear();
        sy.clear();
        for (const auto& [xi, yi] : seg) {
            if (!sx.empty() && sx.back() == xi) continue;  // keep first
            sx.push_back(xi);
            sy.push_back(yi);
        }
        for (std::size_t i : hit) out[i] = np_interp(new_x[i], sx, sy);
    }
    return out;
}

// ---------------------------------------------------------------------------
// Missing-interval diagnostics
// ---------------------------------------------------------------------------

MissingIntervalReport missing_interval_report(const std::vector<double>& depth,
                                              const std::vector<double>& values) {
    if (depth.size() != values.size())
        throw CurveOpError(
            "missing_interval_report needs depth and values of equal length (got " +
            std::to_string(depth.size()) + " and " + std::to_string(values.size()) + ")");
    const auto mask = finite_mask(values);
    MissingIntervalReport rep;
    rep.total_samples = static_cast<long>(values.size());
    for (unsigned char f : mask)
        if (!f) ++rep.missing_samples;

    std::vector<unsigned char> ok(values.size());
    for (std::size_t i = 0; i < values.size(); ++i)
        ok[i] = mask[i] && is_finite(depth[i]) ? 1 : 0;
    bool any_ok = false;
    for (unsigned char f : ok) any_ok = any_ok || f;
    if (any_ok && rep.total_samples > 2) {
        std::size_t first = 0, last = 0;
        for (std::size_t i = 0; i < ok.size(); ++i)
            if (ok[i]) { first = i; break; }
        for (std::size_t i = ok.size(); i-- > 0;)
            if (ok[i]) { last = i; break; }
        long run_start = -1;
        for (std::size_t i = first; i <= last; ++i) {
            const bool bad = !ok[i];
            if (bad && run_start < 0) run_start = static_cast<long>(i);
            if (!bad && run_start >= 0) {
                rep.intervals.emplace_back(depth[static_cast<std::size_t>(run_start)],
                                           depth[i - 1]);
                run_start = -1;
            }
        }
    }
    return rep;
}

// ---------------------------------------------------------------------------
// curve_interpretation.py pure kernels
// ---------------------------------------------------------------------------

std::vector<double> depth_shift(const std::vector<double>& depths, double delta_m,
                                std::optional<std::string> axis_unit) {
    const std::string unit = require_depth_unit(std::move(axis_unit), "depth_shift");
    double delta_axis = delta_m;
    if (unit == "ft") delta_axis *= conversion_factor(std::string("m"), std::string("ft"));
    std::vector<double> out = depths;
    for (double& v : out) v = v + delta_axis;
    return out;
}

std::vector<double> despike(const std::vector<double>& values, double threshold_sigma,
                            int window) {
    std::vector<double> arr = values;
    const std::size_t n = arr.size();
    if (n == 0) return arr;
    const auto mask = finite_mask(arr);
    bool any_finite = false;
    for (unsigned char f : mask) any_finite = any_finite || f;
    if (!any_finite) return arr;

    const int w = std::max(1, static_cast<int>(window) | 1);
    std::vector<double> finite_vals;
    std::vector<double> non_nan_vals;
    for (std::size_t i = 0; i < n; ++i) {
        if (mask[i]) finite_vals.push_back(arr[i]);
        // np.nanmedian(arr) drops NaN alone — ±inf keeps its sorted slot.
        // finite_vals stays finite-only for np.ptp(arr[finite]) below.
        if (!std::isnan(arr[i])) non_nan_vals.push_back(arr[i]);
    }
    const double nan_median = numpy_median(std::move(non_nan_vals));
    std::vector<double> filled(n);
    for (std::size_t i = 0; i < n; ++i) filled[i] = mask[i] ? arr[i] : nan_median;

    const long half = (w - 1) / 2;
    std::vector<double> baseline(n);
    std::vector<double> win(static_cast<std::size_t>(w));
    for (std::size_t i = 0; i < n; ++i) {
        for (long k = -half; k <= half; ++k)
            win[static_cast<std::size_t>(k + half)] =
                filled[reflect_index(static_cast<long>(i) + k, n)];
        baseline[i] = numpy_median(win);
    }

    std::vector<double> residual(n);
    for (std::size_t i = 0; i < n; ++i) residual[i] = arr[i] - baseline[i];
    std::vector<double> residual_finite;
    for (std::size_t i = 0; i < n; ++i)
        if (mask[i]) residual_finite.push_back(residual[i]);
    const double med_res = numpy_median(residual_finite);
    std::vector<double> abs_dev(residual_finite.size());
    for (std::size_t i = 0; i < residual_finite.size(); ++i)
        abs_dev[i] = std::fabs(residual_finite[i] - med_res);
    const double mad = numpy_median(abs_dev);
    double spread_floor = 1.0;
    if (finite_vals.size() > 1) {
        const auto [lo_it, hi_it] = std::minmax_element(finite_vals.begin(),
                                                        finite_vals.end());
        spread_floor = 0.01 * (*hi_it - *lo_it);
    }
    const double spread = std::max({1.4826 * mad, spread_floor, 1e-9});
    for (std::size_t i = 0; i < n; ++i)
        if (std::fabs(residual[i]) > threshold_sigma * spread) arr[i] = baseline[i];
    return arr;
}

std::vector<double> baseline_shift(const std::vector<double>& values, double delta) {
    std::vector<double> out = values;
    for (double& v : out) v = v + delta;
    return out;
}

const std::vector<CurveOperationInfo>& curve_operations() {
    static const std::vector<CurveOperationInfo> kRegistry = {
        {"depth_shift", {"delta_m"}, "depth_axis"},
        {"despike", {}, "curve"},
        {"baseline_shift", {"delta"}, "curve"},
        {"smooth", {"window"}, "curve"},
        {"median_filter", {"window"}, "curve"},
        {"normalize", {}, "curve"},
        {"clip_outliers", {}, "curve"},
        {"unit_conversion", {"from_unit", "to_unit"}, "curve"},
        {"resample", {"step"}, "file"},
        {"depth_unit_normalize", {"target_unit"}, "file"},
        {"derive_curve", {"expression", "result_mnemonic"}, "derive"},
    };
    return kRegistry;
}

}  // namespace pwb::well_science
