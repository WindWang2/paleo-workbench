// CONV-27 — implementation of the scalar style spec + classification.
// See scalar_style.hpp and numpy_math.hpp for the ported semantics.
#include <pwb/cartography/scalar_style.hpp>

#include "numpy_math.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <limits>
#include <set>
#include <stdexcept>
#include <string>

namespace pwb::cartography {

std::string format_fixed(double value, int decimals) {
    // Python f"{v:.{d}f}": nan (any sign) -> "nan"; inf -> "inf"/"-inf";
    // otherwise printf-style fixed with round-half-even on the decimal
    // digit (matches glibc for the doubles involved).
    if (std::isnan(value)) return "nan";
    char buf[512];
    std::snprintf(buf, sizeof(buf), "%.*f", decimals, value);
    return buf;
}

namespace {

std::vector<std::string> format_labels(const std::vector<double>& breaks,
                                       int decimals) {
    std::vector<std::string> labels;
    labels.reserve(breaks.size());
    for (double v : breaks) labels.push_back(format_fixed(v, decimals));
    return labels;
}

std::string py_repr(const std::string& text) { return "'" + text + "'"; }

}  // namespace

void ScalarStyleSpec::validate() const {
    static const char* kModes[] = {"continuous", "classified"};
    static const char* kClassifications[] = {"equal_interval", "quantile",
                                             "natural_breaks", "explicit"};
    if (mode != kModes[0] && mode != kModes[1]) {
        throw std::invalid_argument(
            "mode must be one of ('continuous', 'classified'), got " +
            py_repr(mode));
    }
    bool known_classification = false;
    for (const char* c : kClassifications) {
        if (classification == c) known_classification = true;
    }
    if (!known_classification) {
        throw std::invalid_argument(
            "classification must be one of ('equal_interval', 'quantile', "
            "'natural_breaks', 'explicit'), got " +
            py_repr(classification));
    }
    if (n_classes < 2) throw std::invalid_argument("n_classes must be >= 2");
    if (n_classes > 256) {
        throw std::invalid_argument("n_classes must be <= 256");
    }
    if (!(opacity >= 0.0 && opacity <= 1.0)) {
        throw std::invalid_argument("opacity must be within [0, 1]");
    }
    if (manual_range.has_value()) {
        if (!(manual_range->second > manual_range->first)) {
            throw std::invalid_argument("manual_range needs hi > lo");
        }
    }
    if (classification == "explicit") {
        if (!explicit_breaks.has_value() || explicit_breaks->empty()) {
            throw std::invalid_argument(
                "explicit classification requires explicit_breaks");
        }
        // R3-5: strictly increasing.
        for (std::size_t i = 1; i < explicit_breaks->size(); ++i) {
            if ((*explicit_breaks)[i] <= (*explicit_breaks)[i - 1]) {
                throw std::invalid_argument(
                    "explicit_breaks must be strictly increasing");
            }
        }
    }
}

Json ScalarStyleSpec::to_dict() const {
    Json data = Json::object();
    data["ramp_name"] = ramp_name;
    data["mode"] = mode;
    data["classification"] = classification;
    data["n_classes"] = n_classes;
    data["reverse"] = reverse;
    data["opacity"] = opacity;
    data["nodata_transparent"] = nodata_transparent;
    data["unit_label"] = unit_label;
    data["colorbar_title"] = colorbar_title;
    data["colorbar_decimals"] = colorbar_decimals;
    if (explicit_breaks.has_value()) {
        Json rows = Json::array();
        for (double v : *explicit_breaks) rows.push_back(v);
        data["explicit_breaks"] = std::move(rows);
    }
    if (manual_range.has_value()) {
        Json rows = Json::array();
        rows.push_back(manual_range->first);
        rows.push_back(manual_range->second);
        data["manual_range"] = std::move(rows);
    }
    return data;
}

ScalarStyleSpec ScalarStyleSpec::from_dict(const Json& data) {
    ScalarStyleSpec spec;
    if (!data.is_object()) return spec;
    // str()/float()/int()/bool() coercions mirroring the Python from_dict.
    auto py_str = [](const Json& value) -> std::string {
        if (value.is_string()) return value.get<std::string>();
        if (value.is_boolean()) return value.get<bool>() ? "True" : "False";
        if (value.is_number_integer()) {
            return std::to_string(value.get<long long>());
        }
        if (value.is_number_float()) {
            char buf[40];
            std::snprintf(buf, sizeof(buf), "%g", value.get<double>());
            return buf;
        }
        return value.dump();
    };
    auto py_double = [](const Json& value) -> double {
        if (value.is_number()) {
            return value.is_number_integer()
                       ? static_cast<double>(value.get<long long>())
                       : value.get<double>();
        }
        if (value.is_boolean()) return value.get<bool>() ? 1.0 : 0.0;
        if (value.is_string()) {
            const std::string text = value.get<std::string>();
            std::size_t consumed = 0;
            double parsed = 0.0;
            try {
                parsed = std::stod(text, &consumed);
            } catch (const std::exception&) {
                throw std::invalid_argument(
                    "could not convert string to float: " + text);
            }
            while (consumed < text.size() &&
                   std::isspace(static_cast<unsigned char>(text[consumed]))) {
                ++consumed;
            }
            if (consumed != text.size()) {
                throw std::invalid_argument(
                    "could not convert string to float: " + text);
            }
            return parsed;
        }
        throw std::invalid_argument("float() argument must be a number");
    };
    auto py_long = [](const Json& value) -> long long {
        if (value.is_number_integer()) return value.get<long long>();
        if (value.is_boolean()) return value.get<bool>() ? 1 : 0;
        if (value.is_number_float()) {
            return static_cast<long long>(value.get<double>());  // int() trunc
        }
        if (value.is_string()) {
            const std::string text = value.get<std::string>();
            try {
                std::size_t consumed = 0;
                long long parsed = std::stoll(text, &consumed);
                while (consumed < text.size() &&
                       std::isspace(static_cast<unsigned char>(
                           text[consumed]))) {
                    ++consumed;
                }
                if (consumed != text.size()) throw std::invalid_argument(text);
                return parsed;
            } catch (const std::exception&) {
                throw std::invalid_argument(
                    "invalid literal for int() with base 10: '" + text + "'");
            }
        }
        throw std::invalid_argument("int() argument must be a number");
    };
    auto truthy = [](const Json& value) {
        if (value.is_string()) return !value.get<std::string>().empty();
        if (value.is_boolean()) return value.get<bool>();
        if (value.is_number_integer()) return value.get<long long>() != 0;
        if (value.is_number_float()) return value.get<double>() != 0.0;
        return true;
    };
    auto get = [&data](const char* key) { return data.find(key); };
    if (auto it = get("ramp_name"); it != data.end() && !it->is_null()) {
        spec.ramp_name = py_str(*it);
    }
    if (auto it = get("mode"); it != data.end() && !it->is_null()) {
        spec.mode = py_str(*it);
    }
    if (auto it = get("classification"); it != data.end() && !it->is_null()) {
        spec.classification = py_str(*it);
    }
    if (auto it = get("n_classes"); it != data.end() && !it->is_null()) {
        spec.n_classes = py_long(*it);
    }
    if (auto it = get("explicit_breaks");
        it != data.end() && it->is_array() && !it->empty()) {
        std::vector<double> breaks;
        for (const Json& v : *it) breaks.push_back(py_double(v));
        spec.explicit_breaks = std::move(breaks);
    }
    if (auto it = get("manual_range");
        it != data.end() && it->is_array() && it->size() == 2) {
        spec.manual_range = std::make_pair(py_double((*it)[0]),
                                           py_double((*it)[1]));
    }
    if (auto it = get("reverse"); it != data.end() && !it->is_null()) {
        spec.reverse = truthy(*it);
    }
    if (auto it = get("opacity"); it != data.end() && !it->is_null()) {
        spec.opacity = py_double(*it);
    }
    if (auto it = get("nodata_transparent");
        it != data.end() && !it->is_null()) {
        spec.nodata_transparent = truthy(*it);
    }
    if (auto it = get("unit_label"); it != data.end() && !it->is_null()) {
        spec.unit_label = py_str(*it);
    }
    if (auto it = get("colorbar_title"); it != data.end() && !it->is_null()) {
        spec.colorbar_title = py_str(*it);
    }
    if (auto it = get("colorbar_decimals");
        it != data.end() && !it->is_null()) {
        spec.colorbar_decimals = static_cast<int>(py_long(*it));
    }
    // Python from_dict constructs through __post_init__: invalid payloads
    // raise instead of silently persisting (R3-5 guard).
    spec.validate();
    return spec;
}

std::vector<double> finite_values(const std::vector<double>& values) {
    std::vector<double> out;
    out.reserve(values.size());
    for (double v : values) {
        if (std::isfinite(v)) out.push_back(v);
    }
    return out;
}

ClassifiedBreaks equal_interval_breaks(double vmin, double vmax, long long n,
                                       int decimals) {
    // np.linspace(start, stop, num): step = delta / div;
    // y[i] = i * step + start; endpoint forced to stop.
    const double step = (vmax - vmin) / static_cast<double>(n);
    ClassifiedBreaks out;
    out.breaks.reserve(static_cast<std::size_t>(n) + 1);
    for (long long i = 0; i < n; ++i) {
        out.breaks.push_back(static_cast<double>(i) * step + vmin);
    }
    out.breaks.push_back(vmax);
    out.labels = format_labels(out.breaks, decimals);
    return out;
}

ClassifiedBreaks quantile_breaks(const std::vector<double>& values,
                                 long long n, int decimals) {
    std::vector<double> finite = finite_values(values);
    if (finite.empty()) {
        throw std::invalid_argument(
            "quantile classification needs at least one finite value");
    }
    std::sort(finite.begin(), finite.end());
    const double count = static_cast<double>(finite.size());
    auto quantile = [&](double q) {
        // np.quantile 'linear': virtual index h = (n-1)*q with the
        // two-branch numpy _lerp (t >= 0.5 computes from the b end).
        const double h = (count - 1.0) * q;
        const double floor_h = std::floor(h);
        const std::size_t a = static_cast<std::size_t>(floor_h);
        if (a + 1 >= finite.size()) return finite.back();
        const double t = h - floor_h;
        const double va = finite[a];
        const double vb = finite[a + 1];
        const double diff = vb - va;
        if (t >= 0.5) {
            // numpy: lerp(b, a, 1-t) = b - diff * (1 - t)
            return vb - diff * (1.0 - t);
        }
        return va + diff * t;
    };
    ClassifiedBreaks out;
    const double q_step = 1.0 / static_cast<double>(n);  // np.linspace(0,1,n+1)
    for (long long i = 0; i <= n; ++i) {
        const double q = static_cast<double>(i) * q_step;
        out.breaks.push_back(quantile(q));
    }
    // Enforce strict monotonicity (flat distributions collapse quantiles).
    for (std::size_t index = 1; index < out.breaks.size(); ++index) {
        if (out.breaks[index] <= out.breaks[index - 1]) {
            out.breaks[index] = out.breaks[index - 1];
        }
    }
    out.labels = format_labels(out.breaks, decimals);
    return out;
}

ClassifiedBreaks natural_breaks_from_values(const std::vector<double>& finite,
                                            long long n, int decimals) {
    if (finite.empty()) {
        throw std::invalid_argument("natural breaks need at least one finite value");
    }
    std::vector<double> data = finite;
    std::sort(data.begin(), data.end());
    ClassifiedBreaks out;
    if (static_cast<long long>(data.size()) <= n) {
        out.breaks = data;
        if (!data.empty()) out.breaks.push_back(data.back());
        out.labels = format_labels(out.breaks, decimals);
        return out;
    }
    const std::size_t count = data.size();
    const std::size_t k = static_cast<std::size_t>(n);
    // matrix[k+1][count+1], pivot[k+1][count+1] — identical layout to the
    // Python DP so pivot reconstruction follows the same path.
    std::vector<std::vector<double>> matrix(k + 1,
                                            std::vector<double>(count + 1, 0.0));
    std::vector<std::vector<std::size_t>> pivot(
        k + 1, std::vector<std::size_t>(count + 1, 0));
    for (std::size_t i = 1; i <= count; ++i) matrix[1][i] = std::numeric_limits<double>::infinity();
    for (std::size_t classes = 2; classes <= k; ++classes) {
        for (std::size_t end = classes; end <= count; ++end) {
            double best = std::numeric_limits<double>::infinity();
            std::size_t best_split = classes - 1;
            for (std::size_t split = classes - 1; split < end; ++split) {
                const double* seg = data.data() + split;
                const std::size_t len = end - split;
                const double s = numpy_math::pairwise_sum(seg, len);
                // (seg * seg).sum(): square elementwise, then pairwise.
                std::vector<double> squared(len);
                for (std::size_t i = 0; i < len; ++i) squared[i] = seg[i] * seg[i];
                const double sq = numpy_math::pairwise_sum(squared.data(), len);
                const double variance =
                    sq - (s * s) / static_cast<double>(len);
                const double candidate =
                    matrix[classes - 1][split] + variance;
                if (candidate < best) {
                    best = candidate;
                    best_split = split;
                }
            }
            matrix[classes][end] = best;
            pivot[classes][end] = best_split;
        }
    }
    // Reconstruct class boundaries from the pivot table.
    std::vector<std::size_t> boundaries(k + 1, 0);
    boundaries[k] = count;
    std::size_t end = count;
    for (std::size_t classes = k; classes > 1; --classes) {
        end = pivot[classes][end];
        boundaries[classes - 1] = end;
    }
    std::set<double> unique;
    for (std::size_t i = 0; i < k; ++i) {
        const std::size_t boundary = boundaries[i];
        unique.insert(boundary > 0 ? data[boundary - 1] : data[0]);
    }
    unique.insert(data.back());
    out.breaks.assign(unique.begin(), unique.end());
    out.labels = format_labels(out.breaks, decimals);
    return out;
}

ClassifiedBreaks natural_breaks(const std::vector<double>& values,
                                long long n, long long sample,
                                long long seed, int decimals) {
    std::vector<double> finite = finite_values(values);
    if (finite.empty()) {
        throw std::invalid_argument("natural breaks need at least one finite value");
    }
    if (static_cast<long long>(finite.size()) > sample) {
        // default_rng(seed).choice(finite, size=sample, replace=False):
        // Floyd's variant over the population indices (numpy stream
        // contract, see numpy_math.hpp).
        numpy_math::Pcg64 rng = numpy_math::Pcg64::seeded(
            static_cast<std::uint64_t>(seed));
        std::vector<std::size_t> indices =
            numpy_math::choice_indices_without_replacement(
                rng, finite.size(), static_cast<std::size_t>(sample));
        std::vector<double> drawn;
        drawn.reserve(indices.size());
        for (std::size_t index : indices) drawn.push_back(finite[index]);
        return natural_breaks_from_values(std::move(drawn), n, decimals);
    }
    return natural_breaks_from_values(std::move(finite), n, decimals);
}

ClassifiedBreaks classify_breaks(const ScalarStyleSpec& spec,
                                 const std::vector<double>& values,
                                 double vmin, double vmax,
                                 std::optional<long long> n) {
    // Python: classes = int(n or spec.n_classes) — a falsy n falls back.
    const long long classes =
        (n.has_value() && *n != 0) ? *n : spec.n_classes;
    if (spec.manual_range.has_value()) {
        vmin = spec.manual_range->first;
        vmax = spec.manual_range->second;
    }
    if (spec.classification == "explicit") {
        ClassifiedBreaks out;
        out.breaks = spec.explicit_breaks.value_or(std::vector<double>{});
        if (out.breaks.size() < 2) {
            throw std::invalid_argument("explicit_breaks needs at least two values");
        }
        out.labels = format_labels(out.breaks, spec.colorbar_decimals);
        return out;
    }
    if (spec.classification == "equal_interval") {
        return equal_interval_breaks(vmin, vmax, classes,
                                     spec.colorbar_decimals);
    }
    if (spec.classification == "quantile") {
        return quantile_breaks(values, classes, spec.colorbar_decimals);
    }
    if (spec.classification == "natural_breaks") {
        return natural_breaks(values, classes, 1000, 0,
                              spec.colorbar_decimals);
    }
    throw std::invalid_argument("unknown classification '" + spec.classification +
                                "'");
}

std::vector<Json> ramp_items_for_spec(const ScalarStyleSpec& spec,
                                      const ColorRamp& ramp, double vmin,
                                      double vmax, const std::string& mode,
                                      const std::vector<double>& breaks) {
    if (!(vmax > vmin)) {
        throw std::invalid_argument("ramp span needs vmax > vmin");
    }
    const int decimals = spec.colorbar_decimals;
    std::vector<Json> items;
    auto push_item = [&](double value, const std::string& color) {
        Json item = Json::object();
        item["value"] = value;
        Json rgb = Json::array();
        const auto rgba = hex_to_rgba(color);
        rgb.push_back(rgba[0]);
        rgb.push_back(rgba[1]);
        rgb.push_back(rgba[2]);
        item["color"] = std::move(rgb);
        item["label"] = format_fixed(value, decimals);
        items.push_back(std::move(item));
    };
    if (mode == "classified") {
        if (breaks.size() < 2) {
            throw std::invalid_argument("classified ramp items need breaks");
        }
        std::vector<double> positions;
        positions.reserve(breaks.size());
        for (double b : breaks) {
            positions.push_back((b - vmin) / (vmax - vmin));
        }
        positions.front() = 0.0;
        positions.back() = 1.0;
        for (std::size_t i = 0; i < positions.size(); ++i) {
            push_item(breaks[i], ramp.evaluate(positions[i]));
        }
        if (spec.reverse) {
            // values stay ascending; the color assignment flips end-for-end
            std::vector<Json> flipped = items;
            for (std::size_t i = 0; i < items.size(); ++i) {
                flipped[i]["color"] = items[items.size() - 1 - i]["color"];
            }
            return flipped;
        }
        return items;
    }
    constexpr int kStops = 17;
    for (int index = 0; index < kStops; ++index) {
        const double position = static_cast<double>(index) / (kStops - 1);
        const std::string color =
            ramp.evaluate(spec.reverse ? 1.0 - position : position);
        const double value = vmin + position * (vmax - vmin);
        push_item(value, color);
    }
    return items;
}

}  // namespace pwb::cartography
