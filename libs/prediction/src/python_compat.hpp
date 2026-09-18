// CPython semantics shared by the prediction contract cores. Each helper
// replicates one concrete CPython behavior the frozen oracle depends on
// (truthiness, str()/repr(), str.strip(), pathlib stem, re \w).
// Internal to pwb_prediction — not an installed header.
#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <string_view>

#include "pwb/domain/json.hpp"

namespace pwb::prediction::detail {

using pwb::domain::Json;

// Python truthiness: null/False/0/""/empty containers are falsy.
bool py_truthy(const Json& v);

// `a or b` (returns the operand, not a bool).
const Json& py_or(const Json& a, const Json& b);

// str(x): strings pass through; True/False/None literals; numbers via the
// shortest round-trip representation; containers via repr().
std::string py_str(const Json& v);

// repr(x): CPython string quoting (prefer ', flip to " when the string
// contains ' and no "), escapes for \n \r \t \\ and <0x20/0x7f-0xa0,
// recursive container rendering. Non-ASCII printable code points pass
// through unescaped (unicodedata isprintable approximation — the oracle
// only freezes ASCII-printable and quote-flip cases).
std::string py_repr(const Json& v);

// str.strip() over the complete CPython str.isspace() set — wider than
// pwb::ingest::py_strip (adds 0x1C-0x1F and 0x85 which Python strips).
std::string py_strip(std::string_view text);

// float(value) + math.isfinite filter, i.e. _finite_number: JSON number ->
// value, bool -> 1.0/0.0, string -> Python float() parse (inf/nan/PEP515
// semantics via pwb::ingest), anything else -> nullopt.
std::optional<double> py_finite_number(const Json& v);

// int(value) as used by merged_sample_count accumulation: bool/int/float
// (trunc toward zero)/decimal string. Throws std::runtime_error carrying
// the CPython ValueError/TypeError text.
long long py_int(const Json& v);

// float(value) WITHOUT the isfinite filter — NaN/inf are valid results
// (used by _has_finite_ring where only NaN is rejected downstream).
std::optional<double> py_float_raw(const Json& v);

// round(v, 6): correctly-rounded six-decimal half-even value, matching
// CPython round() (exact decimal rounding of the binary value, then the
// nearest double).
double py_round6(double v);

// math.isclose(a, b) with the Python defaults rel_tol=1e-9 and the caller's
// abs_tol; a == b is accepted first (covers infinities).
bool py_isclose(double a, double b, double abs_tol);

// pathlib stem/name of a POSIX-style path string, incl. trailing-slash
// normalization and the "dot must sit strictly inside the name" rule
// (".." and "a." have no suffix — this differs from ingest's
// split_path_parts on those edges, which is why this port is separate).
std::string py_path_stem(std::string_view path);
std::string py_path_name(std::string_view path);

// Python re \w on a decoded code point: '_' plus Unicode categories L*/N*.
// The category ranges live in word_char_ranges.inc (generated from the
// real unicodedata database by the oracle generator).
bool is_word_char(char32_t cp);

// re.sub(r"[^\w]", "", text, flags=re.UNICODE) over UTF-8 text; undecodable
// bytes are dropped (input is already JSON-decoded, so this cannot fire
// for oracle-conformant strings).
std::string keep_word_chars(std::string_view text);

// CPython type name for `'<type>' object has no attribute` messages.
std::string py_type_name(const Json& v);

}  // namespace pwb::prediction::detail
