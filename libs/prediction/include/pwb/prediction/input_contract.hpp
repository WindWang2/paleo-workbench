// Port of the pure half of paleo_workbench/prediction/input_contract.py
// (CONV-21): parse_input_schema normalization. The resolver/enforcement
// half of that module drives services and geoviz file readers — it is not
// part of this kernel (21-decisions.md D1).
#pragma once

#include "pwb/domain/json.hpp"

namespace pwb::prediction {

using pwb::domain::Json;

// _RECOGNIZED_SCHEMA_KEYS — kept for parity checks against the resolver
// that stays in Python.
inline constexpr const char* kRecognizedSchemaKeys[] = {
    "required_asset_types",
    "asset_types",
    "optional_asset_types",
    "required_curves",
    "curves",
    "require_target_horizon",
    "require_correlation",
    "require_horizon_interpretation",
    "require_fault_interpretation",
    "min_wells",
};

// parse_input_schema(schema) -> normalized dict. schema: JSON object or
// null. Non-mapping truthy values behave like Python (dict() coercion
// failure) — outside the frozen domain they raise.
Json parse_input_schema(const Json& schema);

}  // namespace pwb::prediction
