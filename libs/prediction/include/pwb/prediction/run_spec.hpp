// PredictionRunSpec — the single serialized/comparable run contract for the
// prediction workspace loop:
//
//   select inputs -> select model/version -> edit parameters -> preflight
//   -> run/cancel -> publish -> provenance
//
// The UI edits a RunSpec, the runner consumes the same RunSpec and the
// run/provenance record embeds it verbatim (run.parameters["_run_spec"]) —
// there is exactly ONE parameter truth, never a UI copy plus runner
// defaults. Parameter editing is schema-driven: prediction_param_schema()
// derives ranges/defaults/units from the kernel constants the tiled
// pipeline actually enforces, and deserialization is strict — unknown keys
// and out-of-range values are errors, never silently dropped values.
//
// Qt-free, Python-free, ORT-free (usable by the contracts tests).
#pragma once

#include <optional>
#include <string>
#include <vector>

#include "pwb/domain/json.hpp"
#include "pwb/prediction/prediction_pipeline.hpp"

namespace pwb::prediction {

// Bump when the serialized shape changes; from_json refuses newer schemas
// (a stored spec must never be silently reinterpreted).
inline constexpr int kRunSpecSchemaVersion = 1;

// One UI-editable runtime parameter (schema-driven params panel data).
struct PredictionParamSpec {
    enum class Type { Int, Bool };
    std::string key;    // params object key, e.g. "tile_inline"
    std::string label;  // UI label
    Type type = Type::Int;
    long long min_value = 0;         // inclusive (Int)
    long long max_value = 0;         // inclusive (Int); 0 = unbounded
    long long default_int = 0;       // Int default
    bool default_bool = false;       // Bool default
    std::string unit;                // "" | "体素" | "MiB" | ...
    std::string description;         // includes the sentinel semantics
};

// The editable parameter schema, kernel-anchored: tile geometry defaults
// come from kDefaultTile, the output budget from kDefaultOutputBudgetBytes.
// Keys ending in a sentinel value document it in `description` (0 / -1 mean
// "package-declared default" exactly as PredictionPipelineOptions defines).
[[nodiscard]] std::vector<PredictionParamSpec> prediction_param_schema();

// The defaults every fresh RunSpec starts from (== the schema defaults).
[[nodiscard]] Json default_prediction_params();

// Strict validation: every key must be a known schema key with the right
// type inside [min, max]. Returns one message per problem (empty = valid).
[[nodiscard]] std::vector<std::string> validate_prediction_params(
    const Json& params);

// The single mapping point from serialized params onto the pipeline
// options the runner builds (unknown keys are ignored here — validation
// happens at the UI/preflight seam, before a run opens). Runtime-owned
// fields (output_dir/work_root/cancel/progress/input_options) are never
// taken from params.
void apply_prediction_params(const Json& params,
                             PredictionPipelineOptions& options);

struct PredictionRunSpec {
    // Stable project resource ids (never table rows). Well selection is
    // provenance + pane state for the current kernels; the seismic volume
    // is the inference input.
    std::vector<std::string> well_resource_ids;
    std::optional<std::string> seismic_resource_id;
    // Catalog ModelVersion id (register_package_model identity).
    std::string model_version_id;

    // Runtime parameters — schema-validated (prediction_param_schema()).
    Json params = default_prediction_params();

    // Output naming intent + algorithm id ("seismic_facies" today).
    std::string workflow = "seismic_facies";
    std::string name_prefix = "地震相预测";
    bool demo = false;

    // Filled by preflight (never UI-edited): resolved input version ids,
    // model identity (model_id/model_version/checksum/artifact_uri/
    // provider) and calibration prerequisites. Recorded verbatim into the
    // run for provenance.
    Json resolved = Json::object();

    [[nodiscard]] Json to_json() const;
    // Strict parse: unknown top-level keys / bad types / invalid params /
    // newer schema versions are errors (messages), never dropped fields.
    // Missing optional keys keep their defaults; `require_model` demands
    // model_version_id (a draft spec may omit it until a model is chosen).
    [[nodiscard]] static std::optional<PredictionRunSpec> from_json(
        const Json& value, std::vector<std::string>& errors,
        bool require_model = true);
};

[[nodiscard]] bool operator==(const PredictionRunSpec& a,
                              const PredictionRunSpec& b);
[[nodiscard]] bool operator!=(const PredictionRunSpec& a,
                              const PredictionRunSpec& b);

}  // namespace pwb::prediction
