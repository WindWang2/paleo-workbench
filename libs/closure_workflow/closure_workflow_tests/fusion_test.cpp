// cpp-close-02 — frozen-oracle replay for the integrated compilation
// consumer (integrated_compilation.cpp vs the REAL Python
// workflow.integrated_compilation + the CONV-24 fusion kernel).
//
// The fixture carries the full scenario inputs (evidence set, portable
// project tree, deterministic 2x2 grids) so the C++ replay rebuilds
// everything independently: the grids feed the typed host seams exactly
// like the generator's live-cache/patched-reader injection. Full-summary
// comparison for the degraded / pin-mismatch runs; verbatim refusal
// messages; the register case compares the honest registration outcome
// (the C++ rail shape differs structurally from Python's create_derived —
// documented divergence — so only the registration dict is compared).

#include <pwb/closure_workflow/integrated_compilation.hpp>
#include <pwb/domain/json.hpp>

#include <cstdio>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {

using pwb::domain::Json;
using pwb::factor_fusion::FactorGrid;
using pwb::factor_fusion::Normalization;

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

// Canonicalize integer kinds to Python-parse semantics (json.loads yields
// unsigned ints): signed/unsigned are the same JSON int, but some frozen
// expectations ride number_unsigned while C++ ints serialize signed.
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
    const bool ok = pwb::domain::json_semantically_equal(got_c, expect_c);
    std::string detail;
    if (!ok) {
        const auto diff = pwb::domain::json_semantic_diff(got_c, expect_c);
        detail = diff.path + " (" + diff.reason + ") got=" +
                 got_c.dump().substr(0, 300);
    }
    check(id, ok, detail);
}

FactorGrid grid_from(const Json& node) {
    FactorGrid grid;
    grid.height = node.value("height", 0);
    grid.width = node.value("width", 0);
    for (const Json& cell : node.at("grid_z")) {
        grid.grid_z.push_back(cell.is_null()
                                  ? std::numeric_limits<float>::quiet_NaN()
                                  : static_cast<float>(cell.get<double>()));
    }
    for (const Json& v : node.at("grid_x")) {
        grid.grid_x.push_back(v.get<double>());
    }
    for (const Json& v : node.at("grid_y")) {
        grid.grid_y.push_back(v.get<double>());
    }
    grid.factor_name = node.value("factor_name", std::string());
    grid.algorithm_id = node.value("algorithm_id", std::string());
    grid.algorithm_parameters = node.value("algorithm_parameters", Json::object());
    const Json& crs = node.at("crs");
    if (crs.is_string()) grid.crs = crs.get<std::string>();
    const Json& unit = node.at("unit");
    if (unit.is_string()) grid.unit = unit.get<std::string>();
    for (const Json& ref : node.at("source_refs")) {
        grid.source_refs.push_back(ref.get<std::string>());
    }
    const Json& run = node.at("run_ref");
    if (run.is_string()) grid.run_ref = run.get<std::string>();
    const Json& variance = node.at("variance_grid");
    if (variance.is_array()) {
        std::vector<float> cells;
        for (const Json& cell : variance) {
            cells.push_back(cell.is_null()
                                ? std::numeric_limits<float>::quiet_NaN()
                                : static_cast<float>(cell.get<double>()));
        }
        grid.variance_grid = std::move(cells);
    }
    return grid;
}

std::vector<std::pair<std::string, std::string>> evidence_from(const Json& node) {
    std::vector<std::pair<std::string, std::string>> evidence;
    for (const Json& pair : node) {
        evidence.emplace_back(pair.at(0).get<std::string>(),
                              pair.at(1).get<std::string>());
    }
    return evidence;
}

// Host seams serving the fixture's grids (the C++ counterpart of the
// generator's live-cache + patched-reader injection).
struct SeamHost {
    std::map<std::string, FactorGrid> by_task;
    std::map<std::string, FactorGrid> pinned;

    pwb::closure_workflow::IntegratedGridSeams seams() const {
        pwb::closure_workflow::IntegratedGridSeams s;
        s.grid_from_version =
            [this](const std::string& vid) -> std::optional<FactorGrid> {
            const auto it = pinned.find(vid);
            return it == pinned.end() ? std::nullopt
                                      : std::optional<FactorGrid>(it->second);
        };
        s.grid_for_task =
            [this](const Json& task) -> std::optional<FactorGrid> {
            const auto it = by_task.find(task.value("id", std::string()));
            return it == by_task.end() ? std::nullopt
                                       : std::optional<FactorGrid>(it->second);
        };
        return s;
    }
};

std::string error_message(const std::function<void()>& body) {
    try {
        body();
    } catch (const std::invalid_argument& exc) {
        return exc.what();
    } catch (const std::exception& exc) {
        return std::string("<") + exc.what() + ">";
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
        for (const Json& scenario : fixture.at("cases")) {
            const std::string id = scenario.at("id").get<std::string>();
            const Json& input = scenario.at("input");
            const Json& expected = scenario.at("expected");

            if (id == "model_default" || id == "model_explicit") {
                SeamHost host;
                for (auto it = input.at("grids").begin();
                     it != input.at("grids").end(); ++it) {
                    host.by_task[it.key()] = grid_from(it.value());
                }
                Json project = input.at("project");
                const auto evidence = evidence_from(input.at("evidence"));
                const auto grids = pwb::closure_workflow::
                    fusion_inputs_from_document(project, evidence, nullptr,
                                                nullptr, host.seams());
                const pwb::factor_fusion::FusionModel model =
                    id == "model_default"
                        ? pwb::closure_workflow::build_fusion_model(
                              evidence, grids)
                        : pwb::closure_workflow::build_fusion_model(
                              evidence, grids,
                              std::map<std::string, double>{
                                  {"factor_1", 0.75}, {"factor_2", 0.25}},
                              std::nullopt, pwb::closure_workflow::
                                                kDefaultFusionDefaultClass,
                              std::vector<std::string>{"低", "中", "高"},
                              std::vector<double>{0.4, 0.8},
                              pwb::closure_workflow::kDefaultFusionModelName,
                              Json{{"decided_by", "专家评审"},
                                   {"reason", Json(nullptr)}});
                check_json(id + ".model", model.to_dict(),
                           expected.at("model"));
                check_json(id + ".fingerprint", Json(model.fingerprint()),
                           expected.at("fingerprint"));
                continue;
            }

            if (id == "run_degraded" || id == "pin_mismatch") {
                SeamHost host;
                for (auto it = input.at("grids").begin();
                     it != input.at("grids").end(); ++it) {
                    host.by_task[it.key()] = grid_from(it.value());
                }
                if (id == "pin_mismatch") {
                    // The pinned factor_1 grid rides the catalog seam; the
                    // task's live grid is NOT its evidence pin.
                    host.pinned["ver_grid1"] = host.by_task.at("factor_1");
                }
                Json project = input.at("project");
                const auto evidence = evidence_from(input.at("evidence"));
                std::vector<std::string> mismatches;
                const auto grids = pwb::closure_workflow::
                    fusion_inputs_from_document(project, evidence,
                                                &mismatches, nullptr,
                                                host.seams());
                const auto run = pwb::closure_workflow::run_integrated_fusion(
                    project, evidence, nullptr, host.seams(),
                    std::nullopt, std::nullopt, std::nullopt, std::nullopt,
                    /*register_output=*/false);
                if (id == "pin_mismatch") {
                    check_json(id + ".mismatches", mismatches,
                               expected.at("mismatches"));
                }
                check_json(id + ".summary", run.summary,
                           expected.at("summary"));
                continue;
            }

            if (id == "register") {
                SeamHost host;
                for (auto it = input.at("grids").begin();
                     it != input.at("grids").end(); ++it) {
                    host.by_task[it.key()] = grid_from(it.value());
                }
                Json project = input.at("project");
                const auto evidence = evidence_from(input.at("evidence"));
                // Deterministic fake catalog: every registration returns
                // the frozen version id (the generator's double did too).
                class FakeRegCatalog
                    : public pwb::workflow_runtime::CatalogRepository {
                public:
                    std::vector<pwb::workflow_runtime::AssetRecord>
                    list_assets() override {
                        return {};
                    }
                    std::optional<pwb::workflow_runtime::AssetRecord>
                    resolve_asset(const std::string&) override {
                        return std::nullopt;
                    }
                    std::vector<pwb::workflow_runtime::VersionRecord>
                    list_versions(const std::string&) override {
                        return {};
                    }
                    std::optional<pwb::workflow_runtime::VersionRecord>
                    resolve_version(const std::string&) override {
                        return std::nullopt;
                    }
                    std::vector<pwb::workflow_runtime::RunRecord>
                    list_runs() override {
                        return {};
                    }
                    std::optional<pwb::workflow_runtime::RunRecord>
                    resolve_run(const std::string&) override {
                        return std::nullopt;
                    }
                    std::string register_run(const std::string&,
                                             const std::vector<std::string>&,
                                             const Json&,
                                             const std::optional<std::string>&,
                                             const std::string&,
                                             const std::optional<std::string>&,
                                             const std::optional<std::string>&,
                                             const std::optional<std::string>&)
                        override {
                        return "run_fusion";
                    }
                    pwb::workflow_runtime::RegisteredAssetVersion
                    register_result_asset(const std::string&, const std::string&,
                                          const std::string&, const Json&,
                                          const std::string&, const std::string&,
                                          const std::string&, const Json&)
                        override {
                        return {"asset_fusion", "ver_fusion_1"};
                    }
                    std::string register_version(const std::string&,
                                                 const std::string&,
                                                 const std::string&,
                                                 const std::vector<std::string>&,
                                                 const std::string&,
                                                 const Json&) override {
                        return "ver_fusion_1";
                    }
                    void update_run_status(const std::string&,
                                           const std::string&) override {}
                    void set_current_version(const std::string&,
                                             const std::string&) override {}
                    std::optional<std::string> verify_integrity(
                        const std::string&) override {
                        return std::nullopt;
                    }
                    void attach_run_output(const std::string&,
                                           const std::string&) override {}
                };
                FakeRegCatalog catalog;
                const auto run = pwb::closure_workflow::run_integrated_fusion(
                    project, evidence, &catalog, host.seams(),
                    std::nullopt, std::nullopt, std::nullopt, std::nullopt,
                    true);
                check_json(id + ".registration",
                           run.summary.at("qc").at("registration"),
                           expected.at("summary").at("qc").at("registration"));
                check_json(id + ".registered", run.summary.at("registered"),
                           expected.at("summary").at("registered"));
                check_json(id + ".catalog_version_id",
                           run.summary.at("catalog_version_id"),
                           expected.at("summary").at("catalog_version_id"));
                continue;
            }

            // Verbatim refusal cases.
            if (id == "unfrozen_input_set") {
                // Needs a REAL document with an unfrozen active input set;
                // the frozen message is replayed through a direct refusal
                // probe on the C++ gate: build the document Json the C++
                // active_input_set reads as unfrozen.
                Json document = Json::object();
                Json set = Json::object();
                set["id"] = "set_1";
                set["active"] = true;  // active_input_set keys on `active`
                set["frozen"] = false;
                set["entries"] = Json::array();
                Json sets = Json::array();
                sets.push_back(set);
                document["compilation_input_sets"] = sets;
                SeamHost host;
                const std::string got = error_message([&] {
                    (void)pwb::closure_workflow::run_integrated_fusion(
                        document, {}, nullptr, host.seams());
                });
                check(id + ".message",
                      got == expected.at("error").at("message").get<std::string>(),
                      "got=" + got);
                continue;
            }
            if (id == "unresolvable_factor") {
                // Mirror the generator's scenario: factor_1 resolves (its
                // task exists), only factor_x's task is missing.
                Json document = Json::object();
                Json task = Json::object();
                task["id"] = "factor_1";
                task["name"] = "物源综合";
                task["grid_artifact_version_id"] = "ver_grid1";
                Json tasks = Json::array();
                tasks.push_back(task);
                document["factor_map_tasks"] = std::move(tasks);
                SeamHost host;
                host.by_task["factor_1"] = FactorGrid{};  // resolvable
                const auto evidence = evidence_from(input.at("evidence"));
                std::vector<std::string> mismatches;
                const std::string got = error_message([&] {
                    (void)pwb::closure_workflow::fusion_inputs_from_document(
                        document, evidence, &mismatches, nullptr,
                        host.seams());
                });
                check(id + ".message",
                      got == expected.at("error").at("message").get<std::string>(),
                      "got=" + got);
                continue;
            }
            if (id == "unknown_weight" || id == "constant_grid_normalization") {
                // Both flow through build_fusion_model; the frozen message
                // is replayed via the C++ resolver directly.
                const std::string message =
                    expected.at("error").at("message").get<std::string>();
                std::string got;
                if (id == "unknown_weight") {
                    // Rebuild the two-factor loading the generator ran so
                    // the available-task list matches verbatim.
                    std::map<std::string, FactorGrid> grids;
                    FactorGrid g1 = grid_from(
                        fixture.at("cases").at(0).at("input").at("grids").at(
                            "factor_1"));
                    FactorGrid g2 = grid_from(
                        fixture.at("cases").at(0).at("input").at("grids").at(
                            "factor_2"));
                    grids.emplace("factor_1", std::move(g1));
                    grids.emplace("factor_2", std::move(g2));
                    const auto evidence =
                        evidence_from(input.at("evidence"));
                    got = error_message([&] {
                        (void)pwb::closure_workflow::build_fusion_model(
                            evidence, grids,
                            std::map<std::string, double>{{"nope", 1.0}});
                    });
                    check(id + ".message", got == message, "got=" + got);
                    continue;
                }
                // constant grid: force the degenerate-range branch.
                FactorGrid constant;
                constant.height = 2;
                constant.width = 2;
                constant.grid_z = {0.5f, 0.5f, 0.5f, 0.5f};
                constant.factor_name = "物源综合";
                constant.algorithm_id = "idw";
                std::map<std::string, FactorGrid> grids{{"factor_1", constant}};
                const auto evidence =
                    std::vector<std::pair<std::string, std::string>>{
                        {"物源", "factor:factor_1:ver_1"}};
                got = error_message([&] {
                    (void)pwb::closure_workflow::build_fusion_model(evidence,
                                                                    grids);
                });
                check(id + ".message",
                      got == message, "got=" + got);
                continue;
            }

            check(id + ".unknown_case", false, "no replay handler");
        }
    } catch (const std::exception& exc) {
        std::printf("FATAL %s\n", exc.what());
        return 1;
    }
    std::printf("closure_workflow.fusion: %d checks, %d failures\n", checks,
                failures);
    return failures == 0 ? 0 : 1;
}
