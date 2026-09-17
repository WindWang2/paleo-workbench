#pragma once

// Canonical JSON encoding byte-identical to
//   json.dumps(payload, sort_keys=True, ensure_ascii=False,
//              separators=(",", ":"), default=str)
// which stable_sha256 (interpolation_fingerprint.py) hashes. nlohmann::dump
// cannot be used: its float formatting and key ordering differ from Python.
// Covers exactly the value types a fingerprint payload can contain
// (null / bool / integer / double / string / array / object).
// Qt-free, Python-free, numpy-free.

#include <pwb/domain/json.hpp>

#include <optional>
#include <string>

namespace pwb::factor_host {

using pwb::domain::Json;

// Python repr() for doubles: shortest round-trip digits, fixed notation for
// decimal exponents in [-4, 16), scientific with e±NN (two exponent digits)
// otherwise; NaN / Infinity / -Infinity / -0.0 spellings included.
std::string python_repr_double(double value);

// float("...") coercion with Python semantics for the string forms a JSON
// document can carry ("2.5", "1e3", "inf", "nan", surrounding whitespace).
// Hex floats, nan(payload), underscore separators and non-ASCII digits are
// rejected exactly like Python — except underscore separators and fullwidth
// (Nd) digits, which CPython's numeric transform DOES accept; we reject
// them (documented divergence, never produced by the host document model).
std::optional<double> python_float_from_string(const std::string& text);

// str() coercion of a JSON scalar (Python str(True) == "True",
// str(1.5) == "1.5", strings pass through).
std::string python_str_scalar(const Json& value);

// Canonical encoding (sorted keys byte-wise = Python code-point order,
// compact separators, non-ASCII kept as raw UTF-8).
std::string canonical_encode(const Json& value);

}  // namespace pwb::factor_host
