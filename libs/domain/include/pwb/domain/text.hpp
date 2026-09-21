// Unicode text helpers for the Qt-free cores (pwb_domain).
//
// Python semantics: the lowering table is generated from real str.lower()
// by tools/oracle/generate_domain_lower_table.py — the same freeze contract
// as libs/interchange's unicode_tables.inc, so C++ search/normalization
// cannot drift from the Python reference (#1391).
#pragma once

#include <string>
#include <string_view>

namespace pwb::domain {

// Python str.lower() over UTF-8 input. Ill-formed bytes are passed through
// unchanged (callers operate on already-decoded text; Python str.split /
// lower never sees invalid UTF-8 because decode happened upstream).
std::string lowercase_utf8(std::string_view text);

// Python str.casefold() over UTF-8 input — the stronger fold Python uses
// for case-insensitive ordering (e.g. saved-filter name sorting).
std::string casefold_utf8(std::string_view text);

// ASCII whitespace trim (" \t\n\r\v\f") — the shared home for the
// per-TU `strip`/`strip_copy` clones (#1392). For paths/tags/keys that
// only carry ASCII whitespace.
std::string strip_ascii(std::string_view text);

// Python str.strip() — Unicode whitespace set (incl. U+3000 ideographic
// space, U+00A0, U+2028/29, …). Use for strings Python authored.
std::string python_strip(std::string_view text);

// ASCII-only lowering — byte-wise A-Z fold, no Unicode semantics. The
// shared home for the per-TU `lower_ascii` clones (#1392).
std::string lower_ascii(std::string_view text);

// Decode one UTF-8 code point at text[i]; an invalid sequence reports
// size=1/valid=false so callers can pass bytes through instead of wedging
// on bad input. i must be < text.size().
struct Utf8CodePoint {
    char32_t cp;
    std::size_t size;
    bool valid;
};
Utf8CodePoint decode_utf8_at(std::string_view text, std::size_t i);

}  // namespace pwb::domain
