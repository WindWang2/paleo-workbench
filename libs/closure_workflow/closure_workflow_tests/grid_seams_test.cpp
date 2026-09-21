// V14-COMPILATION-PUBLISH — production fusion grid seams.
//
// The integrated-compilation fusion documents its byte-loading seams as
// host responsibilities. This battery proves the production implementation
// (grid_seams) really loads grids:
//   * decode_grid_artifact round-trips encode_grid_artifact (NaN cells,
//     variance, provenance, axes) and refuses malformed payloads;
//   * grid_from_version resolves a PINNED catalog version through a real
//     CatalogRepository;
//   * a fusion runs end-to-end through the production seams (frozen input
//     set → pin resolution → fuse → catalog registration), and a missing
//     pin still fails closed (never a silent substitute).

#include <pwb/closure_workflow/grid_seams.hpp>
#include <pwb/closure_workflow/integrated_compilation.hpp>
#include <pwb/factor_fusion/factor_grid.hpp>
#include <pwb/workflow_runtime/catalog_seam.hpp>

#include <cmath>
#include <cstdio>
#include <limits>
#include <optional>
#include <string>
#include <vector>

namespace {

int g_failures = 0;
int g_checks = 0;

void check(const std::string& id, bool ok, const std::string& detail = "") {
    ++g_checks;
    if (!ok) {
        ++g_failures;
        std::fprintf(stderr, "FAIL: %s %s\n", id.c_str(), detail.c_str());
    }
}

using pwb::closure_workflow::IntegratedGridSeams;
using pwb::domain::Json;
using pwb::factor_fusion::FactorGrid;

FactorGrid sample_grid() {
    FactorGrid grid;
    grid.width = 3;
    grid.height = 2;
    grid.grid_z = {1.0f, 2.0f, 3.0f, 4.0f,
                   std::numeric_limits<float>::quiet_NaN(), 6.0f};
    grid.grid_x = {0.0, 1.0, 2.0};
    grid.grid_y = {0.0, 1.0};
    grid.factor_name = "物源";
    grid.algorithm_id = "constrained_idw";
    grid.algorithm_parameters = Json::object();
    grid.algorithm_parameters["power"] = 2.0;
    grid.crs = "EPSG:4326";
    grid.unit = "index";
    grid.generator_version = "factor-v1";
    grid.run_ref = "run_000001";
    grid.source_refs = {"ver_raw_1", "ver_raw_2"};
    grid.variance_grid = std::vector<float>{0.1f, 0.2f, 0.3f, 0.4f, 0.5f, 0.6f};
    return grid;
}

bool grids_equal(const FactorGrid& a, const FactorGrid& b) {
    if (a.width != b.width || a.height != b.height) return false;
    if (a.grid_z.size() != b.grid_z.size()) return false;
    for (std::size_t i = 0; i < a.grid_z.size(); ++i) {
        const bool a_nan = std::isnan(a.grid_z[i]);
        const bool b_nan = std::isnan(b.grid_z[i]);
        if (a_nan != b_nan) return false;
        if (!a_nan && a.grid_z[i] != b.grid_z[i]) return false;
    }
    if (a.grid_x != b.grid_x || a.grid_y != b.grid_y) return false;
    if (a.factor_name != b.factor_name || a.algorithm_id != b.algorithm_id) return false;
    if (a.crs != b.crs || a.unit != b.unit) return false;
    if (a.generator_version != b.generator_version || a.run_ref != b.run_ref) {
        return false;
    }
    if (a.source_refs != b.source_refs) return false;
    if (a.variance_grid.has_value() != b.variance_grid.has_value()) return false;
    if (a.variance_grid.has_value() && *a.variance_grid != *b.variance_grid) return false;
    return true;
}

std::string error_message(const std::function<void()>& fn) {
    try {
        fn();
    } catch (const std::invalid_argument& ex) {
        return ex.what();
    } catch (const std::runtime_error& ex) {
        return ex.what();
    }
    return "<no error>";
}

// ---------------------------------------------------------------- decode

void decode_battery() {
    const FactorGrid grid = sample_grid();
    const std::string payload =
        pwb::closure_workflow::encode_grid_artifact(grid, "index");
    const auto decoded = pwb::closure_workflow::decode_grid_artifact(payload);
    check("decode.roundtrip", decoded.has_value() && grids_equal(grid, *decoded));

    // A non-object / non-JSON payload refuses.
    check("decode.not_json",
          !pwb::closure_workflow::decode_grid_artifact("not json").has_value());
    check("decode.not_object",
          !pwb::closure_workflow::decode_grid_artifact("[1,2,3]").has_value());
    // Wrong artifact kind.
    check("decode.wrong_kind",
          !pwb::closure_workflow::decode_grid_artifact(
              R"({"artifact_kind":"something_else"})")
               .has_value());
    // Ragged grid arrays refuse (no silent truncation).
    {
        Json artifact = Json::parse(payload);
        artifact["grid_z"] = Json::array({1.0, 2.0});
        check("decode.ragged_cells",
              !pwb::closure_workflow::decode_grid_artifact(artifact.dump())
                   .has_value());
    }
    // A non-numeric, non-"NaN" cell refuses.
    {
        Json artifact = Json::parse(payload);
        artifact["grid_z"][0] = Json("oops");
        check("decode.bad_cell",
              !pwb::closure_workflow::decode_grid_artifact(artifact.dump())
                   .has_value());
    }
    // Missing / bad axes refuse.
    {
        Json artifact = Json::parse(payload);
        artifact.erase("grid_x");
        check("decode.missing_axes",
              !pwb::closure_workflow::decode_grid_artifact(artifact.dump())
                   .has_value());
    }
    // Degenerate dimensions refuse.
    {
        Json artifact = Json::parse(payload);
        artifact["width"] = 0;
        check("decode.zero_width",
              !pwb::closure_workflow::decode_grid_artifact(artifact.dump())
                   .has_value());
    }
}

// ------------------------------------------------- catalog-backed loading

void catalog_battery() {
    pwb::workflow_runtime::RuntimeStore store;
    const FactorGrid grid = sample_grid();
    const std::string payload =
        pwb::closure_workflow::encode_grid_artifact(grid, "index");
    const auto registered = store.register_result_asset(
        "grid-asset", "factor_grid", "json", Json::object(), payload, "output",
        "run_000001", Json::object());
    const std::string version_id = registered.version_id;

    // grid_from_version resolves through the repository.
    const auto loaded =
        pwb::closure_workflow::load_grid_from_version(&store, version_id);
    check("catalog.load", loaded.has_value() && grids_equal(grid, *loaded));
    // Unknown version → nullopt (a refusal, never a substitute).
    check("catalog.unknown_version",
          !pwb::closure_workflow::load_grid_from_version(&store, "ver_missing")
               .has_value());
    // A null catalog refuses.
    check("catalog.null_catalog",
          !pwb::closure_workflow::load_grid_from_version(nullptr, version_id)
               .has_value());
    // A version whose payload is not a grid artifact refuses.
    const auto text_registered = store.register_result_asset(
        "text-asset", "document", "txt", Json::object(), "just text", "output",
        "run_000002", Json::object());
    const std::string text_version = text_registered.version_id;
    check("catalog.non_grid_payload",
          !pwb::closure_workflow::load_grid_from_version(&store, text_version)
               .has_value());

    // make_production_grid_seams: the pin seam resolves; without a live
    // resolver the current-grid lookup refuses honestly.
    const IntegratedGridSeams seams =
        pwb::closure_workflow::make_production_grid_seams(&store);
    check("seams.pin", seams.grid_from_version(version_id).has_value());
    // grid_for_task is always installed: the task's persisted catalog
    // artifact is the first level (Python's npz artifact equivalent).
    Json persisted_task = Json::object();
    persisted_task["id"] = "factor_1";
    persisted_task["grid_artifact_version_id"] = version_id;
    const auto current = seams.grid_for_task(persisted_task);
    check("seams.current_from_catalog",
          current.has_value() && grids_equal(grid, *current));
    // A task with no persisted artifact and no live resolver refuses.
    Json bare_task = Json::object();
    bare_task["id"] = "factor_2";
    check("seams.no_live_resolver", !seams.grid_for_task(bare_task).has_value());
}

// --------------------------------------------- production fusion path

void fusion_battery() {
    // A frozen input set pinning one factor task, the pinned grid in the
    // catalog: the real production path (freeze gate → pin → fuse →
    // register).
    pwb::workflow_runtime::RuntimeStore store;
    const FactorGrid grid = sample_grid();
    const auto registered = store.register_result_asset(
        "grid-asset", "factor_grid", "json", Json::object(),
        pwb::closure_workflow::encode_grid_artifact(grid, "index"), "output",
        "run_000001", Json::object());
    const std::string version_id = registered.version_id;

    Json document = Json::object();
    Json task = Json::object();
    task["id"] = "factor_1";
    task["name"] = "物源";
    task["grid_artifact_version_id"] = version_id;
    Json tasks = Json::array();
    tasks.push_back(task);
    document["factor_map_tasks"] = std::move(tasks);

    Json entry = Json::object();
    entry["kind"] = "factor";
    entry["task_id"] = "factor_1";
    entry["version_id"] = version_id;
    Json entries = Json::array();
    entries.push_back(entry);
    Json set = Json::object();
    set["id"] = "set_1";
    set["active"] = true;
    set["frozen"] = true;
    set["entries"] = std::move(entries);
    Json sets = Json::array();
    sets.push_back(set);
    document["compilation_input_sets"] = std::move(sets);

    const std::string evidence_value = "factor:factor_1:" + version_id;
    const std::vector<std::pair<std::string, std::string>> evidence = {
        {"物源", evidence_value}};

    const IntegratedGridSeams seams =
        pwb::closure_workflow::make_production_grid_seams(&store);
    const auto output = pwb::closure_workflow::run_integrated_fusion(
        document, evidence, &store, seams);
    check("fusion.registered",
          output.summary.value("registered", false),
          "the production seams registered the fusion product");
    check("fusion.catalog_version_id",
          !output.summary.value("catalog_version_id", std::string()).empty());
    // The run lands completed (#1219 discipline): a death between the two
    // saves would leave a failed run, never a completed ghost.
    bool run_completed = false;
    for (const auto& run : store.runs()) {
        if (run.operation == "factor_fusion") run_completed = run.status == "complete";
    }
    check("fusion.run_completed", run_completed, "status=" + [&] {
        std::string last;
        for (const auto& run : store.runs()) {
            if (run.operation == "factor_fusion") last = run.status;
        }
        return last;
    }());
    // The fusion's registered artifact is itself decodable (the lineage
    // round-trips through the same seam).
    const std::string fusion_version =
        output.summary.value("catalog_version_id", std::string());
    const auto fusion_grid =
        pwb::closure_workflow::load_grid_from_version(&store, fusion_version);
    check("fusion.artifact_decodable", fusion_grid.has_value());
    // The likelihood grid keeps the input geometry.
    check("fusion.result_geometry",
          fusion_grid.has_value() && fusion_grid->width == grid.width &&
              fusion_grid->height == grid.height);

    // A pin that is not in the catalog fails closed — no silent current
    // substitution.
    Json stale_document = document;
    Json stale_set = stale_document["compilation_input_sets"][0];
    stale_set["entries"][0]["version_id"] = "ver_missing";
    stale_document["compilation_input_sets"][0] = stale_set;
    const std::vector<std::pair<std::string, std::string>> stale_evidence = {
        {"物源", "factor:factor_1:ver_missing"}};
    const std::string message = error_message([&] {
        (void)pwb::closure_workflow::run_integrated_fusion(
            stale_document, stale_evidence, &store, seams);
    });
    check("fusion.missing_pin_refuses",
          message.find("factor_1") != std::string::npos &&
              !message.empty(),
          "got=" + message);

    // A null catalog refuses registration rather than faking a version pin.
    const auto degraded = pwb::closure_workflow::run_integrated_fusion(
        document, evidence, nullptr, seams);
    check("fusion.no_catalog_honest",
          !degraded.summary.value("registered", true) &&
              degraded.summary.value("catalog_version_id", std::string()).empty());
}

}  // namespace

int main() {
    decode_battery();
    catalog_battery();
    fusion_battery();
    std::printf("%d/%d checks passed\n", g_checks - g_failures, g_checks);
    if (g_failures != 0) {
        std::fprintf(stderr, "%d FAILURES\n", g_failures);
        return 1;
    }
    std::printf("grid seams battery: PASS\n");
    return 0;
}
