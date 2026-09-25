// prediction.run_spec — the PredictionRunSpec single-run contract:
// serialization roundtrip (strict, fail-closed on unknown keys/schema
// drift), equality, kernel-anchored defaults, parameter validation matrix
// and the params -> PredictionPipelineOptions mapping. Qt-free, ORT-free.

#include <pwb/domain/json.hpp>
#include <pwb/prediction/prediction_pipeline.hpp>
#include <pwb/prediction/run_spec.hpp>

#include <cstdio>
#include <string>
#include <vector>

namespace {

using pwb::domain::Json;
using pwb::prediction::PredictionRunSpec;

int g_failures = 0;
int g_checks = 0;

void check(bool ok, const std::string& what) {
    ++g_checks;
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

bool has_message(const std::vector<std::string>& errors,
                 const std::string& needle) {
    for (const auto& text : errors) {
        if (text.find(needle) != std::string::npos) return true;
    }
    return false;
}

}  // namespace

int main() {
    // -- schema/defaults are kernel-anchored ------------------------------
    {
        const auto schema = pwb::prediction::prediction_param_schema();
        check(!schema.empty(), "schema non-empty");
        const Json defaults = pwb::prediction::default_prediction_params();
        check(defaults.is_object(), "defaults object");
        bool tile_found = false;
        bool budget_found = false;
        for (const auto& spec : schema) {
            const auto it = defaults.find(spec.key);
            check(it != defaults.end(), "default exists for " + spec.key);
            if (spec.key == "tile_inline") {
                tile_found = true;
                check(spec.default_int == 0,
                      "tile_inline default keeps the package declaration");
            }
            if (spec.key == "output_budget_mb") {
                budget_found = true;
                check(spec.default_int == 2048,
                      "budget default 2048 MiB == kernel 2 GiB");
            }
            if (spec.key == "prefer_gpu") {
                check(!spec.default_bool, "prefer_gpu defaults to CPU");
            }
        }
        check(tile_found, "tile_inline in schema");
        check(budget_found, "output_budget_mb in schema");
        check(pwb::prediction::validate_prediction_params(defaults).empty(),
              "defaults validate");
    }

    // -- params validation matrix (fail closed) ---------------------------
    {
        Json params = pwb::prediction::default_prediction_params();
        params["tile_inline"] = -5;
        params["mystery"] = 1;
        params["prefer_gpu"] = "yes";
        params["output_budget_mb"] = 999999;
        const auto errors = pwb::prediction::validate_prediction_params(params);
        check(has_message(errors, "tile_inline") || has_message(errors, "内联"),
              "tile_inline below-min rejected");
        check(has_message(errors, "未知参数"),
              "unknown param key rejected (never dropped)");
        check(has_message(errors, "布尔"), "bool type mismatch rejected");
        check(has_message(errors, "上限"), "budget over-max rejected");

        Json not_object = Json::array();
        check(!pwb::prediction::validate_prediction_params(not_object)
                   .empty(),
              "non-object params rejected");
    }

    // -- serialization roundtrip + strictness ------------------------------
    {
        PredictionRunSpec spec;
        spec.well_resource_ids = {"res_w1", "res_w2"};
        spec.seismic_resource_id = "res_seis";
        spec.model_version_id = "mv_9";
        spec.params = pwb::prediction::default_prediction_params();
        spec.params["tile_inline"] = 96;
        spec.params["prefer_gpu"] = true;
        spec.resolved = Json{{"model_checksum", "abc"}};

        const Json saved = spec.to_json();
        std::vector<std::string> errors;
        const auto loaded = PredictionRunSpec::from_json(saved, errors);
        check(errors.empty(), "roundtrip without errors: " +
                                  (errors.empty() ? "" : errors[0]));
        check(loaded.has_value(), "roundtrip parses");
        if (loaded.has_value()) {
            check(*loaded == spec, "roundtrip equal");
            check(loaded->well_resource_ids.size() == 2 &&
                      loaded->well_resource_ids[0] == "res_w1",
                  "stable well ids survive roundtrip");
            check(loaded->params["tile_inline"].get<int>() == 96,
                  "edited param survives roundtrip");
        }

        // Unknown top-level key (and a param smuggled to top level).
        Json smuggled = saved;
        smuggled["seed"] = 7;
        errors.clear();
        check(!PredictionRunSpec::from_json(smuggled, errors).has_value(),
              "top-level param key rejected");
        check(has_message(errors, "未知 RunSpec 键"),
              "smuggled key named in errors");

        // Schema drift: a stored newer schema refuses reinterpretation.
        Json future = saved;
        future["schema_version"] = pwb::prediction::kRunSpecSchemaVersion + 1;
        errors.clear();
        check(!PredictionRunSpec::from_json(future, errors).has_value(),
              "newer schema refused");
        check(has_message(errors, "版本"), "schema drift named in errors");

        // Draft mode: model may be missing until one is chosen.
        Json draft = saved;
        draft.erase("model_version_id");
        errors.clear();
        check(PredictionRunSpec::from_json(draft, errors, /*require_model=*/false)
                  .has_value(),
              "draft without model accepted in draft mode");
        errors.clear();
        check(!PredictionRunSpec::from_json(draft, errors, true).has_value(),
              "draft without model rejected in run mode");

        // Invalid nested params fail the whole parse.
        Json bad_params = saved;
        bad_params["params"]["batch"] = -3;
        errors.clear();
        check(!PredictionRunSpec::from_json(bad_params, errors).has_value(),
              "invalid nested params fail parse");
    }

    // -- equality is field-wise --------------------------------------------
    {
        PredictionRunSpec a;
        PredictionRunSpec b;
        check(a == b, "fresh specs equal");
        b.params["batch"] = 2;
        check(a != b, "param change breaks equality");
        b.params["batch"] = 0;
        b.seismic_resource_id = "res_s";
        check(a != b, "seismic change breaks equality");
    }

    // -- params -> pipeline options mapping (the runner's single source) --
    {
        Json params = pwb::prediction::default_prediction_params();
        params["tile_inline"] = 48;
        params["tile_xline"] = 64;
        params["tile_time"] = 80;
        params["overlap"] = 12;
        params["batch"] = 4;
        params["prefer_gpu"] = true;
        params["keep_probmap"] = false;
        params["write_outputs"] = false;
        params["resume"] = false;
        params["output_budget_mb"] = 512;

        pwb::prediction::PredictionPipelineOptions options;
        pwb::prediction::apply_prediction_params(params, options);
        check(options.tile[0] == 48 && options.tile[1] == 64 &&
                  options.tile[2] == 80,
              "tile geometry mapped");
        check(options.overlap == 12, "overlap mapped");
        check(options.batch == 4, "batch mapped");
        check(options.prefer_gpu, "prefer_gpu mapped");
        check(!options.keep_probmap, "keep_probmap mapped");
        check(!options.write_outputs, "write_outputs mapped");
        check(!options.resume, "resume mapped");
        check(options.output_budget_bytes == 512LL * 1024 * 1024,
              "budget MiB -> bytes");

        // Sentinels keep the package-declared defaults (kernel semantics).
        pwb::prediction::PredictionPipelineOptions sentinel;
        pwb::prediction::apply_prediction_params(
            pwb::prediction::default_prediction_params(), sentinel);
        check(sentinel.tile == pwb::prediction::Tile3{0, 0, 0} &&
                  sentinel.overlap == -1 && sentinel.batch == 0,
              "defaults map to package-declared sentinels");
    }

    if (g_failures == 0) {
        std::printf("prediction.run_spec: %d checks passed\n", g_checks);
        return 0;
    }
    std::printf("prediction.run_spec: %d/%d checks FAILED\n", g_failures,
                g_checks);
    return 1;
}
