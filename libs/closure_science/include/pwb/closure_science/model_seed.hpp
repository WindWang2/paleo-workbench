// pwb::closure_science — model-registry seeding for the prediction product
// loop (line 03).
//
// Python parity: paleo_workbench/prediction/providers.py
//   ensure_default_models   — idempotent demo + heuristic seeding, both
//                             status="demo" so find_production_model never
//                             returns them; existing rows are never
//                             rewritten (register-or-refresh gates).
//   ensure_geoviz_online_model — deliberately NOT seeded here: the native
//                             runtime has no HTTP executor, and a remote
//                             model without an executor must stay invisible
//                             rather than advertised.
//
// The third entry is the native addition: registering a real model package
// (manifest.json + artifact, validated by pwb::prediction) as catalog
// Model + ModelVersion rows. The prediction branch left the catalog side
// of register_model_package in Python (model_package.hpp D1); this closes
// it for the native product loop. Promotion to production stays an
// explicit caller act (catalog::promote_model — the gate refuses the
// non-promotable demo/heuristic providers).
#pragma once

#include <pwb/catalog/apply_changes.hpp>
#include <pwb/catalog/models.hpp>
#include <pwb/domain/errors.hpp>

#include <string>
#include <utility>

namespace pwb::closure_science {

// Stable logical ids / capability / provider vocabulary (providers.py).
inline constexpr const char* kModelIdDemo = "demo-facies-v1";
inline constexpr const char* kModelIdHeuristic = "facies-heuristic-v1";
inline constexpr const char* kCapabilityFacies = "facies_prediction";
inline constexpr const char* kProviderDemo = "demo";
inline constexpr const char* kProviderLocalAsset = "local_asset";
inline constexpr const char* kProviderTiledOnnx = "tiled_onnx";
inline constexpr const char* kProviderGeovizOnline = "geoviz_online";

// Idempotent seed of the two built-in models (providers.py
// ensure_default_models parity: never rewrites an existing row, never
// promotes). Returns Ok when both models + versions exist afterwards.
domain::DataError ensure_default_models(catalog::CatalogDocument& document,
                                        const catalog::SaveHook& save);

// ensure_mock_facies_models parity (mock_facies.py): idempotent seed of
// the two stage-action mock models (mock_well_facies /
// mock_seismic_facies providers, both status="demo" + demo_only so
// find_production_model never returns them). Returns the (well, seismic)
// version ids.
domain::Result<std::pair<std::string, std::string>>
ensure_mock_facies_models(catalog::CatalogDocument& document,
                          const catalog::SaveHook& save);

// Register-or-refresh one validated model package as catalog rows.
// `manifest_path` points at a model package manifest.json (or the package
// directory). The package is fully loaded + validated first (checksum,
// path containment, scientific gate) — an invalid package registers
// nothing. Row identity comes from the manifest (model_id / model_version /
// capability / provider / runtime / checksum / schemas); `status` seeds the
// demo/production default ("demo" — production must be promoted
// explicitly). Re-registration refreshes under the same register-or-refresh
// gates as ensure_default_models.
struct PackageModelRequest {
    std::string manifest_path;
    std::string status = "demo";
};
domain::Result<catalog::ModelVersion> register_package_model(
    catalog::CatalogDocument& document, const catalog::SaveHook& save,
    const PackageModelRequest& request);

}  // namespace pwb::closure_science
