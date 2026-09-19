#pragma once

// Internal Python-parity helpers for the workflow runtime port (CONV-26).
// Not part of the public surface.

#include <pwb/domain/json.hpp>
#include <pwb/factor_host/canonical_json.hpp>

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <optional>
#include <string>

namespace pwb::workflow_runtime::pycompat {

using pwb::domain::Json;

// Python repr() of a string — single quotes unless the string contains '
// (and not "); backslash/control escapes. Used for frozen detail messages
// like "parameter 'power' changed".
inline std::string repr_str(const std::string& value) {
    const bool has_single = value.find('\'') != std::string::npos;
    const bool has_double = value.find('"') != std::string::npos;
    const char quote = (has_single && !has_double) ? '"' : '\'';
    std::string out(1, quote);
    for (char c : value) {
        switch (c) {
        case '\\': out += "\\\\"; break;
        case '\n': out += "\\n"; break;
        case '\r': out += "\\r"; break;
        case '\t': out += "\\t"; break;
        default:
            if (c == quote) out += '\\';
            out += c;
        }
    }
    out += quote;
    return out;
}

// Python repr() of an optional string (None -> "None").
inline std::string repr_optional_str(const std::optional<std::string>& value) {
    if (!value) return "None";
    return repr_str(*value);
}

// Python round(x, 9): correctly-rounded decimal rounding of the binary
// double (glibc printf is correctly rounded, matching CPython's dtoa).
inline double round9(double value) {
    if (!std::isfinite(value)) return value;
    char buf[64];
    std::snprintf(buf, sizeof(buf), "%.9f", value);
    return std::strtod(buf, nullptr);
}

// Python truthiness of a JSON scalar/container.
inline bool truthy(const Json& value) {
    switch (value.type()) {
    case Json::value_t::null: return false;
    case Json::value_t::boolean: return value.get<bool>();
    case Json::value_t::number_integer:
        return value.get<std::int64_t>() != 0;
    case Json::value_t::number_unsigned:
        return value.get<std::uint64_t>() != 0;
    case Json::value_t::number_float:
        return value.get<double>() != 0.0;
    case Json::value_t::string: return !value.get_ref<const std::string&>().empty();
    case Json::value_t::array: return !value.empty();
    case Json::value_t::object: return !value.empty();
    default: return false;
    }
}

// str() coercion of a JSON scalar (Python str(True) == "True"); containers
// fall back to the JSON dump (host documents never str() containers here).
inline std::string str_scalar(const Json& value) {
    return pwb::factor_host::python_str_scalar(value);
}

// s[:12] of an optional string ("" when absent).
inline std::string head12(const std::optional<std::string>& value) {
    if (!value) return "";
    return value->substr(0, 12);
}
inline std::string head12(const std::string& value) {
    return value.substr(0, 12);
}

// Python dict get with default (missing key OR null -> fallback).
inline Json dict_get(const Json& obj, const char* key, Json fallback) {
    if (obj.is_object() && obj.contains(key) && !obj.at(key).is_null()) {
        return obj.at(key);
    }
    return fallback;
}

}  // namespace pwb::workflow_runtime::pycompat
