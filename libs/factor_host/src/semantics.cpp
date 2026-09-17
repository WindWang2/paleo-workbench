#include "semantics.hpp"

namespace pwb::factor_host::detail {

bool json_truthy(const Json* value) {
    if (value == nullptr || value->is_null()) return false;
    if (value->is_boolean()) return value->get<bool>();
    if (value->is_number()) return value->get<double>() != 0.0;
    if (value->is_string()) return !value->get<std::string>().empty();
    if (value->is_array()) return !value->empty();
    if (value->is_object()) return !value->empty();
    return false;
}

namespace {

// One UTF-8 code point at pos → is it Python whitespace? `numeric_set`
// excludes \x1C-\x1F (float()/int() reject them; str.strip() removes them).
bool space_at(const std::string& s, std::size_t pos, std::size_t& advance,
              bool numeric_set) {
    const auto byte_at = [&s](std::size_t i) {
        return static_cast<unsigned char>(s[i]);
    };
    const unsigned char b0 = byte_at(pos);
    if (b0 < 0x80) {
        advance = 1;
        if (b0 >= 0x09 && b0 <= 0x0D) return true;
        if (b0 == 0x20) return true;
        return !numeric_set && b0 >= 0x1C && b0 <= 0x1F;
    }
    const std::size_t remaining = s.size() - pos;
    // Encode the multibyte whitespace set explicitly (see header).
    if (b0 == 0xC2 && remaining >= 2) {
        const unsigned char b1 = byte_at(pos + 1);
        if (b1 == 0x85 || b1 == 0xA0) {  // U+0085 NEL, U+00A0 NBSP
            advance = 2;
            return true;
        }
    }
    if (b0 == 0xE1 && remaining >= 3 && byte_at(pos + 1) == 0x9A &&
        byte_at(pos + 2) == 0x80) {  // U+1680
        advance = 3;
        return true;
    }
    if (b0 == 0xE2 && remaining >= 3 && byte_at(pos + 1) == 0x80) {
        const unsigned char b2 = byte_at(pos + 2);
        if ((b2 >= 0x80 && b2 <= 0x8A) || b2 == 0xA8 || b2 == 0xA9 ||
            b2 == 0xAF) {  // U+2000-200A, U+2028/2029, U+202F
            advance = 3;
            return true;
        }
    }
    if (b0 == 0xE2 && remaining >= 3 && byte_at(pos + 1) == 0x81 &&
        byte_at(pos + 2) == 0x9F) {  // U+205F
        advance = 3;
        return true;
    }
    if (b0 == 0xE3 && remaining >= 3 && byte_at(pos + 1) == 0x80 &&
        byte_at(pos + 2) == 0x80) {  // U+3000
        advance = 3;
        return true;
    }
    advance = 1;
    return false;
}

std::string strip_impl(const std::string& text, bool numeric_set) {
    std::size_t begin = 0;
    std::size_t end = text.size();
    while (begin < end) {
        std::size_t advance = 0;
        if (!space_at(text, begin, advance, numeric_set)) break;
        begin += advance;
    }
    while (end > begin) {
        // Walk back one full code point.
        std::size_t start = end - 1;
        while (start > begin &&
               (static_cast<unsigned char>(text[start]) & 0xC0) == 0x80) {
            --start;
        }
        std::size_t advance = 0;
        if (!space_at(text, start, advance, numeric_set)) break;
        end = start;
    }
    return text.substr(begin, end - begin);
}

}  // namespace

std::string python_strip(const std::string& text) {
    return strip_impl(text, false);
}

std::string python_strip_number(const std::string& text) {
    return strip_impl(text, true);
}

std::string python_repr_string(const std::string& text) {
    const bool has_single = text.find('\'') != std::string::npos;
    const bool has_double = text.find('"') != std::string::npos;
    const char quote = has_single && !has_double ? '"' : '\'';
    std::string out;
    out += quote;
    for (char c : text) {
        if (c == '\\' || c == quote) out += '\\';
        out += c;
    }
    out += quote;
    return out;
}

}  // namespace pwb::factor_host::detail
