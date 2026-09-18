// Port of paleo_workbench/prediction/spatial_result.py (CONV-21).
// Spatial prediction result contract: type detection, polygon extraction,
// structural validation, bounded summaries and map-compilability. Frozen
// against the Python oracle (fixtures/prediction_contract_oracle.json).
#pragma once

#include "pwb/domain/json.hpp"
#include "pwb/prediction/model_package.hpp"  // spatial type constants

namespace pwb::prediction {

using pwb::domain::Json;

// spatial_type_of(payload) -> spatial_output_type string. Non-mapping
// truthy payloads raise AttributeError like the Python source.
std::string spatial_type_of(const Json& payload);

// extract_polygon_features(payload) -> JSON array of GeoJSON-like
// Polygon/MultiPolygon features (references into the payload shape).
Json extract_polygon_features(const Json& payload);

// validate_spatial_result(payload, *, expected_type=None,
// require_scientific=False) -> JSON array of error strings (empty = ok).
// expected_type: null Json means "detect from payload".
Json validate_spatial_result(const Json& payload, const Json& expected_type,
                             bool require_scientific);

// bounded_result_summary(payload) -> copy of result_summary with any
// embedded grid replaced by {grid_shape, grid_omitted: true}.
Json bounded_result_summary(const Json& payload);

// is_map_compilable(payload) -> bool.
bool is_map_compilable(const Json& payload);

}  // namespace pwb::prediction
