#pragma once

// Port of paleo_workbench/mapping/factor_layer_products.py —
// layer-descriptor builders for the staged factor-map workflow
// (goal §10-12). A Stage-2 factor group carries SIX children per
// FACTOR_CHILD_ORDER (input points → scalar grid → contours →
// classification polygons → uncertainty surface → QC overlay). This
// module builds plain layer *descriptors* — Json dicts with
// layer_id / role / title / geometry_kind / features-or-payload /
// metadata — with no Qt dependency, so the stage-action layer stays a
// thin orchestrator while scientific truth (live grid vs task metadata)
// is decided by the caller.
//
// Honesty rules (mirroring the FactorGridResult design contract):
//   * No invented data — the uncertainty child exists only when the
//     algorithm produced a variance_grid (kriging); its absence is
//     reported as an info QC point instead of a fabricated layer.
//   * Scalar children are descriptors only — they carry the
//     grid-derived metadata the scalar publish path needs (extent,
//     statistics, artifact version, run ref) under "payload"; grid
//     arrays never cross into descriptors.
//   * Derived vector children come from the live grid only — contours
//     reuse the contouring kernel, classifications the polygonization
//     kernel; without a live grid those children are empty with an
//     explicit "absent_reason" (no silent recompute).
//   * Contour features are capped (contour_limit); truncation is
//     reported in metadata, never silent.
//
// Qt-free, Python-free.

#include <pwb/domain/json.hpp>
#include <pwb/mapping/interpolator.hpp>

#include <string>
#include <utility>
#include <vector>

namespace pwb::ui_composite {

using pwb::domain::Json;

// Runtime layer type for scalar-grid semantics (SCALAR_GRID_LAYER_TYPE).
inline constexpr const char* kScalarGridLayerType = "scalar_grid";

// The caller-resolved live grid + its descriptor metadata (the "peek"
// pattern stays in the action). `live` is the numeric grid the
// contour/polygonization kernels consume; `metadata` is the
// FactorGridResult.to_descriptor()-shaped record the scalar payload
// carries verbatim (task.grid_metadata when no live grid is resident).
struct FactorGroupGridView {
    const pwb::mapping::FactorGrid* live = nullptr;
    Json metadata = Json::object();
};

// factor_group_layers parity — descriptors for ALL SIX factor-group
// children of `task` (a factor_map_tasks entry), in FACTOR_CHILD_ORDER:
// input → grid → contour → classification → uncertainty → QC. The
// uncertainty child is omitted when no variance_grid exists (honest
// absence; the QC child reports it).
[[nodiscard]] std::vector<Json> factor_group_layers(
    const Json& document, const Json& task,
    const FactorGroupGridView& grid, int contour_limit = 200);

// classify_prediction_task parity — "well" | "seismic" | "unknown" from
// machine-readable signals (input_refs keys first, then the task name).
[[nodiscard]] std::string classify_prediction_task(const Json& task);

// confidence_overlay_layers parity — probability/confidence polygon
// descriptors for a prediction task. Empty list when the task carries
// no probability-bearing polygon results (never a fabricated surface).
[[nodiscard]] std::vector<Json> confidence_overlay_layers(
    const Json& document, const Json& prediction_task);

// boundary_features_from_polygons parity — extract facies-polygon rings
// as boundary LineString features ((geometry, attributes) pairs;
// exterior first, holes labelled hole_N).
[[nodiscard]] std::vector<std::pair<Json, Json>>
boundary_features_from_polygons(
    const std::vector<std::pair<Json, Json>>& features,
    const std::string& source_layer_id = "");

// integrated_boundary_action_helpers parity — the INTEGRATED_BOUNDARY
// layer descriptor for a draft's facies polygons, resolved document-side
// by layer id. is_null() when the draft has no polygon rings.
[[nodiscard]] Json integrated_boundary_action_helpers(
    const Json& document, const std::string& source_layer_id);

}  // namespace pwb::ui_composite
