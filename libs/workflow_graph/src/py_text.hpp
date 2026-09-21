#pragma once

// Shared Python-semantics text helpers for libs/workflow_graph (D6 local
// py-helper allowance — one copy, not per-TU duplicates). Covers:
//   * str() on Json scalars/containers (float "1.0", None, True/False,
//     repr-style containers) — the single implementation behind both the
//     evidence resolvers and the graph's parameter comparisons;
//   * repr() quoting for !r-interpolated messages;
//   * str.strip() over the full Unicode whitespace set;
//   * truthiness / `or ""` collapse.
//
// Leaf-lib scope: no Qt, no Python.

#include <pwb/domain/json.hpp>
#include <pwb/domain/text.hpp>

#include <charconv>
#include <cmath>
#include <cstdlib>
#include <optional>
#include <string>
#include <string_view>

namespace pwb::workflow_graph::detail {

using pwb::domain::Json;

// --- UTF-8 / Unicode whitespace ----------------------------------------------

struct CodePoint {
    char32_t cp;
    std::size_t size;
};

// Decode one UTF-8 code point at s[i]; nullopt on ill-formed input
// (callers consume one byte so a truncated sequence can never wedge).
inline std::optional<CodePoint> utf8_code_point(std::string_view s,
                                                std::size_t i) {
    if (i >= s.size()) return std::nullopt;
    const unsigned char c = s[i];
    const std::size_t len =
        c < 0x80 ? 1 : c < 0xE0 ? 2 : c < 0xF0 ? 3 : 4;
    if (i + len > s.size()) return std::nullopt;
    char32_t cp;
    switch (len) {
        case 1: cp = c; break;
        case 2: cp = c & 0x1F; break;
        case 3: cp = c & 0x0F; break;
        default: cp = c & 0x07; break;
    }
    for (std::size_t k = 1; k < len; ++k) {
        const unsigned char cc = s[i + k];
        if ((cc & 0xC0) != 0x80) return std::nullopt;
        cp = (cp << 6) | (cc & 0x3F);
    }
    return CodePoint{cp, len};
}

// Python str.strip() — full Unicode whitespace set (#1343 item 1; the
// previous ASCII-only strip rejected U+3000-wrapped selectors Python
// parses fine). Shared implementation lives in pwb::domain (#1392).
inline std::string py_strip(std::string_view s) {
    return domain::python_strip(s);
}

// --- repr() ------------------------------------------------------------------

// repr() of a string for f"{x!r}"-interpolated messages (#1343 item 2):
// CPython prefers single quotes, switches to double when the text holds '
// but not "; escapes \\, the active quote, \n \r \t, C0 controls, DEL,
// C1 (U+0080–U+009F), NBSP and the line/paragraph separators as \xNN /
// \uNNNN. Other code points pass through (printable per the common case).
inline std::string py_repr_string(const std::string& s) {
    const bool has_sq = s.find('\'') != std::string::npos;
    const bool has_dq = s.find('"') != std::string::npos;
    const char quote = (has_sq && !has_dq) ? '"' : '\'';
    std::string out;
    out += quote;
    for (std::size_t i = 0; i < s.size();) {
        const auto d = utf8_code_point(s, i);
        const char32_t cp = d ? d->cp : static_cast<unsigned char>(s[i]);
        const std::size_t len = d ? d->size : 1;
        if (cp == '\\') {
            out += "\\\\";
        } else if (cp == static_cast<char32_t>(quote)) {
            out += '\\';
            out += quote;
        } else if (cp == '\n') {
            out += "\\n";
        } else if (cp == '\r') {
            out += "\\r";
        } else if (cp == '\t') {
            out += "\\t";
        } else if (cp < 0x20 || (cp >= 0x7F && cp <= 0xA0) ||
                   cp == 0x2028 || cp == 0x2029) {
            char buf[16];
            if (cp <= 0xFF) {
                std::snprintf(buf, sizeof buf, "\\x%02x",
                              static_cast<unsigned>(cp));
            } else {
                std::snprintf(buf, sizeof buf, "\\u%04x",
                              static_cast<unsigned>(cp));
            }
            out += buf;
        } else {
            out.append(s, i, len);
        }
        i += len;
    }
    out += quote;
    return out;
}

// --- str() --------------------------------------------------------------------

// Shortest round-trip float repr with Python str() notation rules
// (nan/inf lowercase — str(), not repr-in-dict style).
inline std::string py_float_str(double value) {
    if (std::isnan(value)) return "nan";
    if (std::isinf(value)) return value > 0 ? "inf" : "-inf";
    if (value == 0.0) return std::signbit(value) ? "-0.0" : "0.0";
    char buf[64];
    auto result = std::to_chars(buf, buf + sizeof buf, value,
                                std::chars_format::scientific);
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
    for (char c : mantissa)
        if (c != '.') digits += c;
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

inline std::string py_repr_json(const Json& v);

inline std::string py_str(const Json& v) {
    if (v.is_null()) return "None";  // str(None) — #1341/#1343
    if (v.is_string()) return v.get<std::string>();
    if (v.is_boolean()) return v.get<bool>() ? "True" : "False";
    if (v.is_number_integer()) return std::to_string(v.get<long long>());
    if (v.is_number_unsigned())
        return std::to_string(v.get<unsigned long long>());
    if (v.is_number_float()) return py_float_str(v.get<double>());
    return py_repr_json(v);
}

// repr() on a Json value — container contents use repr, matching
// str(list/dict) element rendering (', ' separators, quoted strings).
inline std::string py_repr_json(const Json& v) {
    if (v.is_string()) return py_repr_string(v.get<std::string>());
    if (v.is_array()) {
        std::string out = "[";
        bool first = true;
        for (const auto& el : v) {
            if (!first) out += ", ";
            first = false;
            out += py_repr_json(el);
        }
        return out + "]";
    }
    if (v.is_object()) {
        std::string out = "{";
        bool first = true;
        for (const auto& [k, val] : v.items()) {
            if (!first) out += ", ";
            first = false;
            out += py_repr_string(k);
            out += ": ";
            out += py_repr_json(val);
        }
        return out + "}";
    }
    return py_str(v);
}

// --- truthiness / attr fetches -------------------------------------------------

// Python builtin type name — used for AttributeError/TypeError messages
// ("'list' object has no attribute 'get'", "'int' object is not iterable").
inline std::string py_type_name(const Json& v) {
    if (v.is_null()) return "NoneType";
    if (v.is_boolean()) return "bool";
    if (v.is_number_integer() || v.is_number_unsigned()) return "int";
    if (v.is_number_float()) return "float";
    if (v.is_string()) return "str";
    if (v.is_array()) return "list";
    return "dict";
}

// Python truthiness for Json scalars/containers.
inline bool truthy(const Json& v) {
    if (v.is_null()) return false;
    if (v.is_boolean()) return v.get<bool>();
    if (v.is_number()) return v.get<double>() != 0.0;
    if (v.is_string()) return !v.get<std::string>().empty();
    return !v.empty();
}

// getattr(obj, key, None) — Json(nullptr) for missing, the raw value
// otherwise. Used at `getattr(x, k, None) or <fallback>` sites.
inline Json attr_or_empty(const Json& obj, const char* key) {
    if (!obj.is_object() || !obj.contains(key)) return Json(nullptr);
    return obj.at(key);
}

// str(getattr(obj, key, "")) — bare str(), NO `or` collapse:
// missing -> "" (the getattr default); present null -> "None";
// present value -> str(value) (#1339/#1341).
inline std::string attr_str(const Json& obj, const char* key) {
    if (!obj.is_object() || !obj.contains(key)) return "";
    return py_str(obj.at(key));
}

// str(value or ""): falsy -> "", truthy -> str(value). The `or ""` sites
// collapse false/0/[]/{}/None to "" (#1339).
inline std::string str_or_empty(const Json& v) {
    if (!truthy(v)) return "";
    return py_str(v);
}

// str(getattr(obj, key, "") or "") — `or ""` collapse on the attr fetch.
inline std::string attr_str_or_empty(const Json& obj, const char* key) {
    return str_or_empty(attr_or_empty(obj, key));
}

}  // namespace pwb::workflow_graph::detail
