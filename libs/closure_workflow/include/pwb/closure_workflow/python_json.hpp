#pragma once

// Python json.dumps(payload, sort_keys=True, ensure_ascii=False) with the
// DEFAULT (", "/": ") separators and indent=None — the byte stream the
// map_product scientific fingerprint hashes (map_product.py L65-66).
// Byte-parity twin of the file-local encoder in
// libs/workflow_runtime/src/versioning.cpp (kept in sync by oracle
// fixtures; the encoder there is deliberately untouched — its bytes are
// frozen by the CONV-33 oracle).
//
// Covers the JSON value model: null / bool / integer / double (Python
// repr) / string (ensure_ascii=False escapes) / array / object (keys
// sorted byte-wise at every level). default=str coercion of unknown
// scalars cannot arise from a Json tree.
//
// Qt-free, Python-free.

#include <pwb/domain/json.hpp>

#include <string>

namespace pwb::closure_workflow {

[[nodiscard]] std::string python_dumps_sorted(const pwb::domain::Json& value);

// json.dumps(payload, ensure_ascii=False) WITHOUT sort_keys — insertion
// order preserved (ordered_json declaration order). This is the byte
// stream compile_map_production writes to the staged payload file
// (compile_map_production.py json.dump(payload, handle,
// ensure_ascii=False)).
[[nodiscard]] std::string python_dumps(const pwb::domain::Json& value);

}  // namespace pwb::closure_workflow
