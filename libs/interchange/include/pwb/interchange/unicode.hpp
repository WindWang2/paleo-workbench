#pragma once

// pwb::interchange — Unicode support for path-safety checks (conv-14).
//
// Faithful C++ counterparts of the two unicodedata operations the Python
// interchange layer relies on: NFC normalization (unicodedata.normalize)
// and full case folding (str.casefold). Tables are generated from the same
// system Python that freezes the oracle
// (tools/oracle/generate_interchange_fixtures.py -> src/unicode_tables.inc),
// so accept/reject decisions cannot drift between the two sides.
// Qt-free, Python-free at run time.

#include <string>
#include <string_view>

namespace pwb::interchange {

// UTF-8 <-> code point conversion. Invalid bytes decode as U+FFFD (the
// oracle only feeds well-formed UTF-8, matching Python's str semantics).
std::u32string utf8_to_codepoints(std::string_view text);
std::string codepoints_to_utf8(const std::u32string& cps);

// Number of code points in a UTF-8 string (Python len(str) semantics).
std::size_t codepoint_length(std::string_view text);

std::u32string nfc_normalize(const std::u32string& cps);
std::u32string casefold(const std::u32string& cps);

std::string nfc_normalize_utf8(std::string_view text);
std::string casefold_utf8(std::string_view text);

}  // namespace pwb::interchange
