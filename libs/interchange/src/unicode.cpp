// NFC normalization + full case folding over generated Unicode tables.
// Algorithm per UAX #15: canonical decomposition -> canonical ordering ->
// canonical composition (Hangul handled by formula, as in the tables' source).

#include <pwb/interchange/unicode.hpp>

#include "unicode_tables.inc"

#include <algorithm>
#include <cstdint>

namespace pwb::interchange {

std::u32string utf8_to_codepoints(std::string_view text) {
    std::u32string out;
    out.reserve(text.size());
    std::size_t i = 0;
    while (i < text.size()) {
        const auto lead = static_cast<unsigned char>(text[i]);
        std::size_t extra = 0;
        std::uint32_t cp = 0;
        if (lead < 0x80) {
            cp = lead;
        } else if ((lead & 0xE0) == 0xC0) {
            extra = 1;
            cp = lead & 0x1F;
        } else if ((lead & 0xF0) == 0xE0) {
            extra = 2;
            cp = lead & 0x0F;
        } else if ((lead & 0xF8) == 0xF0) {
            extra = 3;
            cp = lead & 0x07;
        } else {
            out.push_back(0xFFFD);
            ++i;
            continue;
        }
        if (i + extra >= text.size()) {
            out.push_back(0xFFFD);
            ++i;
            continue;
        }
        bool valid = true;
        for (std::size_t k = 1; k <= extra; ++k) {
            const auto cont = static_cast<unsigned char>(text[i + k]);
            if ((cont & 0xC0) != 0x80) {
                valid = false;
                break;
            }
            cp = (cp << 6) | (cont & 0x3F);
        }
        if (!valid) {
            out.push_back(0xFFFD);
            ++i;
            continue;
        }
        i += extra + 1;
        out.push_back(cp);
    }
    return out;
}

std::string codepoints_to_utf8(const std::u32string& cps) {
    std::string out;
    out.reserve(cps.size() * 3);
    for (const char32_t cp : cps) {
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
    return out;
}

std::size_t codepoint_length(std::string_view text) {
    std::size_t n = 0;
    for (const unsigned char byte : text) {
        if ((byte & 0xC0) != 0x80) {
            ++n;
        }
    }
    return n;
}

namespace {

int ccc_of(std::uint32_t cp) {
    const auto* end = std::end(unicode_tables::kCccRanges);
    const auto* it = std::lower_bound(
        std::begin(unicode_tables::kCccRanges), end, cp,
        [](const unicode_tables::CccRange& range, std::uint32_t value) {
            return range.last < value;
        });
    if (it != end && it->first <= cp && cp <= it->last) {
        return it->ccc;
    }
    return 0;
}

const unicode_tables::DecompEntry* find_decomp(std::uint32_t cp) {
    const auto* end = std::end(unicode_tables::kCanonicalDecompositions);
    const auto* it = std::lower_bound(
        std::begin(unicode_tables::kCanonicalDecompositions), end, cp,
        [](const unicode_tables::DecompEntry& entry, std::uint32_t value) {
            return entry.cp < value;
        });
    if (it != end && it->cp == cp) {
        return it;
    }
    return nullptr;
}

char32_t compose_pair(std::uint32_t a, std::uint32_t b) {
    const auto* end = std::end(unicode_tables::kCanonicalCompositions);
    const auto* it = std::lower_bound(
        std::begin(unicode_tables::kCanonicalCompositions), end,
        std::pair<std::uint32_t, std::uint32_t>{a, b},
        [](const unicode_tables::ComposeEntry& entry,
           const std::pair<std::uint32_t, std::uint32_t>& key) {
            return std::pair<std::uint32_t, std::uint32_t>{entry.a, entry.b} < key;
        });
    if (it != end && it->a == a && it->b == b) {
        return static_cast<char32_t>(it->cp);
    }
    return 0;
}

void decompose_cp(char32_t cp, std::u32string& out) {
    // Hangul syllables: algorithmic decomposition (LV + optional T).
    if (cp >= 0xAC00 && cp <= 0xD7A3) {
        const int s_index = static_cast<int>(cp) - 0xAC00;
        out.push_back(static_cast<char32_t>(0x1100 + s_index / 588));
        out.push_back(static_cast<char32_t>(0x1161 + (s_index % 588) / 28));
        const int t = s_index % 28;
        if (t != 0) {
            out.push_back(static_cast<char32_t>(0x11A7 + t));
        }
        return;
    }
    if (const auto* entry = find_decomp(cp)) {
        for (int i = 0; i < entry->n; ++i) {
            decompose_cp(static_cast<char32_t>(entry->seq[i]), out);
        }
        return;
    }
    out.push_back(cp);
}

void canonical_order(std::u32string& text) {
    for (std::size_t i = 1; i < text.size(); ++i) {
        const int cci = ccc_of(text[i]);
        if (cci == 0) {
            continue;
        }
        for (std::size_t j = i; j > 0; --j) {
            const int ccj = ccc_of(text[j - 1]);
            if (ccj == 0 || ccj <= cci) {
                break;
            }
            std::swap(text[j - 1], text[j]);
        }
    }
}

char32_t hangul_compose(char32_t a, char32_t b) {
    // LV + T -> LVT
    if (a >= 0xAC00 && a <= 0xD7A3 && (a - 0xAC00) % 28 == 0 && b >= 0x11A8
        && b <= 0x11C2) {
        return static_cast<char32_t>(a + (b - 0x11A7));
    }
    // L + V -> LV
    if (a >= 0x1100 && a <= 0x1112 && b >= 0x1161 && b <= 0x1175) {
        return static_cast<char32_t>(0xAC00 + ((a - 0x1100) * 21 + (b - 0x1161)) * 28);
    }
    return 0;
}

}  // namespace

std::u32string nfc_normalize(const std::u32string& cps) {
    std::u32string decomposed;
    decomposed.reserve(cps.size());
    for (const char32_t cp : cps) {
        decompose_cp(cp, decomposed);
    }
    canonical_order(decomposed);
    if (decomposed.size() <= 1) {
        return decomposed;
    }

    std::u32string out;
    out.reserve(decomposed.size());
    out.push_back(decomposed[0]);
    std::size_t starter_pos = 0;
    int last_cc = ccc_of(decomposed[0]);
    for (std::size_t i = 1; i < decomposed.size(); ++i) {
        const char32_t cp = decomposed[i];
        const int cc = ccc_of(cp);
        char32_t composed = 0;
        if (cc == 0) {
            if (last_cc == 0) {
                // Starter+starter compositions (Tamil/Bengali table pairs,
                // Hangul L+V/LV+T) only apply when adjacent starters.
                composed = compose_pair(out[starter_pos], cp);
                if (composed == 0) {
                    composed = hangul_compose(out[starter_pos], cp);
                }
            }
        } else if (last_cc < cc) {
            composed = compose_pair(out[starter_pos], cp);
        }
        if (composed != 0) {
            out[starter_pos] = composed;
            // Consumed characters do not update last_cc: the blocking rule
            // looks at the CCC of the last character that REMAINS in the
            // output (UAX #15), so a composed-away mark never blocks.
        } else {
            if (cc == 0) {
                starter_pos = out.size();
            }
            out.push_back(cp);
            last_cc = cc;
        }
    }
    return out;
}

std::u32string casefold(const std::u32string& cps) {
    const auto* begin = std::begin(unicode_tables::kCasefold);
    const auto* end = std::end(unicode_tables::kCasefold);
    std::u32string out;
    for (const char32_t cp : cps) {
        const auto* it = std::lower_bound(
            begin, end, cp,
            [](const unicode_tables::FoldEntry& entry, std::uint32_t value) {
                return entry.cp < value;
            });
        if (it != end && it->cp == cp) {
            const std::u32string folded = utf8_to_codepoints(it->folded);
            out.insert(out.end(), folded.begin(), folded.end());
        } else {
            out.push_back(cp);
        }
    }
    return out;
}

std::string nfc_normalize_utf8(std::string_view text) {
    return codepoints_to_utf8(nfc_normalize(utf8_to_codepoints(text)));
}

std::string casefold_utf8(std::string_view text) {
    return codepoints_to_utf8(casefold(utf8_to_codepoints(text)));
}

}  // namespace pwb::interchange
