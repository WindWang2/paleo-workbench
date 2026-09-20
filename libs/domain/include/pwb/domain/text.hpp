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

}  // namespace pwb::domain
