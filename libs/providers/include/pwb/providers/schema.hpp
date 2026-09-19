// Parameters schema validation — C++ port of validate_parameters from
// paleo_workbench/providers/execution.py (#1178 subset).
//
// Supported, recursively at every object/array nesting level: type (including
// list-form unions), required, properties, enum, minimum/maximum,
// minItems/maxItems, items, additionalProperties. additionalProperties is
// only enforced when the schema explicitly declares it false. Unknown type
// names are reported instead of silently passing. Problem strings are
// byte-identical to the Python oracle — including Python type names
// (dict/list/str/int/float/bool/NoneType) and Python reprs of values.
#pragma once

#include <pwb/domain/json.hpp>

#include <string>
#include <vector>

namespace pwb::providers {

using Json = pwb::domain::Json;

// Validate `parameters` against the JSON-schema subset the SDK allows.
// label is the root path ("parameters" by default, "arguments" for harness
// action specs).
std::vector<std::string> validate_parameters(const Json& schema, const Json& parameters,
                                             const std::string& label = "parameters");

// Python type(value).__name__ for a JSON value (message parity).
std::string json_python_type_name(const Json& value);
// Python repr() of a JSON value ('x', 3, 3.5, True, None, ['a', 'b']).
std::string python_repr(const Json& value);
// Python str() of a JSON value (strings unquoted).
std::string python_str(const Json& value);

}  // namespace pwb::providers
