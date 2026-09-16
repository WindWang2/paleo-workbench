// JSON semantic comparator (test-plan.md §3):
//  - objects: key order irrelevant, key SETS must match exactly
//    (missing key != null key; defaults never appear in trees)
//  - arrays: order preserved, compared element-wise
//  - numbers: int vs float is a TYPE difference (1 != 1.0)
//  - strings: exact UTF-8 comparison
#pragma once

#include <nlohmann/json.hpp>

#include <optional>
#include <string>

namespace pwb_test {

using nlohmann::ordered_json;

// Nullopt when semantically equal; otherwise a "$"-rooted diff description.
inline std::optional<std::string> json_compare(const ordered_json& left,
                                               const ordered_json& right,
                                               const std::string& path = "$") {
    if (left.type() != right.type()) {
        return path + ": type mismatch (" +
               std::string(left.type_name()) + " vs " +
               std::string(right.type_name()) + ")";
    }
    if (left.is_object()) {
        for (auto it = left.begin(); it != left.end(); ++it) {
            if (!right.contains(it.key())) {
                return path + ": key '" + it.key() + "' missing on right";
            }
        }
        for (auto it = right.begin(); it != right.end(); ++it) {
            if (!left.contains(it.key())) {
                return path + ": key '" + it.key() + "' missing on left";
            }
        }
        for (auto it = left.begin(); it != left.end(); ++it) {
            if (auto diff =
                    json_compare(it.value(), right.at(it.key()),
                                 path + "." + it.key())) {
                return diff;
            }
        }
        return std::nullopt;
    }
    if (left.is_array()) {
        if (left.size() != right.size()) {
            return path + ": array size " + std::to_string(left.size()) +
                   " vs " + std::to_string(right.size());
        }
        for (std::size_t i = 0; i < left.size(); ++i) {
            if (auto diff = json_compare(left[i], right[i],
                                         path + "[" + std::to_string(i) +
                                             "]")) {
                return diff;
            }
        }
        return std::nullopt;
    }
    if (left != right) {
        return path + ": value mismatch (" + left.dump() + " vs " +
               right.dump() + ")";
    }
    return std::nullopt;
}

}  // namespace pwb_test
