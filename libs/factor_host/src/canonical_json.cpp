#include <pwb/factor_host/canonical_json.hpp>

#include "semantics.hpp"

#include <algorithm>
#include <charconv>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

namespace pwb::factor_host {
namespace {

// Strict Python float() string syntax (PEP float literal minus underscores):
// [sign] ( digits [ '.' digits? ] | '.' digits ) ( [eE] [sign] digits )?
// | [sign] ( 'inf' | 'infinity' | 'nan' )  -- case-insensitive, no parens,
// and the whole string must be consumed (rejects C99 "nan(n-char-seq)").
bool is_python_float_literal(const std::string& s) {
    std::size_t i = 0;
    const std::size_t n = s.size();
    if (i < n && (s[i] == '+' || s[i] == '-')) ++i;
    const auto match_word = [&](const char* word) {
        const std::size_t len = std::strlen(word);
        if (n - i < len) return false;
        for (std::size_t k = 0; k < len; ++k) {
            const char c = s[i + k];
            if (std::tolower(static_cast<unsigned char>(c)) != word[k]) {
                return false;
            }
        }
        i += len;
        return true;
    };
    if (i < n && (std::tolower(static_cast<unsigned char>(s[i])) == 'i' ||
                  std::tolower(static_cast<unsigned char>(s[i])) == 'n')) {
        if (!(match_word("infinity") || match_word("inf") || match_word("nan"))) {
            return false;
        }
        return i == n;
    }
    std::size_t digits = 0;
    while (i < n && std::isdigit(static_cast<unsigned char>(s[i]))) {
        ++i;
        ++digits;
    }
    if (i < n && s[i] == '.') {
        ++i;
        while (i < n && std::isdigit(static_cast<unsigned char>(s[i]))) {
            ++i;
            ++digits;
        }
    }
    if (digits == 0) return false;
    if (i < n && (s[i] == 'e' || s[i] == 'E')) {
        ++i;
        if (i < n && (s[i] == '+' || s[i] == '-')) ++i;
        std::size_t exponent_digits = 0;
        while (i < n && std::isdigit(static_cast<unsigned char>(s[i]))) {
            ++i;
            ++exponent_digits;
        }
        if (exponent_digits == 0) return false;
    }
    return i == n;
}

void append_escaped_string(std::string& out, const std::string& text) {
    out += '"';
    for (unsigned char c : text) {
        switch (c) {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\b': out += "\\b"; break;
            case '\f': out += "\\f"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default:
                if (c < 0x20) {
                    char buf[8];
                    std::snprintf(buf, sizeof buf, "\\u%04x", c);
                    out += buf;
                } else {
                    out += static_cast<char>(c);
                }
        }
    }
    out += '"';
}

void encode(std::string& out, const Json& value) {
    if (value.is_null()) {
        out += "null";
    } else if (value.is_boolean()) {
        out += value.get<bool>() ? "true" : "false";
    } else if (value.is_number_integer()) {
        out += std::to_string(value.get<std::int64_t>());
    } else if (value.is_number_float()) {
        out += python_repr_double(value.get<double>());
    } else if (value.is_string()) {
        append_escaped_string(out, value.get<std::string>());
    } else if (value.is_array()) {
        out += '[';
        bool first = true;
        for (const Json& item : value) {
            if (!first) out += ',';
            first = false;
            encode(out, item);
        }
        out += ']';
    } else if (value.is_object()) {
        std::vector<std::string> keys;
        keys.reserve(value.size());
        for (auto it = value.begin(); it != value.end(); ++it) {
            keys.push_back(it.key());
        }
        std::sort(keys.begin(), keys.end());  // UTF-8 byte order == code point order
        out += '{';
        bool first = true;
        for (const std::string& key : keys) {
            if (!first) out += ',';
            first = false;
            append_escaped_string(out, key);
            out += ':';
            encode(out, value.at(key));
        }
        out += '}';
    }
}

}  // namespace

std::string python_repr_double(double value) {
    if (std::isnan(value)) return "NaN";
    if (std::isinf(value)) return value > 0 ? "Infinity" : "-Infinity";
    if (value == 0.0) return std::signbit(value) ? "-0.0" : "0.0";

    // Shortest round-trip digits via to_chars scientific, then re-format
    // with Python repr's notation rules.
    char buf[64];
    auto result =
        std::to_chars(buf, buf + sizeof buf, value, std::chars_format::scientific);
    std::string text(buf, result.ptr);
    const std::size_t epos = text.find('e');
    std::string mantissa = text.substr(0, epos);
    const int exp10 = std::atoi(text.c_str() + epos + 1);

    bool negative = false;
    if (!mantissa.empty() && mantissa.front() == '-') {
        negative = true;
        mantissa.erase(0, 1);
    }
    std::string digits;
    digits.reserve(mantissa.size());
    for (char c : mantissa) {
        if (c != '.') digits += c;
    }

    std::string out = negative ? "-" : "";
    if (exp10 >= -4 && exp10 < 16) {
        if (exp10 >= 0) {
            const std::size_t int_digits = static_cast<std::size_t>(exp10) + 1;
            if (digits.size() <= int_digits) {
                out += digits;
                out += std::string(int_digits - digits.size(), '0');
                out += ".0";
            } else {
                out += digits.substr(0, int_digits);
                out += '.';
                out += digits.substr(int_digits);
            }
        } else {
            out += "0.";
            out += std::string(static_cast<std::size_t>(-exp10) - 1, '0');
            out += digits;
        }
    } else {
        out += digits.front();
        if (digits.size() > 1) {
            out += '.';
            out += digits.substr(1);
        }
        const int magnitude = std::abs(exp10);
        out += exp10 < 0 ? "e-" : "e+";
        if (magnitude < 10) out += '0';
        out += std::to_string(magnitude);
    }
    return out;
}

std::optional<double> python_float_from_string(const std::string& text) {
    // Python float() strips a number-specific whitespace set, then requires
    // the strict float literal grammar. The set accepts \t\n\v\f\r space
    // plus the non-ASCII isspace forms (NBSP, U+3000, …) but NOT \x1c-\x1f:
    // CPython's float parser rejects those even though str.strip() removes
    // them (verified against the interpreter). Hex floats, nan(payload),
    // underscores and non-ASCII digits are ValueErrors.
    const std::string trimmed = detail::python_strip_number(text);
    if (trimmed.empty()) return std::nullopt;
    if (trimmed.find('_') != std::string::npos) return std::nullopt;
    if (!is_python_float_literal(trimmed)) return std::nullopt;
    char* parse_end = nullptr;
    const double parsed = std::strtod(trimmed.c_str(), &parse_end);
    if (parse_end != trimmed.c_str() + trimmed.size()) return std::nullopt;
    return parsed;
}

std::string python_str_scalar(const Json& value) {
    if (value.is_string()) return value.get<std::string>();
    if (value.is_boolean()) return value.get<bool>() ? "True" : "False";
    if (value.is_number_integer()) return std::to_string(value.get<std::int64_t>());
    if (value.is_number_float()) return python_repr_double(value.get<double>());
    // Containers: Python str() renders dict/list repr; we render compact
    // JSON. Documented divergence — only reachable from qc_flag-shaped
    // fields whose str() text is display-only.
    return value.dump();
}

std::string canonical_encode(const Json& value) {
    std::string out;
    encode(out, value);
    return out;
}

}  // namespace pwb::factor_host
