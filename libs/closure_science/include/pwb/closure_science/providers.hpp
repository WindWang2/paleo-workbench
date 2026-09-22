// pwb::closure_science — built-in inference providers (the executor seam
// implementations). Python reference: prediction/providers.py +
// prediction/tiled_onnx.py.
//
// Honesty contract: a provider is a real executor. The demo provider is the
// deterministic synthetic template the product ships for the demo path
// (demo_only — its result is always flagged demo/mock/uncalibrated, and
// find_production_model can never return it). The tiled ONNX provider runs
// the real ONNX Runtime through the native prediction task runtime; a
// missing runtime library, missing model package or contract violation is
// an explicit error — never a silent fallback or fabricated output.
#pragma once

#include <pwb/closure_science/inference_service.hpp>

#include <filesystem>

namespace pwb::closure_science {

// Deterministic synthetic facies prediction (providers.py
// DemoModelProvider parity — C++-frozen deterministic sequence; the result
// vocabulary matches the Python template: adapter_kind "mock", demo/source
// flags, evidence weights, review areas below the 0.7 confidence bound).
[[nodiscard]] ProviderRun make_demo_facies_provider();

// ---- mock facies providers (mock_facies.py parity) -------------------------
// Stage-1 stage-action providers (run_well_facies_mock /
// run_seismic_facies_mock). Both are demo-only deterministic generators
// carrying the full honesty flags (is_mock / is_replaceable / demo /
// final_scientific_prediction=false); map-product assembly fail-closes on
// source_kind=mock exactly like the Python product.
inline constexpr const char* kProviderMockWellFacies = "mock_well_facies";
inline constexpr const char* kProviderMockSeismicFacies =
    "mock_seismic_facies";
inline constexpr const char* kModelIdMockWellFacies = "mock-well-facies-v1";
inline constexpr const char* kModelIdMockSeismicFacies =
    "mock-seismic-facies-v1";
inline constexpr const char* kMockFaciesGeneratorVersion = "mock-facies-1.0";

// Per-well interval draw (MockWellFaciesProvider.run parity): reads
// parameters["_wells"|"wells"], "target_horizon", "seed"; emits
// result_summary.predicted_regions + well_detail for the INTERMEDIATE
// registration. Empty wells → explicit error (InferenceInputError parity).
[[nodiscard]] ProviderRun make_mock_well_facies_provider();

// Areal nearest-neighbour facies patches (MockSeismicFaciesProvider.run
// parity): 12 seeded anchors over parameters["_extent"|"extent"], optional
// "_clip_ring"|"clip_ring" mask, polygonized via the mapping kernel; emits
// spatial VECTOR_POLYGONS features + mock_grid for the INTERMEDIATE
// registration.
[[nodiscard]] ProviderRun make_mock_seismic_facies_provider();

struct TiledOnnxProviderConfig {
    // Root for the inference work/output directories (the artifacts tree —
    // write outputs live under <root>/intermediate/inference/<run id>).
    std::filesystem::path work_root;
    // When true, an unavailable ONNX Runtime library is an immediate
    // explicit error instead of a provider-time failure (same honest
    // outcome, earlier signal).
    bool fail_fast_without_onnx = true;
};

// Real tiled ONNX inference over the native prediction task runtime
// (tiled_onnx.py TiledOnnxProvider parity): one seismic input version, the
// registered model package from the run's _registered_model.artifact_uri
// (a manifest.json — bare ONNX artifacts are rejected with an explicit
// message), and the grid descriptor recorded on the input version's
// metadata ("grid_descriptor": shape/dtype/crs/geotransform/nodata/unit).
// Missing descriptors, unit/CRS violations or wrong shapes fail the run
// before any voxel is computed.
[[nodiscard]] ProviderRun make_tiled_onnx_provider(
    const TiledOnnxProviderConfig& config);

}  // namespace pwb::closure_science
