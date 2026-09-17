#include "pwb/ingest/py_compat.hpp"

#include <cmath>
#include <cstdio>
#include <string>

namespace pwb::ingest {

using detail::CodePoint;

namespace {

bool is_digit(char c) { return c >= '0' && c <= '9'; }

bool is_py_space(unsigned char c) {
    // ASCII members of CPython str.strip() default set.
    return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\f' ||
           c == '\v';
}

std::optional<CodePoint> decode_cp(std::string_view s, size_t i) {
    unsigned char c = static_cast<unsigned char>(s[i]);
    if (c < 0x80) return CodePoint{c, 1};
    size_t len = 0;
    char32_t cp = 0;
    if ((c & 0xE0) == 0xC0) { len = 2; cp = c & 0x1F; }
    else if ((c & 0xF0) == 0xE0) { len = 3; cp = c & 0x0F; }
    else if ((c & 0xF8) == 0xF0) { len = 4; cp = c & 0x07; }
    else return std::nullopt;
    if (i + len > s.size()) return std::nullopt;
    for (size_t k = 1; k < len; ++k) {
        unsigned char cc = static_cast<unsigned char>(s[i + k]);
        if ((cc & 0xC0) != 0x80) return std::nullopt;
        cp = (cp << 6) | (cc & 0x3F);
    }
    return CodePoint{cp, len};
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

bool cp_is_unicode_space(char32_t cp) {
    // The non-ASCII str.isspace() members reachable in practice.
    switch (cp) {
        case 0x00A0: case 0x1680: case 0x2028: case 0x2029: case 0x202F:
        case 0x205F: case 0x3000:
            return true;
        default:
            return cp >= 0x2000 && cp <= 0x200A;
    }
}

std::optional<double> nan_or_inf(std::string_view word) {
    // lowercase ASCII compare
    std::string lower;
    lower.reserve(word.size());
    for (char c : word) lower.push_back(c >= 'A' && c <= 'Z' ? c + 32 : c);
    if (lower == "inf" || lower == "infinity") return INFINITY;
    if (lower == "nan") return NAN;
    return std::nullopt;
}

}  // namespace

namespace detail {

std::optional<CodePoint> utf8_code_point(std::string_view s, size_t i) {
    return decode_cp(s, i);
}

}  // namespace detail

std::optional<double> py_parse_float(std::string_view text) {
    size_t b = 0, e = text.size();
    while (b < e && is_py_space(static_cast<unsigned char>(text[b]))) ++b;
    while (e > b && is_py_space(static_cast<unsigned char>(text[e - 1]))) --e;
    std::string_view s = text.substr(b, e - b);
    if (s.empty()) return std::nullopt;

    size_t i = 0;
    bool negative = false;
    if (s[i] == '+' || s[i] == '-') {
        negative = s[i] == '-';
        ++i;
    }
    std::string_view body = s.substr(i);
    if (body.empty()) return std::nullopt;
    if (auto special = nan_or_inf(body)) {
        return negative ? -(*special) : *special;
    }

    // float("+-1") is a ValueError: the body may not start with a sign
    if (!body.empty() && (body[0] == '+' || body[0] == '-')) {
        return std::nullopt;
    }
    // Underscores are allowed only between digits (PEP 515).
    bool have_digit = false;
    std::string number;
    number.reserve(body.size());
    for (size_t k = 0; k < body.size(); ++k) {
        char c = body[k];
        if (c == '_') {
            bool prev_digit = !number.empty() && is_digit(number.back());
            bool next_digit = k + 1 < body.size() && is_digit(body[k + 1]);
            if (!prev_digit || !next_digit) return std::nullopt;
            continue;
        }
        number.push_back(c);
        if (is_digit(c)) have_digit = true;
    }
    if (!have_digit) return std::nullopt;

    // strtod accepts hex ("0x1p3") and leading whitespace; Python does not.
    {
        if (number.empty()) return std::nullopt;
        size_t k = 0;
        if (number[k] == '+' || number[k] == '-') ++k;
        if (k + 1 < number.size() && number[k] == '0' &&
            (number[k + 1] == 'x' || number[k + 1] == 'X')) {
            return std::nullopt;
        }
    }
    // Reject trailing junk: strtod must consume the entire string.
    const std::string& n = number;
    char* endp = nullptr;
    double value = std::strtod(n.c_str(), &endp);
    if (!endp || *endp != '\0') return std::nullopt;
    if (std::isnan(value)) return std::nullopt;  // "nan" handled above only
    return negative ? -value : value;
}

std::string py_strip(std::string_view text) {
    size_t b = 0, e = text.size();
    auto space_at = [&](size_t i) {
        auto cp = decode_cp(text, i);
        return cp && (cp->cp < 128 ? is_py_space(static_cast<unsigned char>(cp->cp))
                                   : cp_is_unicode_space(cp->cp));
    };
    while (b < e && space_at(b)) {
        b += decode_cp(text, b)->size;
    }
    while (e > b) {
        // step back one code point
        size_t k = e - 1;
        while (k > b && (static_cast<unsigned char>(text[k]) & 0xC0) == 0x80) --k;
        if (!space_at(k)) break;
        e = k;
    }
    return std::string(text.substr(b, e - b));
}

std::string location_key_normalize(std::string_view tag) {
    // strip namespace: keep text after the last '}', then after the last ':'
    std::string_view text(tag);
    auto brace = text.rfind('}');
    if (brace != std::string_view::npos) text = text.substr(brace + 1);
    auto colon = text.rfind(':');
    if (colon != std::string_view::npos) text = text.substr(colon + 1);

    std::string out;
    for (size_t i = 0; i < text.size();) {
        auto cp = decode_cp(text, i);
        if (!cp) { ++i; continue; }
        char32_t c = cp->cp;
        if (c < 128) {
            if ((c >= '0' && c <= '9') || (c >= 'a' && c <= 'z')) {
                out.push_back(static_cast<char>(c));
            } else if (c >= 'A' && c <= 'Z') {
                out.push_back(static_cast<char>(c + 32));
            }
        } else if (c >= 0x4E00 && c <= 0x9FFF) {
            append_cp(out, c);
        }
        i += cp->size;
    }
    return out;
}

std::string log_local_name(std::string_view tag) {
    std::string_view text(tag);
    auto brace = text.rfind('}');
    if (brace != std::string_view::npos) text = text.substr(brace + 1);
    auto colon = text.rfind(':');
    if (colon != std::string_view::npos) text = text.substr(colon + 1);
    std::string out;
    out.reserve(text.size());
    for (size_t i = 0; i < text.size();) {
        auto cp = decode_cp(text, i);
        if (!cp) { out.push_back('?'); ++i; continue; }
        if (cp->cp < 128) {
            char c = static_cast<char>(cp->cp);
            out.push_back(c >= 'A' && c <= 'Z' ? static_cast<char>(c + 32) : c);
        } else {
            append_cp(out, cp->cp);
        }
        i += cp->size;
    }
    // str.strip()
    size_t b = 0, e = out.size();
    while (b < e && is_py_space(static_cast<unsigned char>(out[b]))) ++b;
    while (e > b && is_py_space(static_cast<unsigned char>(out[e - 1]))) --e;
    return out.substr(b, e - b);
}

std::string html_escape(std::string_view text) {
    std::string out;
    out.reserve(text.size());
    for (char c : text) {
        switch (c) {
            case '&': out += "&amp;"; break;
            case '<': out += "&lt;"; break;
            case '>': out += "&gt;"; break;
            case '"': out += "&quot;"; break;
            case '\'': out += "&#x27;"; break;
            default: out.push_back(c); break;
        }
    }
    return out;
}

std::string format_size(long long size_bytes) {
    if (size_bytes < 0) return "—";  // None sentinel from the caller side
    if (size_bytes >= 1024 * 1024) {
        double val = static_cast<double>(size_bytes) / (1024 * 1024);
        char buf[64];
        if (val != std::trunc(val)) {
            std::snprintf(buf, sizeof(buf), "%.1f M", val);
        } else {
            std::snprintf(buf, sizeof(buf), "%d M", static_cast<int>(val));
        }
        return buf;
    }
    if (size_bytes >= 1024) {
        double val = static_cast<double>(size_bytes) / 1024;
        char buf[64];
        if (val != std::trunc(val)) {
            std::snprintf(buf, sizeof(buf), "%.1f K", val);
        } else {
            std::snprintf(buf, sizeof(buf), "%d K", static_cast<int>(val));
        }
        return buf;
    }
    return std::to_string(size_bytes) + " B";
}

PathParts split_path_parts(std::string_view path) {
    // pathlib: suffix from the final component; a leading dot does not make
    // a suffix (".bashrc" -> suffix ""), "a.b.c" -> suffix ".c".
    auto pos = path.find_last_of('/');
    std::string_view name = pos == std::string_view::npos ? path : path.substr(pos + 1);
    PathParts parts;
    parts.name = std::string(name);
    auto dot = name.rfind('.');
    if (dot == std::string_view::npos || dot == 0) {
        parts.stem = std::string(name);
    } else {
        parts.stem = std::string(name.substr(0, dot));
        parts.suffix = std::string(name.substr(dot));
    }
    return parts;
}

std::optional<std::string> decode_utf8_sig(std::string_view bytes, bool strict) {
    std::string_view s = bytes;
    if (s.size() >= 3 && static_cast<unsigned char>(s[0]) == 0xEF &&
        static_cast<unsigned char>(s[1]) == 0xBB &&
        static_cast<unsigned char>(s[2]) == 0xBF) {
        s = s.substr(3);
    }
    return decode_utf8(s, strict);
}

std::optional<std::string> decode_utf8(std::string_view bytes, bool strict) {
    std::string_view s = bytes;
    std::string out;
    out.reserve(s.size());
    for (size_t i = 0; i < s.size();) {
        unsigned char c = static_cast<unsigned char>(s[i]);
        size_t len = 0;
        if (c < 0x80) len = 1;
        else if ((c & 0xE0) == 0xC0) len = 2;
        else if ((c & 0xF0) == 0xE0) len = 3;
        else if ((c & 0xF8) == 0xF0) len = 4;
        if (len == 0 || i + len > s.size()) {
            if (strict) return std::nullopt;
            // one U+FFFD per maximal invalid subsequence (CPython 'replace')
            out += "\xEF\xBF\xBD";
            size_t k = i + 1;
            while (k < s.size() &&
                   (static_cast<unsigned char>(s[k]) & 0xC0) == 0x80) {
                ++k;
            }
            i = k;
            continue;
        }
        bool ok = true;
        for (size_t k = 1; k < len; ++k) {
            if ((static_cast<unsigned char>(s[i + k]) & 0xC0) != 0x80) {
                ok = false;
                break;
            }
        }
        if (!ok) {
            if (strict) return std::nullopt;
            out += "\xEF\xBF\xBD";
            size_t k = i + 1;
            while (k < s.size() &&
                   (static_cast<unsigned char>(s[k]) & 0xC0) == 0x80) {
                ++k;
            }
            i = k;
            continue;
        }
        out.append(s.substr(i, len));
        i += len;
    }
    return out;
}

}  // namespace pwb::ingest
