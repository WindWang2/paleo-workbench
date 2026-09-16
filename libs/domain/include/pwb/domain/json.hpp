// JSON conventions for the data kernel.
//
// Every persistence surface uses nlohmann::ordered_json so object key ORDER
// is preserved end-to-end: Python writes declared fields in model order with
// extras trailing, and the C++ side must reproduce that layout byte-for-byte
// (modulo insignificant whitespace) on round-trip.
#pragma once

#include <nlohmann/json.hpp>

namespace pwb::domain {

using Json = nlohmann::ordered_json;

// Type-sensitive JSON comparison (test-plan §3):
//  - objects: key order irrelevant, key SETS must match exactly
//  - arrays: order preserved, compared element-wise
//  - numbers: int vs float is a TYPE difference (1 != 1.0); same-type
//    compares by value
//  - null / missing key are distinct states and never coerced
bool json_semantically_equal(const Json& left, const Json& right);

// Diff path tracker for readable mismatch messages.
struct JsonDiff {
    bool equal = true;
    std::string path;    // first differing member, "$" rooted
    std::string reason;

    static JsonDiff ok() { return {}; }
    static JsonDiff fail(std::string path, std::string reason) {
        return {false, std::move(path), std::move(reason)};
    }
};

JsonDiff json_semantic_diff(const Json& left, const Json& right,
                            const std::string& path = "$");

// UTF-8 JSON text with Python-compatible formatting:
// ensure_ascii=false, indent=2, "\n" terminator (json.dumps + file write).
std::string dump_json_python_compatible(const Json& value);

// Python json.dumps(obj, ensure_ascii=False, indent=2) without trailing
// newline (matches manager.execute_save payload string).
std::string dump_json_compact_header(const Json& value);

}  // namespace pwb::domain
