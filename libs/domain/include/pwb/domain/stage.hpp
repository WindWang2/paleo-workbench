// Data lifecycle stage vocabulary (catalog/models.py DataStage).
#pragma once

#include <optional>
#include <string>
#include <string_view>

namespace pwb::domain {

enum class DataStage { Raw, Derived, Intermediate, Output };

inline constexpr std::string_view to_string(DataStage stage) {
    switch (stage) {
        case DataStage::Raw: return "raw";
        case DataStage::Derived: return "derived";
        case DataStage::Intermediate: return "intermediate";
        case DataStage::Output: return "output";
    }
    return "raw";
}

// Parses the lowercase wire vocabulary. Unknown values return nullopt —
// callers decide between rejection (write side) and preserve-with-diagnostic
// (read side), matching the schema-map semantics.
inline std::optional<DataStage> data_stage_from_string(
    std::string_view value) {
    if (value == "raw") return DataStage::Raw;
    if (value == "derived") return DataStage::Derived;
    if (value == "intermediate") return DataStage::Intermediate;
    if (value == "output") return DataStage::Output;
    return std::nullopt;
}

}  // namespace pwb::domain
