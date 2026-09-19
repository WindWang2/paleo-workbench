#pragma once

// UI-09 — small domain::Json field accessors with Python dict.get parity.
// Header-only: `field_value(source, name, default)` semantics — missing key
// or wrong type yields the caller's default, never throws.

#include <optional>
#include <string>
#include <string_view>

#include <pwb/domain/json.hpp>

namespace pwb::ui_wellseis {

using domain::Json;

namespace detail {
inline const Json& null_json() {
    static const Json value = Json(nullptr);
    return value;
}
inline const Json& empty_object() {
    static const Json value = Json::object();
    return value;
}
inline const Json& empty_array() {
    static const Json value = Json::array();
    return value;
}
}  // namespace detail

// source.get(name) — null Json when the key is absent or source is not an
// object (Python AttributeError/KeyError never reaches the UI layer).
inline const Json& json_field(const Json& source, std::string_view name) {
    if (!source.is_object()) {
        return detail::null_json();
    }
    const auto it = source.find(std::string(name));
    if (it == source.end()) {
        return detail::null_json();
    }
    return *it;
}

inline const Json& json_object(const Json& source, std::string_view name) {
    const Json& v = json_field(source, name);
    return v.is_object() ? v : detail::empty_object();
}

inline const Json& json_array(const Json& source, std::string_view name) {
    const Json& v = json_field(source, name);
    return v.is_array() ? v : detail::empty_array();
}

// str(value) for scalars; default for null/non-scalar. Numbers render like
// Python str() of a float/int ("0.8", "3" — nlohmann dump already matches).
inline std::string json_str(const Json& source, std::string_view name,
                            std::string fallback = "") {
    const Json& v = json_field(source, name);
    if (v.is_string()) {
        return v.get<std::string>();
    }
    if (v.is_number_integer() || v.is_number_unsigned()) {
        return std::to_string(v.get<long long>());
    }
    if (v.is_number_float()) {
        // Python str(float) prints the shortest round-trip repr;
        // nlohmann's dump does the same for doubles.
        return v.dump();
    }
    if (v.is_boolean()) {
        return v.get<bool>() ? "True" : "False";
    }
    return fallback;
}

inline std::optional<double> json_number(const Json& source,
                                         std::string_view name) {
    const Json& v = json_field(source, name);
    if (v.is_number()) {
        return v.get<double>();
    }
    return std::nullopt;
}

inline bool json_bool(const Json& source, std::string_view name,
                      bool fallback = false) {
    const Json& v = json_field(source, name);
    if (v.is_boolean()) {
        return v.get<bool>();
    }
    return fallback;
}

// Python truthiness of source[name]: null/missing/false/0/""/[]/{} -> false.
inline bool json_truthy(const Json& source, std::string_view name) {
    const Json& v = json_field(source, name);
    if (v.is_null()) return false;
    if (v.is_boolean()) return v.get<bool>();
    if (v.is_number()) return v.get<double>() != 0.0;
    if (v.is_string()) return !v.get<std::string>().empty();
    if (v.is_array() || v.is_object()) return !v.empty();
    return false;
}

}  // namespace pwb::ui_wellseis
