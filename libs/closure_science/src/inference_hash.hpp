#pragma once

// Canonical snapshot encoding shared with the Python prediction service's
// _snapshot_hash (json.dumps(payload, sort_keys=True, ensure_ascii=False)
// with DEFAULT separators ", " / ": " — E-1: a compact dump hashed
// differently, so mixed Python/C++ snapshot generations were always judged
// stale). Internal test seam: byte parity with Python is pinned by
// closure_science_tests/inference_hash_test.cpp.

#include <map>
#include <string>

#include <nlohmann/json.hpp>

namespace pwb::closure_science::detail {

[[nodiscard]] inline std::string dump_canonical(const nlohmann::json& value) {
    if (value.is_object()) {
        std::map<std::string, std::string> encoded;
        for (auto it = value.begin(); it != value.end(); ++it) {
            encoded[it.key()] = dump_canonical(it.value());
        }
        std::string out = "{";
        bool first = true;
        for (const auto& [key, encoded_value] : encoded) {
            if (!first) out += ", ";
            first = false;
            out += "\"" + key + "\": " + encoded_value;
        }
        return out + "}";
    }
    if (value.is_array()) {
        std::string out = "[";
        bool first = true;
        for (const auto& item : value) {
            if (!first) out += ", ";
            first = false;
            out += dump_canonical(item);
        }
        return out + "]";
    }
    return value.dump();
}

}  // namespace pwb::closure_science::detail
