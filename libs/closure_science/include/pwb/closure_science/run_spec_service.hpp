// pwb::closure_science — PredictionRunSpec-backed selection + preflight
// services for the ws1 prediction workflow (select wells -> select model
// -> edit params -> preflight -> run). Qt-free, Python-free.
//
// The service reads the SAME catalog document the inference service runs
// against and speaks the SAME PredictionRunSpec the runner consumes
// (libs/prediction run_spec.hpp): selection edits the spec, preflight
// resolves it (input version ids + model identity) and the run embeds the
// resolved spec verbatim for provenance. There is no second parameter or
// selection truth anywhere.
#pragma once

#include <pwb/catalog/models.hpp>
#include <pwb/closure_science/inference_service.hpp>
#include <pwb/domain/errors.hpp>
#include <pwb/domain/json.hpp>
#include <pwb/prediction/run_spec.hpp>

#include <optional>
#include <string>
#include <vector>

namespace pwb::closure_science {

// ---------------------------------------------------------------------------
// Well selection (predict.select_well backing data)
// ---------------------------------------------------------------------------

struct WellCandidate {
    std::string resource_id;  // stable selection key (never a table row)
    std::string name;
    std::string path;
    // Current resolvable catalog version of the bound well-log asset (""
    // when the resource has no usable version).
    std::string version_id;
    int version_count = 0;  // live (non-trashed) versions of the asset
    // ok | unmanaged | no_current_version | trashed_asset
    std::string availability = "ok";
    // Curves the bound version declares (metadata.curves / curve mnemonics
    // recorded at import); empty when the version records none.
    std::vector<std::string> curves;
    // Curves the scoped model requires that this well does not declare.
    std::vector<std::string> missing_required_curves;
};

// Lists well_log resources with their catalog binding state. When
// *model_version_id* is set, each candidate is annotated with the model's
// required_curves gaps (unverifiable curve metadata is NOT reported as
// missing — only declared-without-the-required-mnemonic is).
[[nodiscard]] std::vector<WellCandidate> list_well_candidates(
    const catalog::CatalogDocument& document,
    const std::vector<ResourceRef>& resources,
    const std::optional<std::string>& model_version_id = std::nullopt);

// ---------------------------------------------------------------------------
// Model selection (predict.model_params backing data)
// ---------------------------------------------------------------------------

struct ModelCandidate {
    std::string model_version_id;  // stable selection key
    std::string model_id;
    std::string model_version;
    std::string name;
    std::string provider;  // demo | tiled_onnx | local_asset | geoviz_online
    std::string runtime;
    std::string status;  // demo | production | archived
    std::optional<std::string> checksum;
    std::string artifact_uri;  // manifest.json (package) or model file
    bool demo_only = false;
    Json input_schema = Json::object();
    // Whether this build can execute the provider at all (tiled_onnx needs
    // a loadable ONNX Runtime; geoviz_online/local_asset have no native
    // executor). Honest selection UI disables what cannot run.
    bool executor_available = false;
    std::string executor_note;
};

[[nodiscard]] std::vector<ModelCandidate> list_model_candidates(
    const catalog::CatalogDocument& document);

// Deep package inspection for the selected model (real manifest load +
// checksum/path validation via pwb::prediction — the same validation the
// run performs; an invalid package cannot be selected for a run).
struct ModelPackageSummary {
    bool ok = false;
    std::string error;
    std::string model_id;
    std::string model_version;
    std::string checksum;          // artifact sha256 (hex)
    std::string model_file;        // package-relative artifact path
    std::vector<std::string> expected_inputs;   // input band names
    std::vector<std::string> class_names;       // facies vocabulary
    std::string preprocessing_version;
    std::string declared_tile;  // "64x128x128"-style package geometry
};
[[nodiscard]] ModelPackageSummary inspect_model_package(
    const std::string& manifest_or_artifact_uri);

// ---------------------------------------------------------------------------
// Preflight (predict.run gate — the ONLY path that resolves a spec)
// ---------------------------------------------------------------------------

struct PreflightReport {
    bool ok = false;
    std::vector<std::string> errors;
    std::vector<std::string> warnings;
    // The contract-resolved input version ids the run opens with (same
    // resolution resolve_model_inputs performs). Empty unless ok.
    std::vector<std::string> input_version_ids;
    // The resolved spec (spec.resolved filled: input version ids, well
    // version ids, model identity incl. checksum + provider + runtime,
    // kernel identity). Only meaningful when ok.
    pwb::prediction::PredictionRunSpec spec;
};

// Validates params, resolves the model (identity + checksum + package
// validation + executor availability), resolves the seismic input version
// (grid descriptor present, PWBVOL1) and the selected well versions, and
// checks the input contract exactly like the run would (resolve_model_inputs).
// Never mutates the catalog. Fail-closed: any problem lands in errors.
[[nodiscard]] PreflightReport preflight_run(
    const catalog::CatalogDocument& document,
    const std::vector<ResourceRef>& resources,
    const pwb::prediction::PredictionRunSpec& spec);

// The run parameters the binding builds from a RESOLVED spec — single
// mapping point (pages' legacy parameter keys stay compatible: the run
// parameters carry well/seismic resource ids, seed, workflow, naming and
// the verbatim spec under "_run_spec" for provenance).
[[nodiscard]] Json run_parameters_from_spec(
    const pwb::prediction::PredictionRunSpec& spec);

}  // namespace pwb::closure_science
