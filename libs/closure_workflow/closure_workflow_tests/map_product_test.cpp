// cpp-close-02 — frozen-oracle replay for the map-product catalog OUTPUT
// orchestration (map_product.cpp vs paleo_workbench.workflow.map_product).
//
// Cases (tools/oracle/generate_closure_map_product_fixtures.py): byte-exact
// scientific fingerprints, the assemble registration flow (RUNNING booking
// → complete, #1219), the fail-closed refusal matrix (verbatim messages),
// failed output registration → failed run, lifecycle (clone/review/
// freeze/staleness/compare/supersede) and rerun supersession.
//
// The C++ fake catalog mirrors the generator's deterministic double:
// sequential ids, content sha256 checksums, call recording. Record ids /
// timestamps ride an injected project::ModelClock whose sequential
// counter mirrors the generator's process-global factory (cases replay
// in fixture order — the ids self-verify against the frozen expectations).

#include <pwb/closure_workflow/map_product.hpp>
#include <pwb/domain/json.hpp>
#include <pwb/domain/sha256.hpp>
#include <pwb/workflow_runtime/catalog_seam.hpp>

#include <algorithm>
#include <cstdio>
#include <fstream>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using pwb::domain::Json;
using pwb::closure_workflow::MapProductAssembly;
using pwb::closure_workflow::MapProductResult;
using pwb::workflow_runtime::AssetRecord;
using pwb::workflow_runtime::RegisteredAssetVersion;
using pwb::workflow_runtime::RunRecord;
using pwb::workflow_runtime::VersionRecord;

int failures = 0;
int checks = 0;

Json read_fixture(const char* path) {
    std::ifstream in(path);
    if (!in) throw std::runtime_error(std::string("cannot open: ") + path);
    Json data;
    in >> data;
    return data;
}

bool equals(const Json& left, const Json& right) {
    return pwb::domain::json_semantically_equal(left, right);
}

// Canonicalize integer kinds (json.loads ints are unsigned; C++ ints
// serialize signed — same JSON int, one canonical kind for compares).
void canonicalize_ints(Json& node) {
    if (node.is_number_integer() && !node.is_number_float()) {
        const std::int64_t value = node.get<std::int64_t>();
        node = Json(static_cast<std::uint64_t>(value));
        return;
    }
    if (node.is_object()) {
        for (auto it = node.begin(); it != node.end(); ++it) canonicalize_ints(*it);
    } else if (node.is_array()) {
        for (auto it = node.begin(); it != node.end(); ++it) canonicalize_ints(*it);
    }
}

void check(const std::string& id, bool ok, const std::string& detail = "") {
    ++checks;
    if (!ok) {
        ++failures;
        std::printf("FAIL %s%s%s\n", id.c_str(), detail.empty() ? "" : ": ",
                    detail.c_str());
    }
}

void check_json(const std::string& id, const Json& got, const Json& expect) {
    Json got_c = got;
    Json expect_c = expect;
    canonicalize_ints(got_c);
    canonicalize_ints(expect_c);
    const bool ok = equals(got_c, expect_c);
    std::string detail;
    if (!ok) {
        const auto diff = pwb::domain::json_semantic_diff(got_c, expect_c);
        detail = diff.path + " (" + diff.reason + ") got=" +
                 got_c.dump().substr(0, 300) + " expect=" +
                 expect_c.dump().substr(0, 300);
    }
    check(id, ok, detail);
}

// ---------------------------------------------------------------- clock --

struct FrozenClock {
    int next_id = 0;
    pwb::project::ModelClock clock() {
        pwb::project::ModelClock c;
        c.now_iso = [] { return std::string("2026-01-01T00:00:00+00:00"); };
        c.make_id = [this](std::string_view prefix) {
            ++next_id;
            char buffer[32];
            std::snprintf(buffer, sizeof buffer, "_frozen%03d", next_id);
            return std::string(prefix) + buffer;
        };
        return c;
    }
};

// ----------------------------------------------------------- fake catalog --

class FakeCatalog : public pwb::workflow_runtime::CatalogRepository {
public:
    bool fail_output = false;
    Json runs = Json::array();
    Json assets = Json::array();
    Json versions = Json::array();
    int seq = 0;

    std::vector<AssetRecord> list_assets() override { return {}; }
    std::optional<AssetRecord> resolve_asset(const std::string&) override {
        return std::nullopt;
    }
    std::vector<VersionRecord> list_versions(const std::string&) override {
        return {};
    }
    std::vector<RunRecord> list_runs() override { return {}; }
    std::optional<VersionRecord> resolve_version(
        const std::string& version_id) override {
        for (const Json& node : versions) {
            if (node.at("id").get<std::string>() == version_id) {
                VersionRecord record;
                record.version_id = version_id;
                record.asset_id =
                    node.value("asset_id", std::string());
                // The Python double's get_version returns a DICT — its
                // sha256 attribute is unreadable, so compare's output
                // hashes degrade to None. Mirror that shape here.
                record.checksum = std::string();
                return record;
            }
        }
        return std::nullopt;
    }
    std::optional<RunRecord> resolve_run(const std::string& run_id) override {
        for (const Json& run : runs) {
            if (run.at("id").get<std::string>() == run_id) {
                RunRecord record;
                record.run_id = run_id;
                return record;
            }
        }
        return std::nullopt;
    }

    std::string register_run(const std::string& operation,
                             const std::vector<std::string>& input_version_ids,
                             const Json& parameters,
                             const std::optional<std::string>& generator,
                             const std::string& status,
                             const std::optional<std::string>& = std::nullopt,
                             const std::optional<std::string>& = std::nullopt,
                             const std::optional<std::string>& = std::nullopt)
        override {
            ++seq;
            Json run = Json::object();
            run["id"] = "run_" + pad(seq);
            run["operation"] = operation;
            run["input_version_ids"] = input_version_ids;
            run["parameters"] = parameters;
            run["generator"] =
                generator.has_value() ? Json(*generator) : Json(nullptr);
            run["status"] = status;
            runs.push_back(std::move(run));
            return runs.back()["id"].get<std::string>();
    }

    RegisteredAssetVersion register_result_asset(
        const std::string& name, const std::string& type,
        const std::string& format, const Json& asset_metadata,
        const std::string& payload_json, const std::string& stage,
        const std::string& run_id, const Json& version_metadata) override {
        if (fail_output) {
            throw std::runtime_error("catalog write refused");
        }
        // ONE increment shared by asset + version — the generator's
        // double allocates exactly the same ids.
        ++seq;
        Json asset = Json::object();
        asset["id"] = "asset_" + pad(seq);
        asset["name"] = name;
        asset["type"] = type;
        asset["format"] = format;
        asset["asset_metadata"] = asset_metadata;
        assets.push_back(std::move(asset));
        Json version = Json::object();
        version["id"] = "ver_" + pad(seq);
        version["asset_id"] = assets.back()["id"];
        version["name"] = name;
        version["stage"] = stage;
        version["run_id"] = run_id;
        version["sha256"] = pwb::domain::Sha256::of_bytes(payload_json);
        version["version_metadata"] = version_metadata;
        versions.push_back(std::move(version));
        return {assets.back()["id"].get<std::string>(),
                versions.back()["id"].get<std::string>()};
    }

    std::string register_version(const std::string& asset_id,
                                 const std::string& payload_json,
                                 const std::string& stage,
                                 const std::vector<std::string>& parents,
                                 const std::string& run_id,
                                 const Json& metadata) override {
        ++seq;
        Json version = Json::object();
        version["id"] = "ver_" + pad(seq);
        version["asset_id"] = asset_id;
        version["stage"] = stage;
        version["run_id"] = run_id;
        version["sha256"] = pwb::domain::Sha256::of_bytes(payload_json);
        version["parent_version_ids"] = parents;
        version["version_metadata"] = metadata;
        versions.push_back(std::move(version));
        return versions.back()["id"].get<std::string>();
    }

    void update_run_status(const std::string& run_id,
                           const std::string& status) override {
        for (Json& run : runs) {
            if (run.at("id").get<std::string>() == run_id) {
                run["status"] = status;
                return;
            }
        }
        throw std::runtime_error("unknown run " + run_id);
    }
    void update_run_status(const std::string& run_id,
                           const std::string& status,
                           const Json& extra_parameters) override {
        for (Json& run : runs) {
            if (run.at("id").get<std::string>() == run_id) {
                run["status"] = status;
                run["extra_parameters"] = extra_parameters;
                return;
            }
        }
        throw std::runtime_error("unknown run " + run_id);
    }
    void set_current_version(const std::string&,
                             const std::string&) override {}
    std::optional<std::string> verify_integrity(const std::string&) override {
        return std::nullopt;
    }
    void attach_run_output(const std::string&,
                           const std::string&) override {}

    [[nodiscard]] Json snapshot() const {
        Json out = Json::object();
        out["runs"] = runs;
        out["assets"] = assets;
        out["versions"] = versions;
        return out;
    }

    [[nodiscard]] std::string pad_public() { return pad(seq); }

private:
    static std::string pad(int value) {
        char buffer[16];
        std::snprintf(buffer, sizeof buffer, "%06d", value);
        return buffer;
    }
};

// --------------------------------------------------------------- helpers --

MapProductAssembly assembly_from(const Json& node) {
    MapProductAssembly assembly;
    assembly.product_name = node.value("product_name", std::string());
    // Refusal scenarios carry partial recipe dicts — every read defaults.
    const Json kEmpty = Json::array();
    const Json& factor_ids =
        node.contains("factor_task_ids") && node.at("factor_task_ids").is_array()
            ? node.at("factor_task_ids")
            : kEmpty;
    for (const Json& id : factor_ids) {
        assembly.factor_task_ids.push_back(id.get<std::string>());
    }
    const Json& refs =
        node.contains("interpretation_refs") &&
                node.at("interpretation_refs").is_array()
            ? node.at("interpretation_refs")
            : kEmpty;
    for (const Json& ref : refs) {
        assembly.interpretation_refs.push_back(ref.get<std::string>());
    }
    const Json& composition = node.contains("composition_ref")
                                  ? node.at("composition_ref")
                                  : kEmpty;
    if (composition.is_string()) {
        assembly.composition_ref = composition.get<std::string>();
    }
    if (node.contains("notes")) assembly.notes = node.value("notes", std::string());
    if (node.contains("manual_adjustments")) {
        assembly.manual_adjustments = node.at("manual_adjustments");
    }
    if (node.contains("fusion_version_id")) {
        assembly.fusion_version_id = node.value("fusion_version_id", std::string());
    }
    if (node.contains("integrated_interpretation_id")) {
        assembly.integrated_interpretation_id =
            node.value("integrated_interpretation_id", std::string());
    }
    if (node.contains("input_set_id")) {
        assembly.input_set_id = node.value("input_set_id", std::string());
    }
    return assembly;
}

std::string expect_error(const std::function<void()>& body) {
    try {
        body();
    } catch (const std::invalid_argument& exc) {
        return exc.what();
    } catch (const std::exception& exc) {
        return std::string("RuntimeError: ") + exc.what();
    }
    return "<no error raised>";
}

std::string runtime_error_message(const std::function<void()>& body) {
    try {
        body();
    } catch (const std::exception& exc) {
        return std::string("RuntimeError: ") + exc.what();
    }
    return "<no error raised>";
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 2) {
        std::fprintf(stderr, "usage: %s <fixture.json>\n", argv[0]);
        return 2;
    }
    try {
        const Json fixture = read_fixture(argv[1]);
        FrozenClock frozen_clock;
        for (const Json& scenario : fixture.at("cases")) {
            const std::string id = scenario.at("id").get<std::string>();
            const Json& input = scenario.at("input");
            const Json& expected = scenario.at("expected");

            if (id == "fingerprint") {
                MapProductAssembly assembly = assembly_from(input.at("assembly"));
                check_json(id + ".fingerprint",
                           Json(assembly.scientific_fingerprint(
                               input.at("project"))),
                           expected.at("scientific_fingerprint"));
                continue;
            }

            if (id.rfind("refuse_", 0) == 0) {
                MapProductAssembly assembly =
                    assembly_from(input.at("assembly"));
                Json project = input.at("project");
                FakeCatalog* catalog_ptr = nullptr;
                FakeCatalog catalog;
                // The refusal cases pass catalog=None except where the
                // fixture's expected error implies a catalog: only the
                // payload/catalog gates distinguish. Mirror the generator:
                // catalog present unless the frozen message says otherwise.
                const std::string message =
                    expected.at("error").at("message").get<std::string>();
                if (message !=
                    "map product assembly requires the data catalog") {
                    catalog_ptr = &catalog;
                }
                const Json& payload_node = input.at("payload");
                std::string payload =
                    payload_node.is_string()
                        ? payload_node.get<std::string>()
                        : std::string();
                const std::string got = expect_error([&] {
                    pwb::closure_workflow::AssembleDeps deps;
                    deps.catalog = catalog_ptr;
                    deps.payload_json = payload;
                    deps.clock = frozen_clock.clock();
                    Json scratch = project;
                    (void)pwb::closure_workflow::assemble_map_product(
                        scratch, assembly, deps);
                });
                check(id + ".message", got == message,
                      "got=" + got + " expect=" + message);
                continue;
            }

            if (id == "assemble" || id == "failed_output_registration") {
                MapProductAssembly assembly =
                    assembly_from(input.at("assembly"));
                Json project = input.at("project");
                FakeCatalog catalog;
                catalog.fail_output = id == "failed_output_registration";
                pwb::closure_workflow::AssembleDeps deps;
                deps.catalog = &catalog;
                deps.payload_json = input.value("payload", "");
                deps.clock = frozen_clock.clock();
                MapProductResult result;
                std::string runtime_error;
                try {
                    result = pwb::closure_workflow::assemble_map_product(
                        project, assembly, deps);
                } catch (const std::exception& exc) {
                    runtime_error =
                        std::string("RuntimeError: ") + exc.what();
                }
                if (id == "assemble") {
                    Json result_json = Json::object();
                    result_json["product_name"] = result.product_name;
                    result_json["record_id"] = result.record_id;
                    result_json["output_version_id"] = result.output_version_id;
                    result_json["run_id"] = result.run_id;
                    result_json["scientific_fingerprint"] =
                        result.scientific_fingerprint;
                    result_json["superseded_record_id"] =
                        result.superseded_record_id.has_value()
                            ? Json(*result.superseded_record_id)
                            : Json(nullptr);
                    check_json(id + ".result", result_json,
                               expected.at("result"));
                } else {
                    check(id + ".error",
                          runtime_error == expected.at("error").get<std::string>(),
                          "got=" + runtime_error);
                }
                check_json(id + ".catalog", catalog.snapshot(),
                           expected.at("catalog"));
                check_json(id + ".map_products", project.at("map_products"),
                           expected.at("map_products"));
                continue;
            }

            if (id == "lifecycle") {
                Json project = input.at("project");
                FakeCatalog catalog;
                // Grid versions pre-registered by the generator — two seq
                // draws per grid (asset + version), same as its helper.
                for (const char* vid : {"ver_grid1", "ver_grid2"}) {
                    ++catalog.seq;
                    Json asset = Json::object();
                    asset["id"] = "asset_" + catalog.pad_public();
                    asset["name"] = std::string("grid-") + vid;
                    asset["type"] = "factor_grid";
                    asset["format"] = "npz";
                    asset["asset_metadata"] = Json::object();
                    catalog.assets.push_back(std::move(asset));
                    ++catalog.seq;
                    Json version = Json::object();
                    version["id"] = vid;
                    version["asset_id"] = catalog.assets.back()["id"];
                    version["name"] = std::string("grid-") + vid;
                    version["stage"] = "derived";
                    version["run_id"] = "";
                    version["sha256"] = std::string("grid-") + vid;
                    version["version_metadata"] = Json::object();
                    catalog.versions.push_back(std::move(version));
                }
                // Pre-step (not frozen): assemble + clone + review + freeze
                // consume clock ids exactly like the generator run.
                pwb::closure_workflow::AssembleDeps deps;
                deps.catalog = &catalog;
                deps.payload_json = "{}";
                deps.clock = frozen_clock.clock();
                MapProductAssembly assembly;
                assembly.product_name = "X";
                assembly.factor_task_ids = {"factor_1", "factor_2"};
                (void)pwb::closure_workflow::assemble_map_product(project,
                                                                  assembly,
                                                                  deps);
                Json& record = project.at("map_products").at(0);
                Json clone = pwb::closure_workflow::clone_map_product(
                    record, project, frozen_clock.clock());
                // clone appended → the array reallocated; re-take the
                // record reference before the in-place mutations.
                Json& record2 = project.at("map_products").at(0);
                check(id + ".pre.review", !pwb::closure_workflow::review_map_product(
                                               record2, project, &catalog)
                                               .is_null());
                pwb::closure_workflow::freeze_map_product(record2);
                check(id + ".lifecycle.record",
                      pwb::closure_workflow::effective_lifecycle(record2) ==
                          expected.at("lifecycle").at("record").get<std::string>());
                check(id + ".lifecycle.clone",
                      pwb::closure_workflow::effective_lifecycle(clone) ==
                          expected.at("lifecycle").at("clone").get<std::string>());
                check_json(id + ".stale_before",
                           pwb::closure_workflow::product_staleness(
                               record2, project),
                           expected.at("stale_before"));
                // Re-interpolate factor_1 → new grid version.
                project.at("factor_map_tasks").at(0)["grid_artifact_version_id"] =
                    "ver_grid9";
                check_json(id + ".stale_after",
                           pwb::closure_workflow::product_staleness(
                               record2, project),
                           expected.at("stale_after"));
                check_json(id + ".compare",
                           pwb::closure_workflow::compare_map_products(
                               record2, clone, project, &catalog),
                           expected.at("compare"));
                const std::string supersede_error = expect_error([&] {
                    pwb::closure_workflow::supersede_map_product(record2,
                                                                 clone);
                });
                check(id + ".supersede_error_on_frozen",
                      supersede_error ==
                          expected.at("supersede_error_on_frozen")
                              .get<std::string>(),
                      supersede_error);
                check_json(id + ".map_products", project.at("map_products"),
                           expected.at("map_products"));
                continue;
            }

            if (id == "rerun") {
                Json project = input.at("project");
                FakeCatalog catalog;
                pwb::closure_workflow::AssembleDeps deps;
                deps.catalog = &catalog;
                deps.payload_json = "{}";
                deps.clock = frozen_clock.clock();
                MapProductAssembly assembly;
                assembly.product_name = "X";
                assembly.factor_task_ids = {"factor_1"};
                (void)pwb::closure_workflow::assemble_map_product(project,
                                                                  assembly,
                                                                  deps);
                Json record = project.at("map_products").at(0);
                const MapProductResult result =
                    pwb::closure_workflow::rerun_map_product(project, record,
                                                             deps);
                Json result_json = Json::object();
                result_json["record_id"] = result.record_id;
                result_json["superseded_record_id"] =
                    result.superseded_record_id.has_value()
                        ? Json(*result.superseded_record_id)
                        : Json(nullptr);
                check_json(id + ".result", result_json,
                           expected.at("result"));
                check_json(id + ".map_products", project.at("map_products"),
                           expected.at("map_products"));
                check_json(id + ".catalog", catalog.snapshot(),
                           expected.at("catalog"));
                continue;
            }

            check(id + ".unknown_case", false, "no replay handler");
        }
    } catch (const std::exception& exc) {
        std::printf("FATAL %s\n", exc.what());
        return 1;
    }
    std::printf("closure_workflow.map_product: %d checks, %d failures\n",
                checks, failures);
    return failures == 0 ? 0 : 1;
}
