#include "python_compat.hpp"

#include <cmath>
#include <cstdio>
#include <cstring>
#include <stdexcept>

#include "pwb/ingest/py_compat.hpp"
#include "pwb/prediction/errors.hpp"

namespace pwb::prediction::detail {

namespace {

// The complete CPython str.isspace() set (29 code points).
bool py_is_space(char32_t cp) {
    if (cp >= 0x09 && cp <= 0x0D) return true;   // \t\n\v\f\r
    if (cp >= 0x1C && cp <= 0x1F) return true;   // FS GS RS US
    switch (cp) {
        case 0x20: case 0x85: case 0xA0: case 0x1680:
        case 0x2028: case 0x2029: case 0x202F: case 0x205F: case 0x3000:
            return true;
        default:
            return cp >= 0x2000 && cp <= 0x200A;
    }
}

void append_cp(std::string& out, char32_t cp) {
    if (cp < 0x80) {
        out.push_back(static_cast<char>(cp));
    } else if (cp < 0x800) {
        out.push_back(static_cast<char>(0xC0 | (cp >> 6)));
        out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
    } else if (cp < 0x10000) {
        out.push_back(static_cast<char>(0xE0 | (cp >> 12)));
        out.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F)));
        out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
    } else {
        out.push_back(static_cast<char>(0xF0 | (cp >> 18)));
        out.push_back(static_cast<char>(0x80 | ((cp >> 12) & 0x3F)));
        out.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F)));
        out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
    }
}

std::string repr_string(const std::string& s) {
    const bool has_sq = s.find('\'') != std::string::npos;
    const bool has_dq = s.find('"') != std::string::npos;
    const char quote = (has_sq && !has_dq) ? '"' : '\'';
    std::string out;
    out.push_back(quote);
    for (size_t i = 0; i < s.size();) {
        auto cp = pwb::ingest::detail::utf8_code_point(s, i);
        if (!cp) { ++i; continue; }
        const char32_t c = cp->cp;
        if (c == static_cast<char32_t>(quote) || c == '\\') {
            out.push_back('\\');
            out.push_back(static_cast<char>(c));
        } else if (c == '\n') {
            out += "\\n";
        } else if (c == '\r') {
            out += "\\r";
        } else if (c == '\t') {
            out += "\\t";
        } else if (c < 0x20 || (c >= 0x7F && c <= 0xA0)) {
            char buf[8];
            std::snprintf(buf, sizeof buf, "\\x%02x", static_cast<unsigned>(c));
            out += buf;
        } else {
            append_cp(out, c);
        }
        i += cp->size;
    }
    out.push_back(quote);
    return out;
}

// repr() for a JSON scalar.
std::string repr_scalar(const Json& v) {
    if (v.is_null()) return "None";
    if (v.is_boolean()) return v.get<bool>() ? "True" : "False";
    if (v.is_number()) {
        // nlohmann prints the shortest round-trip form and always keeps a
        // decimal marker on floats, matching repr(int)/repr(float).
        return v.dump();
    }
    if (v.is_string()) return repr_string(v.get_ref<const std::string&>());
    return {};
}

}  // namespace

bool py_truthy(const Json& v) {
    switch (v.type()) {
        case Json::value_t::null: return false;
        case Json::value_t::boolean: return v.get<bool>();
        case Json::value_t::number_integer:
        case Json::value_t::number_unsigned:
        case Json::value_t::number_float:
            return v.get<double>() != 0.0;
        case Json::value_t::string:
            return !v.get_ref<const std::string&>().empty();
        case Json::value_t::array:
        case Json::value_t::object:
            return !v.empty();
        default:
            return false;
    }
}

const Json& py_or(const Json& a, const Json& b) {
    return py_truthy(a) ? a : b;
}

std::string py_str(const Json& v) {
    if (v.is_string()) return v.get_ref<const std::string&>();
    if (v.is_array() || v.is_object()) return py_repr(v);
    return repr_scalar(v);
}

std::string py_repr(const Json& v) {
    if (v.is_array()) {
        std::string out = "[";
        bool first = true;
        for (const auto& el : v) {
            if (!first) out += ", ";
            first = false;
            out += py_repr(el);
        }
        return out + "]";
    }
    if (v.is_object()) {
        std::string out = "{";
        bool first = true;
        for (const auto& [key, val] : v.items()) {
            if (!first) out += ", ";
            first = false;
            out += repr_string(key);
            out += ": ";
            out += py_repr(val);
        }
        return out + "}";
    }
    return repr_scalar(v);
}

std::string py_strip(std::string_view text) {
    size_t b = 0, e = text.size();
    auto space_at = [&](size_t i) {
        auto cp = pwb::ingest::detail::utf8_code_point(text, i);
        return cp && py_is_space(cp->cp);
    };
    while (b < e && space_at(b)) b += pwb::ingest::detail::utf8_code_point(text, b)->size;
    while (e > b) {
        size_t k = e - 1;
        while (k > b && (static_cast<unsigned char>(text[k]) & 0xC0) == 0x80) --k;
        if (!space_at(k)) break;
        e = k;
    }
    return std::string(text.substr(b, e - b));
}

std::optional<double> py_finite_number(const Json& v) {
    if (v.is_boolean()) return v.get<bool>() ? 1.0 : 0.0;
    if (v.is_number()) {
        const double d = v.get<double>();
        return std::isfinite(d) ? std::optional<double>(d) : std::nullopt;
    }
    if (v.is_string()) {
        const auto parsed =
            pwb::ingest::py_parse_float(v.get_ref<const std::string&>());
        if (parsed && std::isfinite(*parsed)) return parsed;
    }
    return std::nullopt;
}

long long py_int(const Json& v) {
    if (v.is_boolean()) return v.get<bool>() ? 1 : 0;
    if (v.is_number_integer()) return v.get<long long>();
    if (v.is_number_unsigned()) {
        const auto u = v.get<unsigned long long>();
        if (u > static_cast<unsigned long long>(INT64_MAX)) {
            throw ValueError(
                "int() argument out of int64 range for JSON port");
        }
        return static_cast<long long>(u);
    }
    if (v.is_number_float()) {
        const double d = std::trunc(v.get<double>());
        if (d > 9.2e18 || d < -9.2e18) {
            // Python produces a bignum; out of the ported contract domain.
            throw ValueError("int() of float overflows int64");
        }
        return static_cast<long long>(d);
    }
    if (v.is_string()) {
        const std::string s = py_strip(v.get_ref<const std::string&>());
        size_t i = 0;
        if (i < s.size() && (s[i] == '+' || s[i] == '-')) ++i;
        const size_t start = i;
        bool have_digit = false;
        for (; i < s.size(); ++i) {
            const char c = s[i];
            if (c == '_') {
                const bool prev_d = i > start && s[i - 1] >= '0' && s[i - 1] <= '9';
                const bool next_d =
                    i + 1 < s.size() && s[i + 1] >= '0' && s[i + 1] <= '9';
                if (!prev_d || !next_d) break;
                continue;
            }
            if (c < '0' || c > '9') break;
            have_digit = true;
        }
        if (i == s.size() && have_digit) {
            // Erase underscores then strtoll (Python accepts 1_000 = 1000).
            std::string clean;
            clean.reserve(s.size());
            for (char c : s) if (c != '_') clean.push_back(c);
            return std::stoll(clean);
        }
        throw ValueError(
            "invalid literal for int() with base 10: " + py_repr(v));
    }
    throw TypeError(
        "int() argument must be a string, a bytes-like object or a real "
        "number, not '" +
        py_type_name(v) + "'");
}

std::optional<double> py_float_raw(const Json& v) {
    if (v.is_boolean()) return v.get<bool>() ? 1.0 : 0.0;
    if (v.is_number()) return v.get<double>();
    if (v.is_string()) {
        return pwb::ingest::py_parse_float(v.get_ref<const std::string&>());
    }
    return std::nullopt;
}

double py_round6(double v) {
    if (!std::isfinite(v)) return v;
    char buf[64];
    std::snprintf(buf, sizeof buf, "%.6f", v);
    return std::strtod(buf, nullptr);
}

bool py_isclose(double a, double b, double abs_tol) {
    if (a == b) return true;
    return std::fabs(a - b) <=
           std::max(1e-9 * std::max(std::fabs(a), std::fabs(b)), abs_tol);
}

namespace {

// pathlib: collapse trailing slashes, then take the final component.
std::string_view final_component(std::string_view path) {
    size_t end = path.size();
    while (end > 1 && path[end - 1] == '/') --end;
    const std::string_view body = path.substr(0, end);
    const auto pos = body.find_last_of('/');
    return pos == std::string_view::npos ? body : body.substr(pos + 1);
}

}  // namespace

std::string py_path_stem(std::string_view path) {
    const std::string_view name = final_component(path);
    const auto i = name.rfind('.');
    if (i != std::string_view::npos && i > 0 && i < name.size() - 1) {
        return std::string(name.substr(0, i));
    }
    return std::string(name);
}

std::string py_path_name(std::string_view path) {
    return std::string(final_component(path));
}

#include "word_char_ranges.inc"

bool is_word_char(char32_t cp) {
    if (cp == '_') return true;
    const auto c = static_cast<std::uint32_t>(cp);
    size_t lo = 0, hi = kWordCharRangeCount;
    while (lo < hi) {
        const size_t mid = (lo + hi) / 2;
        if (c < kWordCharRanges[mid][0]) {
            hi = mid;
        } else if (c > kWordCharRanges[mid][1]) {
            lo = mid + 1;
        } else {
            return true;
        }
    }
    return false;
}

std::string keep_word_chars(std::string_view text) {
    std::string out;
    out.reserve(text.size());
    for (size_t i = 0; i < text.size();) {
        auto cp = pwb::ingest::detail::utf8_code_point(text, i);
        if (!cp) { ++i; continue; }
        if (is_word_char(cp->cp)) {
            out.append(text.substr(i, cp->size));
        }
        i += cp->size;
    }
    return out;
}

std::string py_type_name(const Json& v) {
    switch (v.type()) {
        case Json::value_t::null: return "NoneType";
        case Json::value_t::boolean: return "bool";
        case Json::value_t::number_integer:
        case Json::value_t::number_unsigned: return "int";
        case Json::value_t::number_float: return "float";
        case Json::value_t::string: return "str";
        case Json::value_t::array: return "list";
        case Json::value_t::object: return "dict";
        default: return "object";
    }
}

}  // namespace pwb::prediction::detail
