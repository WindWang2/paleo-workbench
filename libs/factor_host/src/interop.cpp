#include <pwb/factor_host/interop.hpp>

#include "semantics.hpp"

#include <pwb/factor_host/canonical_json.hpp>

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdlib>
#include <optional>
#include <stdexcept>
#include <vector>

namespace pwb::factor_host {

namespace {

// Python int(value): strict for strings ("24" ok, "24.7" raises),
// truncating for floats, 1/0 for bools. nullopt = raise → caller falls back.
std::optional<int> python_int(const Json& value) {
    if (value.is_number_integer()) return value.get<int>();
    if (value.is_number_float()) {
        const double v = value.get<double>();
        return static_cast<int>(v >= 0 ? std::floor(v) : std::ceil(v));
    }
    if (value.is_boolean()) return value.get<bool>() ? 1 : 0;
    if (value.is_string()) {
        // int() strips the number-specific whitespace set (no \x1C-\x1F)
        // and then requires strict integer digits.
        const std::string text = detail::python_strip_number(value.get<std::string>());
        if (text.empty()) return std::nullopt;
        std::size_t i = 0;
        if (text[i] == '+' || text[i] == '-') ++i;
        if (i == text.size()) return std::nullopt;
        for (std::size_t j = i; j < text.size(); ++j) {
            if (!std::isdigit(static_cast<unsigned char>(text[j]))) {
                return std::nullopt;
            }
        }
        return std::atoi(text.c_str());
    }
    return std::nullopt;
}

// Python float(value) for the JSON forms; nullopt = raise → caller falls back.
std::optional<double> python_float(const Json& value) {
    if (value.is_number()) return value.get<double>();
    if (value.is_boolean()) return value.get<bool>() ? 1.0 : 0.0;
    if (value.is_string()) {
        return python_float_from_string(value.get<std::string>());
    }
    return std::nullopt;
}

}  // namespace

std::string resolve_engine_method(const std::string& method) {
    static const Json table = [] {
        Json t = Json::object();
        t["克里金"] = "kriging";
        t["克里金(MVP·线性)"] = "kriging";
        t["IDW"] = "IDW";
        t["idw"] = "IDW";
        t["样条"] = "样条";
        t["spline"] = "样条";
        t["cubic"] = "样条";
        t["方向趋势"] = "方向趋势";
        t["directional"] = "方向趋势";
        t["kriging"] = "kriging";
        t["约束IDW"] = "constrained_idw";
        return t;
    }();
    const auto mapped = table.find(method);
    if (mapped != table.end()) return mapped->get<std::string>();
    static const std::vector<std::string> known = {
        "constrained_idw", "mock",
    };
    for (const std::string& engine : known) {
        if (method == engine) return method;
    }
    std::vector<std::string> labels;
    labels.reserve(table.size());
    for (auto it = table.begin(); it != table.end(); ++it) {
        labels.push_back(it.key());
    }
    std::sort(labels.begin(), labels.end());  // UTF-8 byte order == code points
    std::string supported;
    for (std::size_t i = 0; i < labels.size(); ++i) {
        if (i) supported += ", ";
        supported += labels[i];
    }
    throw std::invalid_argument(
        "unknown interpolation method " + detail::python_repr_string(method) +
        "; supported: " + supported);
}

Json variogram_settings_from_params(const Json& params) {
    static const std::pair<const char*, const char*> kMap[] = {
        {"variogram_model", "variogram_model"},
        {"variogram_range", "variogram_range"},
        {"variogram_nugget", "variogram_nugget"},
        {"range_m", "variogram_range"},
        {"nugget", "variogram_nugget"},
    };
    Json settings = Json::object();
    if (!params.is_object()) return settings;
    for (const auto& [src, dst] : kMap) {
        const auto it = params.find(src);
        if (it != params.end() && !it->is_null()) {
            settings[dst] = *it;
        }
    }
    return settings;
}

std::tuple<std::string, int, double> interp_params_from_task(
    const Json& params, const std::string& task_method) {
    const Json empty = Json::object();
    const Json& p = params.is_object() ? params : empty;

    std::string method = "IDW";
    const auto method_it = p.find("method");
    if (method_it != p.end() && detail::json_truthy(&*method_it)) {
        // Python str(params.get("method")): numeric/bool ids become their
        // str() text instead of failing.
        method = python_str_scalar(*method_it);
    } else if (!task_method.empty()) {
        method = task_method;
    }

    int grid_n = kDefaultGridN;
    const auto grid_it = p.find("grid_n");
    if (grid_it != p.end() && detail::json_truthy(&*grid_it)) {
        if (auto parsed = python_int(*grid_it)) {
            grid_n = std::max(8, *parsed);
        }
    }

    double power = 2.0;
    const auto power_it = p.find("power");
    if (power_it != p.end() && detail::json_truthy(&*power_it)) {
        if (auto parsed = python_float(*power_it)) {
            power = *parsed;
        }
    }
    return {method, grid_n, power};
}

}  // namespace pwb::factor_host
