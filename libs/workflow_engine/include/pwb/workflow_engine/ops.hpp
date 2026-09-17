#pragma once

// Node bodies for the workflow engine slice: the no-op plus the
// mapping_kernel wrappers. op names are the registry keys (Python action
// ids of this slice): "test.noop" (registered by register_builtin_ops),
// "map.extract_factors" and "map.interpolate_idw" (register_mapping_ops).
//
// Data flow contract (in-memory, JSON projection + typed payload):
//   extract node output keys: factor_name, unit, target_horizon, crs,
//     point_count, points ([[x, y, value, qc_flag], ...], extraction order),
//     diagnostics; payload = pwb::mapping::FactorDataset.
//   interpolate node input: params.samples (usually {"$ref": <extract>,
//     "key": "points"}), grid_n / power / max_neighbors / search_radius /
//     min_neighbors / crs; output keys: algorithm_id, grid_n, n_samples,
//     grid_x, grid_y, grid_z (row-major nested, NaN → null), statistics,
//     distance_policy, distance_policy_annotation; payload =
//     pwb::mapping::FactorGrid.
// A failed interpolation throws (std::invalid_argument with the Python
// validate() message) — the engine lands the node FAILED and skips its
// dependents.

#include <pwb/workflow_engine/engine.hpp>

namespace pwb::workflow_engine {

// "test.noop" → {"ok": true}
void register_builtin_ops(NodeRegistry& registry);

// "map.extract_factors" + "map.interpolate_idw" over pwb::mapping kernels.
void register_mapping_ops(NodeRegistry& registry);

}  // namespace pwb::workflow_engine
