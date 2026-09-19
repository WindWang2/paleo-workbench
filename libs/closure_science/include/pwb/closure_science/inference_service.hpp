// pwb::closure_science — the native inference job layer (line 03).
//
// C++ port of paleo_workbench/prediction/inference_service.py's service
// contract, over the committed catalog surface (CatalogDocument + SaveHook)
// instead of the Python DataCatalogService:
//
//   start_inference   -> DataRun(status="running") with model identity +
//                        reproducibility snapshot (_input_snapshot_hash)
//   execute_run       -> provider dispatch -> spatial validation ->
//                        payload persistence (DERIVED version + run link)
//                        -> terminal run status; cancellation is a
//                        terminal "cancelled" (never "failed"), failures
//                        record the error and never fabricate output
//   materialize_prediction_task -> the domain PredictionTask dict the
//                        prediction pages display
//   resolve_model_inputs / resolve_postprocess_inputs -> schema-driven
//                        input resolution (input_contract.py core)
//
// Execution honesty (parity with the Python service, audit #1152/#1167):
//   * a terminal run refuses re-execution ("execute_run requires a
//     running run") — late/duplicate execution cannot touch it;
//   * provider results may not relabel the envelope (PAYLOAD_RESERVED_KEYS
//     are service-owned and re-asserted after the merge);
//   * a cancelled or failed run produces no consumable output version.
//
// The provider registry is the executor seam: built-ins are "demo" (the
// frozen deterministic synthetic) and "tiled_onnx" (the real ONNX Runtime
// task runtime). An unknown provider name, or a model whose runtime has no
// native executor (e.g. the HTTP geoviz_online service), is an explicit
// error — never a silent fallback. Qt-free, Python-free.
#pragma once

#include <pwb/catalog/apply_changes.hpp>
#include <pwb/catalog/models.hpp>
#include <pwb/domain/errors.hpp>
#include <pwb/domain/json.hpp>

#include <filesystem>
#include <functional>
#include <optional>
#include <string>
#include <vector>

namespace pwb::closure_science {

using domain::Json;

// ---------------------------------------------------------------------------
// Provider executor seam
// ---------------------------------------------------------------------------

// `inputs` maps input version id -> {"path", "name", "asset_type",
// "format", "version_metadata"} (payload locations + recorded metadata of
// the run's declared input versions). `parameters` carries the run's
// reproducibility metadata (seed, "_registered_model", ...). Returns the
// provider result dict; a cooperatively cancelled provider returns a dict
// with "cancelled": true. Errors surface through the Result channel.
using ProviderRun = std::function<domain::Result<Json>(
    const Json& inputs, Json parameters,
    const std::function<bool()>& cancel)>;

class ProviderRegistry {
public:
    // Registers (or replaces) the executor under *name*. Production
    // registries seed only real executors; test doubles must never be
    // installed in a production path.
    void register_provider(const std::string& name, ProviderRun run);

    // nullopt when the name is unknown — execute_run reports it as the
    // explicit "Unknown model provider" error (Python parity).
    [[nodiscard]] std::optional<ProviderRun> get(
        const std::string& name) const;

private:
    std::vector<std::pair<std::string, ProviderRun>> providers_;
};

// ---------------------------------------------------------------------------
// Input resolution (input_contract.py core + inference_service.py helpers)
// ---------------------------------------------------------------------------

// The project resource fields input resolution reads (the narrow slice the
// host collects from its project document / page state).
struct ResourceRef {
    std::string id;
    std::string type;  // well_log | seismic | well_stratification | ...
    std::string path;  // absolute source path ("" when absent)
    // Explicit re-import bridge recorded on the resource's parsed_summary
    // ("" when the resource predates it).
    std::string catalog_asset_id;
};

// _resolve_resource_version_id parity: catalog asset id / legacy bridge /
// recorded catalog_asset_id (resource summary) match, then the unique
// live source-URI fallback. nullopt when unresolved.
[[nodiscard]] std::optional<std::string> resolve_resource_version_id(
    const catalog::CatalogDocument& document, const ResourceRef& resource);

// resolve_inputs_for_model parity (strict): returns the input version ids
// for one run of *model_version_id*. When *selected_resource_id* is set the
// resolution is scoped to that single resource (the prediction page's
// single-well / single-survey request).
[[nodiscard]] domain::Result<std::vector<std::string>> resolve_model_inputs(
    const catalog::CatalogDocument& document,
    const std::vector<ResourceRef>& resources,
    const std::string& model_version_id,
    const std::optional<std::string>& selected_resource_id = std::nullopt);

// resolve_prediction_postprocess_inputs parity: per-well stratification
// versions recorded for reproducible local post-processing.
[[nodiscard]] std::vector<std::string> resolve_postprocess_inputs(
    const catalog::CatalogDocument& document,
    const std::vector<ResourceRef>& resources);

// ---------------------------------------------------------------------------
// Run lifecycle
// ---------------------------------------------------------------------------

inline constexpr const char* kInferenceGenerator = "inference-service-v1";

struct StartInferenceRequest {
    std::string model_version_id;
    std::vector<std::string> input_version_ids;
    Json parameters = Json::object();
    std::string operation = "prediction";
    std::string generator = std::string(kInferenceGenerator);
};

// Opens the running inference DataRun (Python start_inference parity):
// canonicalized input order, model identity + reproducibility snapshot in
// run.parameters, model_ref bound to the registered model version.
// Persisted through *save* (asset/run dirty set) in one channel.
[[nodiscard]] domain::Result<catalog::DataRun> start_inference(
    catalog::CatalogDocument& document, const catalog::SaveHook& save,
    const StartInferenceRequest& request);

struct ExecuteRunDeps {
    // Persistence channel (catalog SaveHook over the caller's store).
    catalog::SaveHook save;
    // Executor seam — must contain every provider name the catalog's
    // registered models reference; anything else is an explicit error.
    const ProviderRegistry* providers = nullptr;
    // Project dir (version payload path joins) and the artifacts staging
    // root for result files ("<project>.artifacts" per the platform layout;
    // results land under <artifacts_root>/derived/inference/).
    std::filesystem::path project_dir;
    std::filesystem::path artifacts_root;
};

struct ExecuteRunOutcome {
    catalog::DataRun run;
    // The service-owned payload envelope persisted as the result version.
    Json payload = Json::object();
    std::string output_version_id;
    catalog::DataVersion output_version;
    bool cancelled = false;
};

// Executes one running inference run (Python execute_run parity, including
// the late/duplicate-execution refusal, the reserved-key envelope
// discipline, spatial output validation and terminal status recording).
// Never throws; every failure lands on the run (status failed + error) or
// in the Result channel. *cancel* is polled through the provider seam.
[[nodiscard]] domain::Result<ExecuteRunOutcome> execute_run(
    catalog::CatalogDocument& document, const ExecuteRunDeps& deps,
    const std::string& run_id, const std::function<bool()>& cancel = {});

struct PredictionTaskOptions {
    std::string name_prefix;
    std::string workflow;
    std::string target_horizon;
    std::vector<std::string> well_log_resource_ids;
    std::vector<std::string> seismic_resource_ids;
    std::string run_id;
    std::string output_version_id;
};

// materialize_prediction_task parity: the domain PredictionTask dict a
// finished run displays (bounded result summary, model metadata with
// workflow/run/prediction-version identity, honest demo flags).
[[nodiscard]] Json materialize_prediction_task(
    const catalog::CatalogDocument& document, const Json& payload,
    const PredictionTaskOptions& options);

// DataRun model_dump (models.py key order) for the page payload.
[[nodiscard]] Json run_to_json(const catalog::DataRun& run);

}  // namespace pwb::closure_science
