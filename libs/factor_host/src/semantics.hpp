#pragma once

// Internal shared Python-semantics helpers for the factor_host translation
// units (not part of the installed surface). Kept in one place so the
// Python-truthiness / str.strip() rules cannot drift apart between leaves.

#include <pwb/domain/json.hpp>

#include <string>

namespace pwb::factor_host::detail {

using pwb::domain::Json;

// Python truthiness for the JSON values the port inspects
// (None / 0 / 0.0 / "" / empty array / empty object / false are falsy).
bool json_truthy(const Json* value);

// str.strip() with Python's full str.isspace() set: ASCII 0x09-0x0D,
// 0x1C-0x1F, 0x20 plus the multibyte whitespace (U+0085, U+00A0, U+1680,
// U+2000-200A, U+2028, U+2029, U+202F, U+205F, U+3000).
std::string python_strip(const std::string& text);

// The whitespace set float()/int() accept around a numeric literal: same as
// python_strip minus \x1C-\x1F (CPython's numeric parsers reject those even
// though str.strip() removes them — verified against the interpreter).
std::string python_strip_number(const std::string& text);

// Python repr() of a str for error/warning text: prefers single quotes,
// switches to double quotes when the text contains ' but not ".
std::string python_repr_string(const std::string& text);

}  // namespace pwb::factor_host::detail
