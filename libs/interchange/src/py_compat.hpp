// pwb::interchange — internal Python-scalar coercion helpers shared by the
// manifest codec (conv-14) and the package runtime (conv-14b). Inline here
// so both TUs stay in one namespace without an extra object file.

#pragma once

#include <pwb/domain/json.hpp>
#include <pwb/interchange/path_safety.hpp>

#include <cstdio>
#include <string>

namespace pwb::interchange::detail {

// Python repr() of a raw JSON scalar, for error messages.
inline std::string repr_scalar(const Json& value) {
    if (value.is_boolean()) {
        return value.get<bool>() ? "True" : "False";
    }
    if (value.is_null()) {
        return "None";
    }
    if (value.is_string()) {
        return python_repr(value.get<std::string>());
    }
    if (value.is_number_float()) {
        // %g matches Python repr for the frozen 2.5-class values only
        // (6 significant digits); exotic floats are out of oracle scope.
        const double number = value.get<double>();
        char buffer[32];
        std::snprintf(buffer, sizeof(buffer), "%g", number);
        return buffer;
    }
    return value.dump();
}

// Python str() coercion of a raw JSON scalar (from_dict stores strings).
inline std::string py_str(const Json& value) {
    if (value.is_null()) {
        return "None";
    }
    if (value.is_boolean()) {
        return value.get<bool>() ? "True" : "False";
    }
    if (value.is_string()) {
        return value.get<std::string>();
    }
    return repr_scalar(value);
}

// Python int() coercion of a raw JSON scalar; raises ValueError/TypeError
// with the Python message on un-coercible input.
inline long long py_llong(const Json& value) {
    if (value.is_boolean()) {
        return value.get<bool>() ? 1 : 0;
    }
    if (value.is_number_integer()) {
        return value.get<long long>();
    }
    if (value.is_number_float()) {
        return static_cast<long long>(value.get<double>());
    }
    if (value.is_string()) {
        const std::string raw = value.get<std::string>();
        std::size_t begin = raw.find_first_not_of(" \t\n\r\v\f");
        bool negative = false;
        if (begin != std::string::npos && (raw[begin] == '+' || raw[begin] == '-')) {
            negative = raw[begin] == '-';
            ++begin;
        }
        const std::size_t digits_begin = begin;
        if (begin == std::string::npos
            || raw.find_first_not_of("0123456789", digits_begin)
                != std::string::npos
            || digits_begin >= raw.size()) {
            throw std::invalid_argument(
                "invalid literal for int() with base 10: " + python_repr(raw));
        }
        const long long parsed = std::stoll(raw.substr(digits_begin));
        return negative ? -parsed : parsed;
    }
    // Frozen scope: only JSON null reaches this line in the oracle; Python
    // would name the actual type here.
    throw std::invalid_argument(
        "int() argument must be a string, a bytes-like object or a real "
        "number, not 'NoneType'");
}

}  // namespace pwb::interchange::detail
