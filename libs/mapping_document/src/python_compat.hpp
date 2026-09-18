// Python scalar coercions used by the document kernels (internal).
//
// These mirror the *specific* coercion semantics of the ported from_dict
// paths: `payload.get(key) or default` (falsy collapse) versus
// `payload.get(key, default)` (presence check), Python float()/int()/str()
// and truthiness. Bounded by design: float("1_000")-style literal underscores
// are NOT accepted (no fixture or product path relies on them).
#pragma once

#include <pwb/domain/json.hpp>

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace pwb::mapping_document::detail {

using Json = pwb::domain::Json;

inline bool py_truthy(const Json& value) {
    switch (value.type()) {
        case Json::value_t::null:
            return false;
        case Json::value_t::boolean:
            return value.get<bool>();
        case Json::value_t::number_integer:
        case Json::value_t::number_unsigned:
            return value.get<long long>() != 0;
        case Json::value_t::number_float:
            return value.get<double>() != 0.0;
        case Json::value_t::string:
            return !value.get<std::string>().empty();
        case Json::value_t::array:
        case Json::value_t::object:
            return !value.empty();
        default:
            return false;
    }
}

// Python float(x): numbers pass through (bool → 0/1), strings parse after
// both-end whitespace trim with inf/infinity/nan accepted; anything else or a
// partial parse raises like the uncaught ValueError.
inline double py_float(const Json& value) {
    if (value.is_boolean()) return value.get<bool>() ? 1.0 : 0.0;
    if (value.is_number()) return value.get<double>();
    if (!value.is_string()) {
        throw std::invalid_argument(
            "python_compat: float() of a non-scalar JSON value");
    }
    const std::string raw = value.get<std::string>();
    const char* ws = " \t\n\r\f\v";
    const std::size_t begin = raw.find_first_not_of(ws);
    const std::string trimmed = begin == std::string::npos
                                    ? std::string()
                                    : raw.substr(begin, raw.find_last_not_of(ws) + 1 - begin);
    if (trimmed.empty()) {
        throw std::invalid_argument("python_compat: float() of empty string");
    }
    // Case-insensitive specials (strtod only knows the C locale spellings).
    std::string lowered;
    lowered.reserve(trimmed.size());
    for (char c : trimmed) lowered.push_back(static_cast<char>(std::tolower(static_cast<unsigned char>(c))));
    std::string body = lowered;
    bool negative = false;
    if (!body.empty() && (body.front() == '+' || body.front() == '-')) {
        negative = body.front() == '-';
        body.erase(body.begin());
    }
    if (body == "inf" || body == "infinity") {
        return negative ? -std::numeric_limits<double>::infinity()
                        : std::numeric_limits<double>::infinity();
    }
    if (body == "nan") {
        return std::numeric_limits<double>::quiet_NaN();
    }
    // Python float() rejects hex literals ("0x1A" raises); glibc strtod would
    // happily parse them — refuse before touching strtod.
    if (!body.empty() && body[0] == '0' && body.size() > 1
        && (body[1] == 'x' || body[1] == 'X')) {
        throw std::invalid_argument(
            "python_compat: could not convert string to float: " + raw);
    }
    char* end = nullptr;
    const double parsed = std::strtod(trimmed.c_str(), &end);
    if (end != trimmed.c_str() + trimmed.size() || end == trimmed.c_str()) {
        throw std::invalid_argument("python_compat: could not convert string to float: " + raw);
    }
    return parsed;
}

// Python int(x): floats truncate toward zero, bools are 0/1, strings must be
// a strict integer literal after whitespace trim ("3.5" raises).
inline long long py_int(const Json& value) {
    if (value.is_boolean()) return value.get<bool>() ? 1 : 0;
    if (value.is_number_integer()) return value.get<long long>();
    if (value.is_number_float()) {
        const double v = value.get<double>();
        if (std::isnan(v) || std::isinf(v) || std::fabs(v) > 9.3e18) {
            throw std::invalid_argument("python_compat: int() overflow");
        }
        return static_cast<long long>(v);  // C++ truncation == Python int()
    }
    if (value.is_string()) {
        const std::string raw = value.get<std::string>();
        const char* ws = " \t\n\r\f\v";
        const std::size_t begin = raw.find_first_not_of(ws);
        if (begin == std::string::npos) {
            throw std::invalid_argument("python_compat: int() of empty string");
        }
        const std::string trimmed =
            raw.substr(begin, raw.find_last_not_of(ws) + 1 - begin);
        std::size_t at = 0;
        const bool negative = trimmed[0] == '-';
        if (trimmed[0] == '+' || trimmed[0] == '-') ++at;
        if (at >= trimmed.size()) {
            throw std::invalid_argument("python_compat: int() of invalid literal: " + raw);
        }
        long long magnitude = 0;
        for (; at < trimmed.size(); ++at) {
            const unsigned char c = static_cast<unsigned char>(trimmed[at]);
            if (!std::isdigit(c)) {
                throw std::invalid_argument("python_compat: int() of invalid literal: " + raw);
            }
            const long long digit = c - '0';
            constexpr long long kMax = std::numeric_limits<long long>::max();
            if (magnitude > (kMax - digit) / 10) {
                throw std::invalid_argument("python_compat: int() overflow");
            }
            magnitude = magnitude * 10 + digit;
        }
        return negative ? -magnitude : magnitude;
    }
    throw std::invalid_argument("python_compat: int() of a non-scalar JSON value");
}

// Python str(x) for the scalar shapes the document kernels read back:
// strings as-is, ints as digits, floats in shortest-round-trip form (which
// nlohmann's dump already matches, including the ".0" suffix), bools as
// True/False, null as None.
inline std::string py_str(const Json& value) {
    if (value.is_string()) return value.get<std::string>();
    if (value.is_boolean()) return value.get<bool>() ? "True" : "False";
    if (value.is_null()) return "None";
    // numbers (and, as a documented last resort, containers) take their
    // shortest JSON form — nlohmann's dump matches Python str() for numbers.
    return value.dump();
}
// Copy every payload key not named in `keys` into `extras`, preserving the
// input order (§7.4: unknown keys are never dropped).
inline void collect_extras(const Json& payload,
                           const std::vector<const char*>& keys, Json& extras) {
    extras = Json::object();
    for (auto it = payload.begin(); it != payload.end(); ++it) {
        const bool known = std::any_of(keys.begin(), keys.end(),
                                       [&](const char* k) { return k == it.key(); });
        if (!known) extras[it.key()] = it.value();
    }
}

// Python integers are unbounded; when such a JSON number parses back through
// nlohmann, non-negative values become number_unsigned and negatives become
// number_integer. The domain comparator is strict about that distinction, so
// the kernels emit integers in the shape a Python-written document parses to.
inline Json py_int_json(long long value) {
    if (value >= 0) return Json(static_cast<std::uint64_t>(value));
    return Json(value);
}

}  // namespace pwb::mapping_document::detail
