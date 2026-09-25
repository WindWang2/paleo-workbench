// closure_science.run_spec_service — the ws1 RunSpec selection + preflight
// services: well candidates (stable ids, availability states, required-
// curve gaps), model candidates (executor honesty), package inspection
// (real fixture package), the preflight failure matrix and the
// run-parameters mapping (_run_spec verbatim for provenance). Qt-free,
// ORT-free (a tiled_onnx preflight without ORT fails honestly — asserted).
#include <pwb/catalog/model_registry.hpp>
#include <pwb/catalog/models.hpp>
#include <pwb/catalog/service_core.hpp>
#include <pwb/closure_science/inference_service.hpp>
#include <pwb/closure_science/model_seed.hpp>
#include <pwb/closure_science/providers.hpp>
#include <pwb/closure_science/run_spec_service.hpp>
#include <pwb/domain/json.hpp>
#include <pwb/prediction/onnx_session.hpp>
#include <pwb/prediction/run_spec.hpp>
#include <pwb/project/manager.hpp>

#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <functional>
#include <string>
#include <vector>

#ifdef _WIN32
#include <process.h>
#else
#include <unistd.h>
#endif

namespace {

namespace fs = std::filesystem;
using pwb::catalog::CatalogDocument;
using pwb::catalog::DataAsset;
using pwb::catalog::DataVersion;
using pwb::domain::Json;

long get_pid() {
#ifdef _WIN32
    return static_cast<long>(_getpid());
#else
    return static_cast<long>(::getpid());
#endif
}

int g_failures = 0;
int g_checks = 0;

void check(bool ok, const std::string& what) {
    ++g_checks;
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

bool has_error(const std::vector<std::string>& errors,
               const std::string& needle) {
    for (const auto& text : errors) {
        if (text.find(needle) != std::string::npos) return true;
    }
    return false;
}

struct Fixture {
    CatalogDocument document;
    std::vector<pwb::closure_science::ResourceRef> resources;

    Fixture() {
        // well-w1: managed, current version, declares GR/DT curves. The
        // resource<->asset bridge is legacy_resource_id (the page resource
        // ids predate the catalog rows — the resolver's ordinary path).
        DataAsset w1;
        w1.id = pwb::domain::AssetId(std::string("asset_w1"));
        w1.type = "well_log";
        w1.legacy_resource_id = std::string("res_w1");
        DataVersion w1v1;
        w1v1.id = pwb::domain::VersionId(std::string("ver_w1"));
        w1v1.asset_id = w1.id;
        w1v1.metadata = Json{{"curves", Json::array({"GR", "DT"})}};
        w1.current_version_id = w1v1.id;
        // well-w2: no current version (superseded-only asset).
        DataAsset w2;
        w2.id = pwb::domain::AssetId(std::string("asset_w2"));
        w2.type = "well_log";
        w2.legacy_resource_id = std::string("res_w2");
        // well-w3: trashed asset.
        DataAsset w3;
        w3.id = pwb::domain::AssetId(std::string("asset_w3"));
        w3.type = "well_log";
        w3.legacy_resource_id = std::string("res_w3");
        w3.trashed = true;
        // seismic: managed version with grid descriptor.
        DataAsset seis;
        seis.id = pwb::domain::AssetId(std::string("asset_seis"));
        seis.type = "seismic";
        seis.legacy_resource_id = std::string("res_seis");
        DataVersion seisv1;
        seisv1.id = pwb::domain::VersionId(std::string("ver_seis"));
        seisv1.asset_id = seis.id;
        seisv1.metadata = Json{{"grid_descriptor",
                                Json{{"shape", Json::array({8, 8, 8})},
                                     {"dtype", "float32"},
                                     {"crs", "EPSG:32650"}}}};
        seis.current_version_id = seisv1.id;
        document.assets = {w1, w2, w3, seis};
        document.versions = {w1v1, seisv1};

        resources = {
            {"res_w1", "well_log", "/wells/w1.las", ""},
            {"res_w2", "well_log", "/wells/w2.las", ""},
            {"res_w3", "well_log", "/wells/w3.las", ""},
            {"res_seis", "seismic", "/seis/vol.pwbvol", ""},
        };

        // Model rows: demo (executable), tiled_onnx (package identity) and
        // an online provider with no native executor.
        pwb::catalog::Model demo;
        demo.id = "model_demo_row";
        demo.model_id = "demo-facies-v1";
        demo.model_name = "演示相预测";
        demo.capability = "facies_prediction";
        demo.provider = "demo";
        demo.status = "demo";
        pwb::catalog::ModelVersion demo_v;
        demo_v.id = "mver_demo";
        demo_v.model_id = demo.model_id;
        demo_v.model_version = "1";
        demo_v.status = "demo";
        demo_v.demo_only = true;

        pwb::catalog::Model tiled;
        tiled.id = "model_tiled_row";
        tiled.model_id = "facies-tiled-onnx-demo";
        tiled.model_name = "地震相带预测";
        tiled.capability = "facies_prediction";
        tiled.provider = "tiled_onnx";
        tiled.status = "production";
        pwb::catalog::ModelVersion tiled_v;
        tiled_v.id = "mver_tiled";
        tiled_v.model_id = tiled.model_id;
        tiled_v.model_version = "1.0.0";
        tiled_v.status = "production";
        tiled_v.artifact_uri = (fs::path(PWB_FIXTURE_DIR) / "identity_package" /
                                "manifest.json")
                                   .string();
        tiled_v.input_schema = Json{{"required_asset_types",
                                     Json::array({"seismic"})}};
        tiled_v.checksum =
            "36f1a110c491f99b6b488692c81c041f796b4d6c94b03b8cd8b02b4fd3351ed7";

        pwb::catalog::Model online;
        online.id = "model_online_row";
        online.model_id = "geoviz-online-v1";
        online.model_name = "线上模型";
        online.capability = "facies_prediction";
        online.provider = "geoviz_online";
        online.status = "production";
        pwb::catalog::ModelVersion online_v;
        online_v.id = "mver_online";
        online_v.model_id = online.model_id;
        online_v.model_version = "1";
        online_v.status = "production";

        document.models = {demo, tiled, online};
        document.model_versions = {demo_v, tiled_v, online_v};
    }
};

}  // namespace

int main() {
    Fixture fx;

    // ---- well candidates: stable ids + availability + curve gaps --------
    {
        const auto wells = pwb::closure_science::list_well_candidates(
            fx.document, fx.resources);
        check(wells.size() == 3, "three well_log candidates");
        const auto by_id = [&](const std::string& id) {
            for (const auto& well : wells) {
                if (well.resource_id == id) return well;
            }
            return pwb::closure_science::WellCandidate{};
        };
        const auto w1 = by_id("res_w1");
        check(w1.resource_id == "res_w1" && w1.version_id == "ver_w1",
              "managed well resolves stable version id");
        check(w1.availability == "ok", "managed well ok");
        check(w1.version_count == 1, "live version count");
        check(by_id("res_w2").availability == "unmanaged",
              "asset without current version -> unmanaged");
        check(by_id("res_w3").availability == "trashed_asset",
              "trashed asset reported");

        // Required-curve gap against the tiled model (declares none of its
        // own — the w1 set lacks a required curve only if the model asks).
        auto wells_scoped = pwb::closure_science::list_well_candidates(
            fx.document, fx.resources, std::string("mver_tiled"));
        check(wells_scoped.size() == 3, "scoped listing unchanged count");
        // Unverifiable curve metadata is never reported missing.
        for (const auto& well : wells_scoped) {
            check(well.missing_required_curves.empty(),
                  "no fabricated missing curves");
        }
    }

    // ---- model candidates: executor honesty ------------------------------
    {
        const auto models =
            pwb::closure_science::list_model_candidates(fx.document);
        check(models.size() == 3, "three model candidates");
        const auto by_id = [&](const std::string& id) {
            for (const auto& model : models) {
                if (model.model_version_id == id) return model;
            }
            return pwb::closure_science::ModelCandidate{};
        };
        check(by_id("mver_demo").executor_available,
              "demo provider always executable");
        check(!by_id("mver_online").executor_available,
              "geoviz_online has no native executor");
        const auto tiled = by_id("mver_tiled");
        check(!tiled.artifact_uri.empty(), "tiled model carries artifact");
        // Without a loadable ORT the tiled candidate is honestly not
        // executable (the note names the env knob).
        check(tiled.executor_available ==
                  pwb::prediction::onnx_runtime_available(),
              "tiled executor flag mirrors real ORT availability");
        if (!tiled.executor_available) {
            check(tiled.executor_note.find("onnxruntime") !=
                      std::string::npos,
                  "executor note names the missing runtime");
        }
    }

    // ---- package inspection over the real fixture package ----------------
    {
        const auto summary = pwb::closure_science::inspect_model_package(
            (fs::path(PWB_FIXTURE_DIR) / "identity_package" / "manifest.json")
                .string());
        check(summary.ok, "fixture package validates: " + summary.error);
        check(summary.model_id == "facies-tiled-onnx-demo",
              "package identity model_id");
        check(summary.checksum ==
                  "36f1a110c491f99b6b488692c81c041f796b4d6c94b03b8cd8b02b"
                  "4fd3351ed7",
              "package artifact sha256");
        check(summary.class_names.size() == 2, "class vocabulary read");
        check(summary.declared_tile == "6x8x5", "declared tile geometry");
        check(pwb::closure_science::inspect_model_package("/nonexistent")
                  .ok == false,
              "missing package fails inspection");
    }

    // ---- preflight failure matrix ----------------------------------------
    {
        pwb::prediction::PredictionRunSpec spec;
        spec.model_version_id = "mver_tiled";
        spec.seismic_resource_id = "res_seis";
        spec.well_resource_ids = {"res_w1"};

        // Healthy path (may still fail honestly without ORT — the matrix
        // treats both outcomes explicitly).
        auto report = pwb::closure_science::preflight_run(
            fx.document, fx.resources, spec);
        const bool ort = pwb::prediction::onnx_runtime_available();
        check(report.ok == ort,
              "tiled preflight passes only with a real ORT runtime");
        if (report.ok) {
            check(report.input_version_ids.size() == 1 &&
                      report.input_version_ids[0] == "ver_seis",
                  "input resolution returns the seismic version");
            check(report.spec.resolved.contains("model"),
                  "resolved identity recorded");
            check(report.spec.resolved["model"]["artifact_checksum"] ==
                      "36f1a110c491f99b6b488692c81c041f796b4d6c94b03b8cd"
                      "8b02b4fd3351ed7",
                  "resolved model checksum recorded");
        } else {
            check(has_error(report.errors, "ONNX Runtime"),
                  "no-ORT preflight names the runtime");
        }

        // No model selected.
        auto no_model = spec;
        no_model.model_version_id.clear();
        check(!pwb::closure_science::preflight_run(fx.document, fx.resources,
                                                   no_model)
                  .ok,
              "empty model fails preflight");

        // Unknown model id.
        auto unknown = spec;
        unknown.model_version_id = "mver_missing";
        check(has_error(
                  pwb::closure_science::preflight_run(fx.document, fx.resources,
                                                      unknown)
                      .errors,
                  "不存在"),
              "unknown model id named");

        // Provider without a native executor.
        auto online = spec;
        online.model_version_id = "mver_online";
        check(has_error(
                  pwb::closure_science::preflight_run(fx.document, fx.resources,
                                                      online)
                      .errors,
                  "无原生执行器"),
              "online provider refused at preflight");

        // Tiled model without a seismic selection.
        auto no_seis = spec;
        no_seis.seismic_resource_id.reset();
        check(has_error(
                  pwb::closure_science::preflight_run(fx.document, fx.resources,
                                                      no_seis)
                      .errors,
                  "选择一个地震体"),
              "tiled preflight demands a seismic input");

        // Seismic resource without a recorded grid descriptor.
        Fixture no_grid;
        for (auto& version : no_grid.document.versions) {
            if (version.id.str() == "ver_seis") version.metadata = Json::object();
        }
        check(has_error(
                  pwb::closure_science::preflight_run(no_grid.document,
                                                      no_grid.resources, spec)
                      .errors,
                  "grid_descriptor"),
              "missing grid descriptor named");

        // A selected well without a usable version fails closed.
        auto bad_well = spec;
        bad_well.well_resource_ids = {"res_w2"};
        check(has_error(
                  pwb::closure_science::preflight_run(fx.document, fx.resources,
                                                      bad_well)
                      .errors,
                  "没有可用的纳管版本"),
              "well without version refuses the run");

        // Invalid params never reach a run.
        auto bad_params = spec;
        bad_params.params["tile_inline"] = 999999;
        check(has_error(
                  pwb::closure_science::preflight_run(fx.document, fx.resources,
                                                      bad_params)
                      .errors,
                  "参数无效"),
              "invalid params blocked at preflight");

        // Checksum drift: a tampered registry checksum forbids the run.
        Fixture drifted;
        for (auto& mv : drifted.document.model_versions) {
            if (mv.id == "mver_tiled") mv.checksum = std::string(64, '0');
        }
        if (ort) {
            check(has_error(pwb::closure_science::preflight_run(
                                drifted.document, drifted.resources, spec)
                                .errors,
                            "校验和不一致"),
                  "checksum drift blocks the run");
        }

        // Demo provider: always executable, no seismic requirement.
        auto demo = spec;
        demo.model_version_id = "mver_demo";
        demo.seismic_resource_id.reset();
        const auto demo_report = pwb::closure_science::preflight_run(
            fx.document, fx.resources, demo);
        check(demo_report.ok, "demo preflight passes without seismic");
        bool warned = false;
        for (const auto& warning : demo_report.warnings) {
            warned |= warning.find("演示") != std::string::npos;
        }
        check(warned, "demo model warned as non-production");
    }

    // ---- run parameters carry the spec verbatim ---------------------------
    {
        pwb::prediction::PredictionRunSpec spec;
        spec.model_version_id = "mver_tiled";
        spec.seismic_resource_id = "res_seis";
        spec.well_resource_ids = {"res_w1", "res_w2"};
        spec.params["tile_inline"] = 48;
        const Json parameters =
            pwb::closure_science::run_parameters_from_spec(spec);
        check(parameters["_run_spec"].is_object(),
              "parameters embed the verbatim spec");
        std::vector<std::string> errors;
        const auto parsed =
            pwb::prediction::PredictionRunSpec::from_json(
                parameters["_run_spec"], errors);
        check(parsed.has_value() && errors.empty(), "embedded spec parses");
        check(parsed.has_value() && *parsed == spec,
              "embedded spec equals the edited spec (one contract)");
        check(parameters["well_log_resource_ids"].size() == 2,
              "well resource ids recorded");
        check(parameters["seismic_resource_ids"].size() == 1,
              "seismic resource id recorded");
    }

    // ---- the spec reaches the PROVIDER through execute_run ----------------
    // (the '_' prefix keeps _run_spec out of the snapshot hash and the
    // persisted envelope — execute_run must forward it explicitly or the
    // UI-edited params silently run at kernel defaults while the run row
    // still records them as provenance).
    {
        namespace fs = std::filesystem;
        const fs::path dir =
            fs::temp_directory_path() /
            ("closure_science_runspec_" +
             std::to_string(get_pid()));
        fs::remove_all(dir);
        fs::create_directories(dir);
        const fs::path project_file = dir / "runspec.paleo.json";
        fs::create_directories(dir / "runspec.artifacts");
        auto project_document =
            pwb::project::ProjectDocument::create_new("runspec", "");
        pwb::project::ProjectManager manager(project_file);
        const auto saved = manager.save(project_document);
        check(saved.is_ok(), "project save");
        if (!saved.is_ok()) {
            std::printf("closure_science.run_spec_service: FATAL save\n");
            return 2;
        }
        auto opened = pwb::catalog::open_catalog(project_file);
        check(opened.is_ok(), "catalog opens");
        if (!opened.is_ok()) return 2;
        pwb::catalog::CatalogServiceCore core(std::move(opened.value()));
        const pwb::catalog::SaveHook save_hook =
            [&core](const pwb::catalog::DirtySet& dirty) {
                return core.save(dirty);
            };
        const auto seeded = pwb::closure_science::ensure_default_models(
            core.document(), save_hook);
        check(seeded.code == pwb::domain::ErrorCode::Ok,
              "default models seeded");
        const auto demo_version = pwb::catalog::get_model_version(
            core.document(), pwb::closure_science::kModelIdDemo, "1");
        check(demo_version.is_ok(), "demo version resolvable");

        pwb::prediction::PredictionRunSpec spec;
        spec.model_version_id = demo_version.value()->id;
        spec.params = pwb::prediction::default_prediction_params();
        spec.params["tile_inline"] = 48;
        spec.params["prefer_gpu"] = true;

        Json captured_parameters;
        bool provider_invoked = false;
        pwb::closure_science::ProviderRegistry registry;
        registry.register_provider(
            "demo",
            [&captured_parameters, &provider_invoked](
                const Json&, Json parameters,
                const std::function<bool()>&) -> pwb::domain::Result<Json> {
                captured_parameters = parameters;
                provider_invoked = true;
                return pwb::closure_science::make_demo_facies_provider()(
                    Json::object(), std::move(parameters),
                    [] { return false; });
            });

        auto run = pwb::closure_science::start_inference(
            core.document(), save_hook,
            {spec.model_version_id, {},
             pwb::closure_science::run_parameters_from_spec(spec)});
        check(run.is_ok(), "start_inference ok");
        if (!run.is_ok()) return 2;
        pwb::closure_science::ExecuteRunDeps deps;
        deps.save = save_hook;
        deps.providers = &registry;
        deps.project_dir = dir;
        deps.artifacts_root = dir / "runspec.artifacts";
        const auto outcome = pwb::closure_science::execute_run(
            core.document(), deps, run.value().id.str());
        check(outcome.is_ok(), "execute_run ok: " +
                                   (outcome.is_ok()
                                        ? std::string()
                                        : outcome.error().message));
        check(provider_invoked, "provider invoked");
        check(captured_parameters.contains("_run_spec") &&
                  captured_parameters["_run_spec"].is_object(),
              "_run_spec forwarded to the provider");
        if (captured_parameters.contains("_run_spec")) {
            check(captured_parameters["_run_spec"]["params"]
                          ["tile_inline"]
                              .get<long long>() == 48,
                  "edited tile_inline reached the provider verbatim");
        }
        check(outcome.is_ok() &&
                  outcome.value().run.status == "complete",
              "run completed (status=" +
                  (outcome.is_ok() ? outcome.value().run.status
                                   : outcome.error().message) +
                  ")");
        fs::remove_all(dir);
    }

    if (g_failures == 0) {
        std::printf("closure_science.run_spec_service: %d checks passed\n",
                    g_checks);
        return 0;
    }
    std::printf("closure_science.run_spec_service: %d/%d checks FAILED\n",
                g_failures, g_checks);
    return 1;
}
