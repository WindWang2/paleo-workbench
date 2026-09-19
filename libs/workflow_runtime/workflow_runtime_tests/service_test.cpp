// CONV-33 轮2 — workflow service/orchestrator 冻结 oracle replay（A4）。
//
// Replays the fixtures frozen by the REAL Python implementation:
//   argv[1] = workflow_service_oracle.json
//             (tools/oracle/generate_workflow_service_fixtures.py)
//   argv[2] = workflow_orchestrator_oracle.json（缺省从 argv[1] 同目录推导）
//             (tools/oracle/generate_workflow_orchestrator_fixtures.py)
//
// Scenario inputs are rebuilt independently on the C++ side (Json seam
// views + a fixture CatalogRepository mirroring the generator's
// FakeCatalog); the fixture files are the only shared artifacts.
// Comparison = pwb::domain::json_semantically_equal (semantic JSON
// equality; the computed side is round-tripped through dump/parse to
// collapse number spellings exactly like Python's json serialization).
//
// Tail of main(): negative self-check — tampered expectations MUST fail
// the comparator (proves the replay is not vacuously green).
//
// Boundary notes (33-impl-a4.md):
//  - "freshness_service": "check_integrity" / "boom" markers rebuild the
//    injection manually (the frozen header exposes no check_integrity /
//    throwing-service knob; Python injected those via kwargs).
//  - The orchestrator prerequisite-rejection case is frozen with
//    "cpp_replay": false — the frozen C++ contract has no cursor setter
//    and owns its project by value (D8), so the branch is Python-only
//    reachable there; the replay reports it as an acknowledged boundary.

#include <pwb/domain/json.hpp>
#include <pwb/workflow_runtime/catalog_seam.hpp>
#include <pwb/workflow_runtime/current_context.hpp>
#include <pwb/workflow_runtime/freshness.hpp>
#include <pwb/workflow_runtime/orchestrator.hpp>
#include <pwb/workflow_runtime/recompute_plan.hpp>
#include <pwb/workflow_runtime/service.hpp>
#include <pwb/workflow_graph/graph.hpp>

#include <algorithm>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <memory>
#include <optional>
#include <set>
#include <stdexcept>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

namespace {

using pwb::domain::Json;
using pwb::workflow_graph::DataRunRef;
using pwb::workflow_graph::DataVersionRef;
using pwb::workflow_graph::DependencyGraph;
using pwb::workflow_runtime::AssetRecord;
using pwb::workflow_runtime::CatalogRepository;
using pwb::workflow_runtime::CurrentProjectVersionContext;
using pwb::workflow_runtime::FreshnessService;
using pwb::workflow_runtime::RunRecord;
using pwb::workflow_runtime::VersionRecord;
using pwb::workflow_runtime::WorkflowOrchestrator;
using pwb::workflow_runtime::WorkflowStepContext;

int failures = 0;
int checks = 0;
int skipped = 0;

// --------------------------------------------------------- fixture io --

Json read_fixture(const char* path) {
    std::ifstream in(path);
    if (!in) {
        throw std::runtime_error(std::string("cannot open fixture: ") + path);
    }
    Json data;
    try {
        in >> data;
    } catch (const std::exception& exc) {
        throw std::runtime_error(std::string("fixture parse error: ") +
                                 exc.what());
    }
    return data;
}

bool equals(const Json& got, const Json& expect) {
    return pwb::domain::json_semantically_equal(got, expect);
}

void report_mismatch(const std::string& id, const Json& got,
                     const Json& expect) {
    const auto diff = pwb::domain::json_semantic_diff(got, expect);
    std::printf("FAIL %s at %s: %s\n  got:    %s\n  expect: %s\n",
                id.c_str(), diff.path.c_str(), diff.reason.c_str(),
                got.dump().c_str(), expect.dump().c_str());
    ++failures;
}

// Python-json-normalized comparison (int/float spelling collapse).
bool compare_value(const std::string& id, const Json& got_in,
                   const Json& expect) {
    ++checks;
    const Json got = Json::parse(got_in.dump());
    if (!equals(got, expect)) {
        report_mismatch(id, got, expect);
        return false;
    }
    return true;
}

// ------------------------------------------------- fixture catalog ----
// Mirrors the generator's FakeCatalog: listing order = spec order;
// resolve_version may explode (audit #847-3 probe case).

class FixtureCatalog : public CatalogRepository {
public:
    explicit FixtureCatalog(const Json& spec) {
        fail_listing_ = spec.value("fail_listing", false);
        resolve_boom_ = spec.value("resolve_boom", false);
        for (const Json& ver : spec.value("versions", Json::array())) {
            VersionRecord record;
            record.asset_id = ver.value("asset_id", std::string());
            record.version_id = ver.value("version_id", std::string());
            record.name = ver.value("name", std::string());
            if (ver.contains("producing_run_id") &&
                ver.at("producing_run_id").is_string()) {
                record.producing_run_id =
                    ver.at("producing_run_id").get<std::string>();
            }
            record.checksum = ver.value("checksum", std::string());
            record.trashed = ver.value("trashed", false);
            record.path = ver.value("path", std::string());
            record.created_at =
                ver.value("created_at", std::string("2026-01-01T00:00:00"));
            versions_.push_back(std::move(record));
        }
        for (const Json& run : spec.value("runs", Json::array())) {
            RunRecord record;
            record.run_id = run.value("run_id", std::string());
            record.operation = run.value("operation", std::string());
            for (const Json& id : run.value("input_version_ids",
                                            Json::array())) {
                record.input_version_ids.push_back(id.get<std::string>());
            }
            for (const Json& id : run.value("output_version_ids",
                                            Json::array())) {
                record.output_version_ids.push_back(id.get<std::string>());
            }
            if (run.contains("generator_version") &&
                run.at("generator_version").is_string()) {
                record.generator_version =
                    run.at("generator_version").get<std::string>();
            }
            record.status = run.value("status", std::string("running"));
            if (run.contains("started_at") &&
                run.at("started_at").is_string()) {
                record.started_at = run.at("started_at").get<std::string>();
            }
            if (run.contains("finished_at") &&
                run.at("finished_at").is_string()) {
                record.finished_at = run.at("finished_at").get<std::string>();
            }
            if (run.contains("domain_task_id") &&
                run.at("domain_task_id").is_string()) {
                record.domain_task_id =
                    run.at("domain_task_id").get<std::string>();
            }
            if (run.contains("input_snapshot_hash") &&
                run.at("input_snapshot_hash").is_string()) {
                record.input_snapshot_hash =
                    run.at("input_snapshot_hash").get<std::string>();
            }
            runs_.push_back(std::move(record));
        }
    }

    std::vector<AssetRecord> list_assets() override {
        maybe_fail_listing();
        std::vector<AssetRecord> assets;
        for (const VersionRecord& ver : versions_) {
            const auto slot = std::find_if(
                assets.begin(), assets.end(),
                [&ver](const AssetRecord& asset) {
                    return asset.id == ver.asset_id;
                });
            if (slot == assets.end()) {
                AssetRecord asset;
                asset.id = ver.asset_id;
                asset.name = ver.name;
                asset.type = "fixture";
                asset.format = "json";
                assets.push_back(std::move(asset));
            }
        }
        return assets;
    }

    std::optional<AssetRecord> resolve_asset(
        const std::string& asset_id) override {
        for (const AssetRecord& asset : list_assets()) {
            if (asset.id == asset_id) {
                return asset;
            }
        }
        return std::nullopt;
    }

    std::vector<VersionRecord> list_versions(
        const std::string& asset_id) override {
        maybe_fail_listing();
        std::vector<VersionRecord> out;
        for (const VersionRecord& ver : versions_) {
            if (ver.asset_id == asset_id) {
                out.push_back(ver);
            }
        }
        return out;
    }

    std::optional<VersionRecord> resolve_version(
        const std::string& version_id) override {
        if (resolve_boom_) {
            throw std::runtime_error("catalog backend exploded");
        }
        for (const VersionRecord& ver : versions_) {
            if (ver.version_id == version_id) {
                return ver;
            }
        }
        return std::nullopt;
    }

    std::vector<RunRecord> list_runs() override {
        maybe_fail_listing();
        return runs_;
    }

    std::optional<RunRecord> resolve_run(const std::string& run_id) override {
        for (const RunRecord& run : runs_) {
            if (run.run_id == run_id) {
                return run;
            }
        }
        return std::nullopt;
    }

    std::string register_run(
        const std::string&, const std::vector<std::string>&, const Json&,
        const std::optional<std::string>&, const std::string&,
        const std::optional<std::string>&, const std::optional<std::string>&,
        const std::optional<std::string>&) override {
        throw std::logic_error("fixture catalog: register_run unused");
    }
    pwb::workflow_runtime::RegisteredAssetVersion register_result_asset(
        const std::string&, const std::string&, const std::string&,
        const Json&, const std::string&, const std::string&,
        const std::string&, const Json&) override {
        throw std::logic_error(
            "fixture catalog: register_result_asset unused");
    }
    std::string register_version(const std::string&, const std::string&,
                                 const std::string&,
                                 const std::vector<std::string>&,
                                 const std::string&,
                                 const Json&) override {
        throw std::logic_error("fixture catalog: register_version unused");
    }
    void update_run_status(const std::string&, const std::string&) override {
        throw std::logic_error("fixture catalog: update_run_status unused");
    }
    void attach_run_output(const std::string&, const std::string&) override {
        throw std::logic_error("fixture catalog: attach_run_output unused");
    }
    void set_current_version(const std::string&,
                             const std::string&) override {
        throw std::logic_error("fixture catalog: set_current_version unused");
    }
    std::optional<std::string> verify_integrity(const std::string&) override {
        return std::nullopt;
    }

    // Listing views for the manual composition builder.
    [[nodiscard]] const std::vector<VersionRecord>& listed_versions() const {
        return versions_;
    }
    [[nodiscard]] const std::vector<RunRecord>& listed_runs() const {
        return runs_;
    }

private:
    void maybe_fail_listing() {
        if (fail_listing_) {
            throw std::runtime_error("catalog listing exploded");
        }
    }

    std::vector<VersionRecord> versions_;
    std::vector<RunRecord> runs_;
    bool fail_listing_ = false;
    bool resolve_boom_ = false;
};

// ------------------------------------- manual service compositions -----
// The frozen service header exposes no check_integrity / throwing-seam
// knob; the fixture marks those scenarios with "freshness_service":
// "check_integrity" | "boom" and the replay rebuilds the injected
// service from the same catalog spec (same shape the library
// composition builds).

struct ManualComposition {
    DependencyGraph graph;
    FreshnessService::VersionLookup versions;
    CurrentProjectVersionContext context{};
    pwb::workflow_runtime::CatalogSeam seam{};
    std::shared_ptr<FixtureCatalog> keep_alive;  // seam lambda state
    std::unique_ptr<FreshnessService> service;
};

std::unique_ptr<ManualComposition> build_manual_service(const Json& spec,
                                                         bool boom,
                                                         bool check_integrity) {
    auto bundle = std::make_unique<ManualComposition>();
    bundle->keep_alive = std::make_shared<FixtureCatalog>(spec);
    const FixtureCatalog& catalog = *bundle->keep_alive;

    std::vector<DataVersionRef> graph_versions;
    for (const VersionRecord& ver : catalog.listed_versions()) {
        graph_versions.push_back(DataVersionRef{ver.asset_id, ver.version_id,
                                                ver.name,
                                                ver.producing_run_id});
        bundle->versions[ver.version_id] = ver;
    }
    std::vector<DataRunRef> graph_runs;
    for (const RunRecord& run : catalog.listed_runs()) {
        graph_runs.push_back(
            DataRunRef{run.run_id, run.operation, run.input_version_ids,
                       run.output_version_ids, run.parameters,
                       run.generator_version, run.status, run.started_at,
                       run.finished_at, run.domain_task_id,
                       run.input_snapshot_hash});
    }
    bundle->graph = DependencyGraph::from_listings(graph_versions, graph_runs);

    // last-tip-per-asset context (same inference the library composition
    // applies; mirrors Python resolve with service=None).
    std::vector<std::string> asset_order;
    std::map<std::string, std::vector<const VersionRecord*>> by_asset;
    for (const VersionRecord& ver : catalog.listed_versions()) {
        if (by_asset.find(ver.asset_id) == by_asset.end()) {
            asset_order.push_back(ver.asset_id);
        }
        by_asset[ver.asset_id].push_back(&ver);
    }
    for (const std::string& asset : asset_order) {
        auto vers = by_asset[asset];
        std::sort(vers.begin(), vers.end(),
                  [](const VersionRecord* a, const VersionRecord* b) {
                      return std::tie(a->created_at, a->version_id) <
                             std::tie(b->created_at, b->version_id);
                  });
        bundle->context.select(asset, vers.back()->version_id,
                               vers.back()->name);
    }

    if (boom) {
        bundle->seam.resolve_version =
            [](const std::string&) -> std::optional<VersionRecord> {
            throw std::runtime_error("catalog backend exploded");
        };
    } else {
        std::shared_ptr<FixtureCatalog> shared = bundle->keep_alive;
        bundle->seam.resolve_version =
            [shared](const std::string& id) -> std::optional<VersionRecord> {
            return shared->resolve_version(id);
        };
    }
    bundle->seam.file_exists = [](const std::string& path) {
        std::error_code ec;
        return !path.empty() && std::filesystem::exists(path, ec);
    };
    // The integrity gate in freshness.cpp requires verify_integrity to be
    // installed as well (Python gates on `catalog is not None and
    // hasattr(catalog, "verify_integrity")` — the seam bundle is that
    // presence proxy in C++).
    if (!boom) {
        std::shared_ptr<FixtureCatalog> shared = bundle->keep_alive;
        bundle->seam.verify_integrity =
            [shared](const std::string& id) -> std::optional<std::string> {
            return shared->verify_integrity(id);
        };
    }
    bundle->service = std::make_unique<FreshnessService>(
        bundle->graph, bundle->context, bundle->versions, bundle->seam,
        check_integrity);
    return bundle;
}

// ------------------------------------------------------ home helpers --

std::set<std::string> preexisting_step_ids(const Json& project) {
    std::set<std::string> ids;
    const auto runs = project.find("compilation_runs");
    if (runs == project.end() || !runs->is_array() || runs->empty()) {
        return ids;
    }
    const Json& run = runs->back();
    if (!run.is_object()) {
        return ids;
    }
    const auto steps = run.find("workflow_steps");
    if (steps == run.end() || !steps->is_array()) {
        return ids;
    }
    for (const Json& step : *steps) {
        const auto id = step.find("id");
        if (id != step.end() && id->is_string()) {
            ids.insert(id->get<std::string>());
        }
    }
    return ids;
}

void strip_unpredictable_ids(Json& steps_array,
                             const std::set<std::string>& preexisting) {
    for (Json& step : steps_array) {
        const auto id = step.find("id");
        const bool known = id != step.end() && id->is_string() &&
                           preexisting.count(id->get<std::string>()) > 0;
        if (!known && id != step.end()) {
            step.erase("id");
        }
    }
}

Json steps_array_json(
    const std::vector<pwb::project::WorkflowStep>& steps) {
    Json out = Json::array();
    for (const pwb::project::WorkflowStep& step : steps) {
        out.push_back(step.to_dict());
    }
    return out;
}

Json runs_after_json(const Json& project,
                     const std::set<std::string>& preexisting) {
    Json runs = Json::array();
    const auto it = project.find("compilation_runs");
    if (it != project.end() && it->is_array()) {
        runs = *it;
    }
    for (Json& run : runs) {
        const auto steps = run.find("workflow_steps");
        if (steps != run.end() && steps->is_array()) {
            strip_unpredictable_ids(*steps, preexisting);
        }
    }
    return runs;
}

// ------------------------------------------------------ clock setup --

pwb::project::ModelClock counter_clock(int start) {
    pwb::project::ModelClock clock;
    clock.now_iso = [] { return std::string("2026-01-01T00:00:00+00:00"); };
    clock.make_id = [start](std::string_view prefix) mutable {
        ++start;
        char tail[16];
        std::snprintf(tail, sizeof(tail), "%012d", start);
        return std::string(prefix) + "_" + tail;
    };
    return clock;
}

// ---------------------------------------------------- service replay --

Json replay_service_case(const Json& scenario) {
    const std::string fn = scenario.at("fn").get<std::string>();
    const Json& input = scenario.at("input");

    if (fn == "service.create_compilation_run") {
        Json project = input.at("project");
        pwb::project::ModelClock clock =
            counter_clock(input.value("id_counter_start", 0));
        pwb::project::CompilationRun run =
            pwb::workflow_runtime::create_compilation_run(
                project, input.at("name").get<std::string>(),
                input.at("target_horizon").get<std::string>(),
                input.at("sequence_scheme").get<std::string>(), clock);
        Json out = Json::object();
        out["run"] = run.to_dict();
        out["stratigraphy_after"] = project.at("stratigraphy");
        out["compilation_runs_after"] = project.at("compilation_runs");
        return out;
    }

    if (fn == "service.infer_workflow_step_status") {
        // Family shapes (input keys decide):
        //  a) project + steps[]                  -> {step: status}
        //  b) step + matrix[[status...]]         -> per-entry result
        //  c) cases[{id, project}] (qc matrix)   -> [{id, qc}]
        //  d) project_empty/project_with_products + steps -> nested
        //  e) project + step (+catalog/+flags)   -> single status string
        if (input.contains("cases")) {
            Json results = Json::array();
            for (const Json& entry : input.at("cases")) {
                Json result = Json::object();
                result["id"] = entry.at("id");
                result["qc"] = pwb::workflow_runtime::
                    infer_workflow_step_status(entry.at("project"), "qc");
                results.push_back(std::move(result));
            }
            return results;
        }
        if (input.contains("matrix")) {
            const std::string step = input.at("step").get<std::string>();
            const char* section =
                step == "factor_map" ? "factor_map_tasks" : "prediction_tasks";
            Json results = Json::array();
            for (const Json& statuses : input.at("matrix")) {
                Json project = Json::object();
                Json tasks = Json::array();
                for (const Json& status : statuses) {
                    Json task = Json::object();
                    task["status"] = status;
                    tasks.push_back(std::move(task));
                }
                project[section] = std::move(tasks);
                Json result = Json::object();
                result[step] = pwb::workflow_runtime::
                    infer_workflow_step_status(project, step);
                results.push_back(std::move(result));
            }
            return results;
        }
        if (input.contains("project_empty")) {
            Json out = Json::object();
            Json empty = Json::object();
            Json with_products = Json::object();
            for (const Json& step : input.at("steps")) {
                const std::string name = step.get<std::string>();
                empty[name] = pwb::workflow_runtime::
                    infer_workflow_step_status(input.at("project_empty"),
                                               name);
                with_products[name] = pwb::workflow_runtime::
                    infer_workflow_step_status(
                        input.at("project_with_products"), name);
            }
            out["empty"] = std::move(empty);
            out["with_products"] = std::move(with_products);
            return out;
        }
        if (input.contains("steps")) {
            Json out = Json::object();
            for (const Json& step : input.at("steps")) {
                const std::string name = step.get<std::string>();
                out[name] = pwb::workflow_runtime::
                    infer_workflow_step_status(input.at("project"), name);
            }
            return out;
        }

        // single-step overlay shape
        pwb::workflow_runtime::StepStatusOptions options;
        std::unique_ptr<FixtureCatalog> catalog;
        std::unique_ptr<ManualComposition> manual;
        const bool fail_listing =
            input.contains("catalog") &&
            input.at("catalog").value("fail_listing", false);
        if (input.contains("catalog") && !fail_listing) {
            catalog = std::make_unique<FixtureCatalog>(input.at("catalog"));
            options.catalog = catalog.get();
        }
        if (input.contains("apply_freshness")) {
            options.apply_freshness =
                input.at("apply_freshness").get<bool>();
        }
        if (input.contains("freshness_service")) {
            const std::string marker =
                input.at("freshness_service").get<std::string>();
            if (marker == "check_integrity") {
                manual =
                    build_manual_service(input.at("catalog"), false, true);
                options.freshness_service = manual->service.get();
            } else if (marker == "boom") {
                manual =
                    build_manual_service(input.at("catalog"), true, false);
                options.freshness_service = manual->service.get();
            }
        }
        return pwb::workflow_runtime::infer_workflow_step_status(
            input.at("project"), input.at("step").get<std::string>(),
            options);
    }

    if (fn == "service.home_workflow_steps") {
        Json project = input.at("project");
        const std::set<std::string> preexisting =
            preexisting_step_ids(project);
        pwb::workflow_runtime::StepStatusOptions options;
        std::unique_ptr<FixtureCatalog> catalog;
        if (input.contains("catalog")) {
            catalog = std::make_unique<FixtureCatalog>(input.at("catalog"));
            options.catalog = catalog.get();
        }
        const std::vector<pwb::project::WorkflowStep> steps =
            pwb::workflow_runtime::home_workflow_steps(project, options);
        Json steps_json = steps_array_json(steps);
        strip_unpredictable_ids(steps_json, preexisting);
        Json out = Json::object();
        out["steps"] = std::move(steps_json);
        out["compilation_runs_after"] = runs_after_json(project, preexisting);
        return out;
    }

    if (fn == "service.build_affected_products_plan") {
        std::unique_ptr<FixtureCatalog> catalog;
        if (input.contains("catalog")) {
            catalog = std::make_unique<FixtureCatalog>(input.at("catalog"));
        }
        std::optional<std::vector<std::string>> changed;
        if (input.contains("changed_version_ids")) {
            changed.emplace();
            for (const Json& id : input.at("changed_version_ids")) {
                changed->push_back(id.get<std::string>());
            }
        }
        pwb::workflow_runtime::RecomputePlan plan =
            pwb::workflow_runtime::build_affected_products_plan(
                input.at("project"), changed, catalog.get());
        return plan.to_dict();
    }

    if (fn == "service.downstream_impact_for_version") {
        std::unique_ptr<FixtureCatalog> catalog;
        if (input.contains("catalog")) {
            catalog = std::make_unique<FixtureCatalog>(input.at("catalog"));
        }
        return pwb::workflow_runtime::downstream_impact_for_version(
            input.at("version_id").get<std::string>(),
            input.contains("project") ? &input.at("project") : nullptr,
            catalog.get());
    }

    if (fn == "service.dashboard_state") {
        return pwb::workflow_runtime::dashboard_state(input.at("project"));
    }

    throw std::runtime_error("unknown service fn: " + fn);
}

// ---------------------------------------------- orchestrator replay --

Json context_to_json(const WorkflowStepContext& context) {
    Json out = Json::object();
    out["step_id"] = context.step_id;
    out["step_name"] = context.step_name;
    out["index"] = context.index;
    out["total_steps"] = context.total_steps;
    out["is_valid"] = context.is_valid;
    Json prereqs = Json::array();
    for (const std::string& prereq : context.prerequisites) {
        prereqs.push_back(prereq);
    }
    out["prerequisites"] = std::move(prereqs);
    out["status"] = context.status;
    return out;
}

Json transition_to_json(
    const pwb::workflow_runtime::StepTransitionResult& result,
    int index_after) {
    Json out = Json::object();
    out["success"] = result.success;
    out["message"] = result.message;
    out["step_context"] = context_to_json(result.step_context);
    out["index_after"] = index_after;
    return out;
}

Json replay_orchestrator_case(const Json& input) {
    Json project = input.contains("project") && input.at("project").is_object()
                       ? input.at("project")
                       : Json::object();
    WorkflowOrchestrator orchestrator(std::move(project));
    Json results = Json::array();
    for (const Json& call : input.at("calls")) {
        if (call.is_string() && call.get<std::string>() == "ctx") {
            results.push_back(
                context_to_json(orchestrator.get_step_context()));
            continue;
        }
        if ((call.is_string() && call.get<std::string>() == "next") ||
            (call.is_object() && call.contains("next_payload"))) {
            // Python's step_payload is accepted but ignored (L81); C++
            // omits the parameter entirely (D4) — same observable.
            const pwb::workflow_runtime::StepTransitionResult result =
                orchestrator.next_step();
            results.push_back(transition_to_json(
                result, orchestrator.current_step_index()));
            continue;
        }
        if (call.is_object() && call.contains("set_index")) {
            throw std::logic_error(
                "set_index is only present in cpp_replay=false cases");
        }
        throw std::logic_error("unknown orchestrator call");
    }
    return results;
}

// ------------------------------------------------------- replay loop --

struct ReplayOutcome {
    std::string id;
    Json got;
};

std::vector<ReplayOutcome> replay_fixture(const Json& fixture) {
    std::vector<ReplayOutcome> outcomes;
    for (const Json& scenario : fixture.at("cases")) {
        const std::string id = scenario.at("id").get<std::string>();
        // The generator freezes the replayability marker inside input.
        const Json& input = scenario.at("input");
        const bool cpp_replay =
            scenario.value("cpp_replay", input.value("cpp_replay", true));
        if (!cpp_replay) {
            ++skipped;
            std::printf(
                "SKIP %s — %s\n", id.c_str(),
                input.value("cpp_boundary", std::string("python-only case"))
                    .c_str());
            continue;
        }
        const Json got =
            scenario.at("fn").get<std::string>() == "orchestrator.sequence"
                ? replay_orchestrator_case(scenario.at("input"))
                : replay_service_case(scenario);
        const Json& expect = scenario.at("expect");
        if (expect.contains("raise")) {
            // No frozen case raises through this surface; guard loudly if
            // one ever appears (raise parity would need plumbing here).
            report_mismatch(id, got, expect);
            continue;
        }
        // create_compilation_run cases freeze their payload at the top
        // level of expect (run / *_after); every other fn nests under
        // "result".
        const Json& expected =
            expect.contains("result") ? expect.at("result") : expect;
        compare_value(id, got, expected);
        outcomes.push_back(ReplayOutcome{id, got});
    }
    return outcomes;
}

template <typename Range>
const ReplayOutcome* find_outcome(const Range& outcomes,
                                  const std::string& id) {
    for (const ReplayOutcome& outcome : outcomes) {
        if (outcome.id == id) {
            return &outcome;
        }
    }
    return nullptr;
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "usage: workflow_runtime_service_test "
                     "<service-oracle.json> [orchestrator-oracle.json]\n";
        return 2;
    }
    const Json service_fixture = read_fixture(argv[1]);
    std::string orchestrator_path;
    if (argc >= 3) {
        orchestrator_path = argv[2];
    } else {
        const std::filesystem::path dir =
            std::filesystem::path(argv[1]).parent_path();
        orchestrator_path =
            (dir / "workflow_orchestrator_oracle.json").string();
    }
    const Json orchestrator_fixture =
        read_fixture(orchestrator_path.c_str());

    const std::vector<ReplayOutcome> service_outcomes =
        replay_fixture(service_fixture);
    const std::vector<ReplayOutcome> orchestrator_outcomes =
        replay_fixture(orchestrator_fixture);

    // ------------------------------------------- negative self-check --
    // Tampered expectations MUST fail the comparator (fields across both
    // fixtures). A green replay that cannot go red is worthless.
    const auto tamper_check = [](const std::string& note, const Json& got,
                                 const Json& tampered) {
        const Json normalized = Json::parse(got.dump());
        if (equals(normalized, tampered)) {
            std::printf(
                "FAIL negative self-check (%s): comparator accepted a "
                "tampered expectation\n",
                note.c_str());
            ++failures;
        } else {
            ++checks;
            std::printf("ok   negative self-check: %s caught\n",
                        note.c_str());
        }
    };
    if (const ReplayOutcome* outcome =
            find_outcome(service_outcomes, "home_sticky_vs_stale_overlay")) {
        Json tampered = Json::parse(outcome->got.dump());
        tampered["steps"][2]["status"] = "warning";  // frozen: complete
        tamper_check("home sticky: prediction status tampered", outcome->got,
                     tampered);
    } else {
        std::printf("FAIL negative self-check: outcome missing\n");
        ++failures;
    }
    if (const ReplayOutcome* outcome =
            find_outcome(service_outcomes, "dashboard_full_shape")) {
        Json tampered = Json::parse(outcome->got.dump());
        tampered["workflow_complete_count"] =
            tampered["workflow_complete_count"].get<int>() + 1;
        tamper_check("dashboard: complete count tampered", outcome->got,
                     tampered);
    } else {
        std::printf("FAIL negative self-check: outcome missing\n");
        ++failures;
    }
    if (const ReplayOutcome* outcome =
            find_outcome(service_outcomes, "overlay_factor_map_stale")) {
        tamper_check("overlay: stale tampered to complete", outcome->got,
                     Json("complete"));  // frozen: stale
    } else {
        std::printf("FAIL negative self-check: outcome missing\n");
        ++failures;
    }
    if (const ReplayOutcome* outcome =
            find_outcome(orchestrator_outcomes, "full_walk_to_completion")) {
        Json tampered = Json::parse(outcome->got.dump());
        tampered[3]["message"] = "已成功切换至第 4 步 [古地理图编绘!]";
        tamper_check("orchestrator: advancement message tampered",
                     outcome->got, tampered);
    } else {
        std::printf("FAIL negative self-check: outcome missing\n");
        ++failures;
    }

    std::printf(
        "\nservice/orchestrator replay: %d checks, %d skipped "
        "(documented boundary), %d failures\n",
        checks, skipped, failures);
    return failures == 0 ? 0 : 1;
}
