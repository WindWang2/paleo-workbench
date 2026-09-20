#include "pwb/domain/text.hpp"

#include "lower_table.inc"

#include <algorithm>

namespace pwb::domain {

namespace {

// Decode one UTF-8 code point at s[i]; 0-length (invalid) consumes 1 byte so
// callers can pass bytes through unchanged instead of wedging on bad input.
struct Decoded {
    char32_t cp;
    std::size_t size;
    bool valid;
};

Decoded decode_cp(std::string_view s, std::size_t i) {
    const auto c = static_cast<unsigned char>(s[i]);
    if (c < 0x80) return {c, 1, true};
    std::size_t len = 0;
    char32_t cp = 0;
    if ((c & 0xE0) == 0xC0) { len = 2; cp = c & 0x1F; }
    else if ((c & 0xF0) == 0xE0) { len = 3; cp = c & 0x0F; }
    else if ((c & 0xF8) == 0xF0) { len = 4; cp = c & 0x07; }
    else return {0, 1, false};
    if (i + len > s.size()) return {0, 1, false};
    for (std::size_t k = 1; k < len; ++k) {
        const auto cc = static_cast<unsigned char>(s[i + k]);
        if ((cc & 0xC0) != 0x80) return {0, 1, false};
        cp = (cp << 6) | (cc & 0x3F);
    }
    return {cp, len, true};
}

const lower_table::LowerEntry* find_entry(const lower_table::LowerEntry* begin,
                                          const lower_table::LowerEntry* end,
                                          char32_t cp) {
    const auto* it = std::lower_bound(
        begin, end, cp,
        [](const lower_table::LowerEntry& e, char32_t v) {
            return e.cp < v;
        });
    return (it != end && it->cp == cp) ? it : nullptr;
}

std::string fold_with(std::string_view text, const lower_table::LowerEntry* begin,
                      const lower_table::LowerEntry* end) {
    std::string out;
    out.reserve(text.size());
    std::size_t i = 0;
    while (i < text.size()) {
        const Decoded d = decode_cp(text, i);
        if (!d.valid) {
            out.push_back(text[i]);
            i += 1;
            continue;
        }
        if (const auto* e = find_entry(begin, end, d.cp)) {
            out += e->folded;
        } else {
            out.append(text.substr(i, d.size));
        }
        i += d.size;
    }
    return out;
}

}  // namespace

std::string lowercase_utf8(std::string_view text) {
    return fold_with(text, std::begin(lower_table::kLower),
                     std::end(lower_table::kLower));
}

std::string casefold_utf8(std::string_view text) {
    return fold_with(text, std::begin(lower_table::kCasefold),
                     std::end(lower_table::kCasefold));
}

}  // namespace pwb::domain
