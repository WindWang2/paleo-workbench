// Internal helpers replicating the Python literal semantics the frozen
// error messages depend on (CONV-06 D4). Not part of the public surface.
#pragma once

#include <string>

#include <pwb/domain/json.hpp>

namespace pwb::workflow_spec::detail {

// repr() of a JSON scalar/list — Python single-quote strings, None/True/
// False, ['a', 'b'] lists. Dictionaries inside `value` render through their
// items in insertion order (only the frozen message paths consume this).
[[nodiscard]] std::string py_repr(const domain::Json& value);

// str() of a JSON number the way Python str() renders it: ints without a
// fractional part, floats with repr semantics (1.0 keeps ".0").
[[nodiscard]] std::string py_str_number(const domain::Json& value);

// type(value).__name__ for the JSON-schema subset messages: dict / list /
// str / int / float / bool / NoneType.
[[nodiscard]] std::string py_type_name(const domain::Json& value);

// Python str() of a JSON scalar for non-string types (True, None, 3, 1.5).
[[nodiscard]] std::string py_str_scalar(const domain::Json& value);

// Double rendering matching Python repr() for the values that reach frozen
// messages: shortest round-trip digits, ".0" appended when integral, no
// trailing garbage.
[[nodiscard]] std::string py_repr_double(double value);

// Coercions mirroring from_dict's int()/float()/bool() applications.
[[nodiscard]] int json_to_int(const domain::Json& value, const char* field);
[[nodiscard]] double json_to_double(const domain::Json& value, const char* field);
// bool(x) Python truthiness (never throws).
[[nodiscard]] bool json_to_bool(const domain::Json& value);

// Required-key access mirroring data["key"] (KeyError -> ModelError).
[[nodiscard]] const domain::Json& required_key(const domain::Json& data,
                                               const char* key);

}  // namespace pwb::workflow_spec::detail
