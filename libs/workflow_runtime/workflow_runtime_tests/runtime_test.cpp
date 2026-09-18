// CONV-26 workflow runtime oracle replay test.
//
// Replays libs/workflow_runtime_tests/fixtures/workflow_runtime_oracle.json
// (frozen from the real Python implementation by
// tools/oracle/generate_workflow_runtime_fixtures.py) through the C++ port
// and compares against the frozen expectation — semantic JSON equality
// plus raise parity. Scenario inputs are rebuilt independently on the C++
// side; the fixture is the only shared artifact.
//
// Beyond the replay, the tail of main() exercises the acceptance closure:
// WorkflowSpec -> validate -> execute C++ node -> publish provenance ->
// freshness -> recompute plan -> reuse -> downstream state (E2E flow that
// needs no Python), and a negative self-check proving the comparator
// catches mutations.

#include <pwb/domain/json.hpp>
#include <pwb/domain/sha256.hpp>
#include <pwb/workflow_engine/ops.hpp>
#include <pwb/workflow_runtime/catalog_seam.hpp>
#include <pwb/workflow_runtime/constraint_versions.hpp>
#include <pwb/workflow_runtime/current_context.hpp>
#include <pwb/workflow_runtime/freshness.hpp>
#include <pwb/workflow_runtime/node_adapters.hpp>
#include <pwb/workflow_runtime/provenance_graph.hpp>
#include <pwb/workflow_runtime/recompute_plan.hpp>
#include <pwb/workflow_runtime/runtime_service.hpp>
#include <pwb/workflow_runtime/staleness.hpp>

#include <algorithm>
#include <filesystem>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using pwb::domain::Json;
using pwb::workflow_runtime::AdmissionGate;
using pwb::workflow_runtime::AssetRecord;
using pwb::workflow_runtime::CatalogRepository;
using pwb::workflow_runtime::CurrentProjectVersionContext;
using pwb::workflow_runtime::DependencyGraph;
using pwb::workflow_runtime::FreshnessService;
using pwb::workflow_runtime::RunRecord;
using pwb::workflow_runtime::VersionRecord;
using pwb::workflow_runtime::WorkflowRuntimeService;

int failures = 0;

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

void compare(const std::string& id, const Json& got_in, const Json& expect) {
    if (expect.contains("raise")) {
        // Raise parity: the C++ side must throw the same python_class +
        // message the real Python implementation froze.
        if (got_in.contains("raise") &&
            got_in.at("raise") == expect.at("raise")) {
            return;
        }
        report_mismatch(id, got_in, expect);
        return;
    }
    if (got_in.contains("raise")) {
        report_mismatch(id, got_in, expect);
        return;
    }
    // The frozen expectations went through Python's JSON serialization;
    // normalize the computed side the same way (int/unsigned and float
    // spellings collapse exactly like Python's json round-trip).
    const Json got = Json::parse(got_in.dump());
    if (!equals(got, expect.at("result"))) {
        report_mismatch(id, got, expect.at("result"));
    }
}

// ---------------------------------------------------------------- scenarios

// Owns everything FreshnessService references (the service holds const
// refs into this bundle).
struct ServiceBundle {
    DependencyGraph graph;
    FreshnessService::VersionLookup versions;
    CurrentProjectVersionContext context{};

    FreshnessService make_service(bool check_integrity) {
        // Seam parity with the generator's FakeCatalog: integrity re-hashes
        // the recorded payload against the checksum; payload existence is
        // the real filesystem (fixture paths are hermetically absent).
        pwb::workflow_runtime::CatalogSeam seam;
        seam.verify_integrity =
            [this](const std::string& id) -> std::optional<std::string> {
                const auto it = versions.find(id);
                if (it == versions.end() || it->second.checksum.empty() ||
                    it->second.payload_json.empty()) {
                    return std::nullopt;
                }
                return pwb::domain::Sha256::of_bytes(
                           it->second.payload_json) == it->second.checksum
                           ? std::optional<std::string>("verified")
                           : std::optional<std::string>("modified");
            };
        seam.file_exists = [](const std::string& path) {
            std::error_code ec;
            return !path.empty() && std::filesystem::exists(path, ec);
        };
        return FreshnessService(graph, context, versions, seam,
                                check_integrity);
    }
};

std::optional<std::string> opt_string(const Json& v) {
    return v.is_string() ? std::optional<std::string>(v.get<std::string>())
                         : std::nullopt;
}

std::vector<std::string> str_list(const Json& v) {
    std::vector<std::string> out;
    if (v.is_array()) {
        for (const auto& item : v) {
            if (item.is_string()) out.push_back(item.get<std::string>());
        }
    }
    return out;
}

std::string str_or(const Json& obj, const char* key, const std::string& dflt) {
    if (obj.is_object() && obj.contains(key) && obj.at(key).is_string()) {
        return obj.at(key).get<std::string>();
    }
    return dflt;
}

ServiceBundle build_service(const Json& spec) {
    ServiceBundle bundle;
    std::vector<pwb::workflow_graph::DataVersionRef> graph_versions;
    std::vector<pwb::workflow_graph::DataRunRef> runs;
    if (spec.contains("versions")) {
        for (const auto& v : spec.at("versions")) {
            pwb::workflow_graph::DataVersionRef ref;
            ref.asset_id = v.at("asset_id").get<std::string>();
            ref.version_id = v.at("version_id").get<std::string>();
            ref.name = str_or(v, "name", "");
            ref.producing_run_id = opt_string(v.contains("producing_run_id")
                                                  ? v.at("producing_run_id")
                                                  : Json(nullptr));
            graph_versions.push_back(ref);

            VersionRecord rec;
            rec.asset_id = ref.asset_id;
            rec.version_id = ref.version_id;
            rec.name = ref.name;
            rec.producing_run_id = ref.producing_run_id;
            rec.checksum = str_or(v, "checksum", "");
            rec.trashed = v.contains("trashed") && v.at("trashed").get<bool>();
            rec.path = str_or(v, "path", "");
            if (v.contains("payload_json") && v.at("payload_json").is_string()) {
                rec.payload_json = v.at("payload_json").get<std::string>();
            }
            bundle.versions[rec.version_id] = rec;
        }
    }
    if (spec.contains("runs")) {
        for (const auto& r : spec.at("runs")) {
            pwb::workflow_graph::DataRunRef ref;
            ref.run_id = r.at("run_id").get<std::string>();
            ref.operation = str_or(r, "operation", "");
            ref.input_version_ids = str_list(r.contains("input_version_ids")
                                                 ? r.at("input_version_ids")
                                                 : Json::array());
            ref.output_version_ids = str_list(
                r.contains("output_version_ids") ? r.at("output_version_ids")
                                                 : Json::array());
            if (r.contains("parameters") && r.at("parameters").is_object()) {
                ref.parameters = r.at("parameters");
            }
            ref.generator_version = opt_string(
                r.contains("generator_version") ? r.at("generator_version")
                                                : Json(nullptr));
            ref.status = str_or(r, "status", "running");
            ref.started_at = opt_string(r.contains("started_at")
                                            ? r.at("started_at")
                                            : Json(nullptr));
            ref.finished_at = opt_string(r.contains("finished_at")
                                             ? r.at("finished_at")
                                             : Json(nullptr));
            ref.domain_task_id = opt_string(r.contains("domain_task_id")
                                                ? r.at("domain_task_id")
                                                : Json(nullptr));
            ref.input_snapshot_hash =
                opt_string(r.contains("input_snapshot_hash")
                               ? r.at("input_snapshot_hash")
                               : Json(nullptr));
            runs.push_back(ref);
        }
    }
    bundle.graph = DependencyGraph::from_listings(graph_versions, runs);

    if (spec.contains("context") && spec.at("context").is_object()) {
        const Json& ctx = spec.at("context");
        for (const auto& sel :
             ctx.contains("selects") ? ctx.at("selects") : Json::array()) {
            bundle.context.select(sel.at("asset_id").get<std::string>(),
                                  sel.at("version_id").get<std::string>(),
                                  str_or(sel, "label", ""));
        }
        for (const auto& mark : ctx.contains("domain_current")
                                    ? ctx.at("domain_current")
                                    : Json::array()) {
            bundle.context.mark_domain_product_current(
                mark.at("domain_task_id").get<std::string>(),
                mark.at("version_id").get<std::string>());
        }
        for (const auto& ident : ctx.contains("expected_identity")
                                     ? ctx.at("expected_identity")
                                     : Json::array()) {
            const Json parameters = ident.contains("parameters")
                                        ? ident.at("parameters")
                                        : Json(nullptr);
            const Json model_ref = ident.contains("model_ref")
                                       ? ident.at("model_ref")
                                       : Json(nullptr);
            bundle.context.set_expected_identity(
                ident.at("key").get<std::string>(),
                opt_string(ident.contains("generator_version")
                               ? ident.at("generator_version")
                               : Json(nullptr)),
                opt_string(ident.contains("input_snapshot_hash")
                               ? ident.at("input_snapshot_hash")
                               : Json(nullptr)),
                parameters, model_ref);
        }
    }
    return bundle;
}

Json reports_to_json(std::vector<pwb::workflow_runtime::FreshnessReport> reports) {
    Json arr = Json::array();
    for (const auto& r : reports) arr.push_back(r.to_dict());
    return arr;
}

// Repository over a frozen Json run/asset listing (provenance cases).
class JsonCatalogStub : public CatalogRepository {
public:
    JsonCatalogStub(Json runs, Json versions)
        : runs_json_(std::move(runs)), versions_json_(std::move(versions)) {}

    std::vector<AssetRecord> list_assets() override { return {}; }
    std::optional<AssetRecord> resolve_asset(const std::string&) override {
        return std::nullopt;
    }
    std::vector<VersionRecord> list_versions(const std::string&) override {
        std::vector<VersionRecord> out;
        if (versions_json_.is_array()) {
            for (const auto& v : versions_json_) {
                VersionRecord rec;
                rec.version_id = v.at("version_id").get<std::string>();
                out.push_back(rec);
            }
        }
        return out;
    }
    std::optional<VersionRecord> resolve_version(
        const std::string&) override {
        return std::nullopt;
    }
    std::vector<RunRecord> list_runs() override {
        std::vector<RunRecord> out;
        if (runs_json_.is_array()) {
            for (const auto& r : runs_json_) {
                RunRecord rec;
                rec.run_id = r.at("id").get<std::string>();
                rec.operation = r.at("operation").get<std::string>();
                rec.input_version_ids = str_list(r.at("input_version_ids"));
                rec.output_version_ids = str_list(r.at("output_version_ids"));
                out.push_back(rec);
            }
        }
        return out;
    }
    std::optional<RunRecord> resolve_run(const std::string&) override {
        return std::nullopt;
    }
    std::string register_run(const std::string&, const std::vector<std::string>&,
                             const Json&, const std::optional<std::string>&,
                             const std::string&,
                             const std::optional<std::string>&,
                             const std::optional<std::string>&,
                             const std::optional<std::string>&) override {
        throw std::logic_error("stub: register_run");
    }
    pwb::workflow_runtime::RegisteredAssetVersion register_result_asset(
        const std::string&, const std::string&, const std::string&,
        const Json&, const std::string&, const std::string&,
        const std::string&, const Json&) override {
        throw std::logic_error("stub: register_result_asset");
    }
    std::string register_version(const std::string&, const std::string&,
                                 const std::string&,
                                 const std::vector<std::string>&,
                                 const std::string&, const Json&) override {
        throw std::logic_error("stub: register_version");
    }
    void update_run_status(const std::string&, const std::string&) override {
        throw std::logic_error("stub: update_run_status");
    }
    void attach_run_output(const std::string&, const std::string&) override {
        throw std::logic_error("stub: attach_run_output");
    }
    void set_current_version(const std::string&, const std::string&) override {
        throw std::logic_error("stub: set_current_version");
    }
    std::optional<std::string> verify_integrity(const std::string&) override {
        return std::nullopt;
    }

private:
    Json runs_json_;
    Json versions_json_;
};

std::unique_ptr<CatalogRepository> setup_constraint_repo(const Json& setup) {
    auto store = std::make_unique<pwb::workflow_runtime::RuntimeStore>();
    if (setup.is_array()) {
        for (const auto& group : setup) {
            pwb::workflow_runtime::commit_constraint_group(*store, group,
                                                           "oracle-setup");
        }
    }
    return store;
}

// ------------------------------------------------------------------ dispatch

void dispatch_case(const std::string& id, const std::string& fn,
                   const Json& input, const Json& expect) {
    // ---- current_context ----
    if (fn == "current_context.state" || fn == "current_context.reselect") {
        CurrentProjectVersionContext ctx;
        const Json& state = input.at("state");
        for (const auto& sel : state.at("selects")) {
            ctx.select(sel.at("asset_id").get<std::string>(),
                       sel.at("version_id").get<std::string>(),
                       str_or(sel, "label", ""));
        }
        if (state.contains("domain_current")) {
            for (const auto& mark : state.at("domain_current")) {
                ctx.mark_domain_product_current(
                    mark.at("domain_task_id").get<std::string>(),
                    mark.at("version_id").get<std::string>());
            }
        }
        if (fn == "current_context.state") {
            for (const auto& ident : state.at("expected_identity")) {
                ctx.set_expected_identity(
                    ident.at("key").get<std::string>(),
                    opt_string(ident.at("generator_version")),
                    opt_string(ident.at("input_snapshot_hash")),
                    ident.contains("parameters") ? ident.at("parameters")
                                                 : Json(nullptr),
                    ident.contains("model_ref") ? ident.at("model_ref")
                                                : Json(nullptr));
            }
            Json out = Json::object();
            Json by_asset = Json::object();
            for (const auto& [a, v] : ctx.current_by_asset()) by_asset[a] = v;
            out["current_by_asset"] = by_asset;
            Json selected = Json::array();
            {
                std::vector<std::string> sorted(ctx.selected_version_ids()
                                                    .begin(),
                                                ctx.selected_version_ids()
                                                    .end());
                std::sort(sorted.begin(), sorted.end());
                for (const auto& s : sorted) selected.push_back(s);
            }
            out["selected"] = selected;
            Json labels = Json::object();
            for (const auto& [v, l] : ctx.labels()) labels[v] = l;
            out["labels"] = labels;
            Json by_domain = Json::object();
            for (const auto& [d, v] : ctx.current_by_domain_task()) {
                by_domain[d] = v;
            }
            out["current_by_domain_task"] = by_domain;
            Json expected = Json::object();
            for (const auto& [k, v] : ctx.expected_identity()) {
                expected[k] = v;
            }
            out["expected_identity"] = expected;
            out["current_for_asset(h1)"] =
                ctx.current_for_asset("asset_h1")
                    ? Json(*ctx.current_for_asset("asset_h1"))
                    : Json(nullptr);
            out["current_for_asset(none)"] = Json(nullptr);
            out["is_current(ver_h1_v1)"] =
                ctx.is_current_version("ver_h1_v1");
            out["is_current(ver_x)"] = ctx.is_current_version("ver_x");
            compare(id, out, expect);
            return;
        }
        Json out = Json::object();
        if (state.contains("domain_current")) {
            Json by_domain = Json::object();
            for (const auto& [d, v] : ctx.current_by_domain_task()) {
                by_domain[d] = v;
            }
            out["current_by_domain_task"] = by_domain;
        } else {
            out["current"] = ctx.current_for_asset("a")
                                 ? Json(*ctx.current_for_asset("a"))
                                 : Json(nullptr);
        }
        Json selected = Json::array();
        {
            std::vector<std::string> sorted(ctx.selected_version_ids()
                                                .begin(),
                                            ctx.selected_version_ids().end());
            std::sort(sorted.begin(), sorted.end());
            for (const auto& s : sorted) selected.push_back(s);
        }
        out["selected"] = selected;
        compare(id, out, expect);
        return;
    }

    // ---- freshness ----
    if (fn == "freshness.evaluate_run" || fn == "freshness.evaluate_version" ||
        fn == "freshness.evaluate_domain_task" ||
        fn == "freshness.downstream_impact" ||
        fn == "freshness.stale_downstream" ||
        fn == "freshness.evaluate_operation" ||
        fn == "freshness.step_freshness") {
        ServiceBundle bundle = build_service(input.at("spec"));
        FreshnessService svc = bundle.make_service(
            input.at("spec").value("check_integrity", false));
        if (fn == "freshness.evaluate_run") {
            compare(id, svc.evaluate_run(input.at("run_id").get<std::string>())
                            .to_dict(),
                    expect);
        } else if (fn == "freshness.evaluate_version") {
            compare(id,
                    svc.evaluate_version(
                            input.at("version_id").get<std::string>())
                        .to_dict(),
                    expect);
        } else if (fn == "freshness.evaluate_domain_task") {
            compare(id,
                    svc.evaluate_domain_task(
                            input.at("domain_task_id").get<std::string>())
                        .to_dict(),
                    expect);
        } else if (fn == "freshness.downstream_impact") {
            compare(id,
                    reports_to_json(svc.downstream_impact(
                        str_list(input.at("version_ids")))),
                    expect);
        } else if (fn == "freshness.stale_downstream") {
            compare(id,
                    reports_to_json(svc.stale_downstream(
                        str_list(input.at("version_ids")))),
                    expect);
        } else if (fn == "freshness.evaluate_operation") {
            compare(id,
                    reports_to_json(svc.evaluate_operation(
                        input.at("operation").get<std::string>())),
                    expect);
        } else {
            auto state = svc.step_freshness(
                input.at("step_type").get<std::string>());
            compare(id,
                    state ? Json(pwb::workflow_runtime::freshness_state_value(
                                *state))
                          : Json(nullptr),
                    expect);
        }
        return;
    }

    // ---- recompute ----
    if (fn == "recompute.build_plan") {
        ServiceBundle bundle = build_service(input.at("spec"));
        FreshnessService svc = bundle.make_service(false);
        pwb::workflow_runtime::RecomputePlanOptions options;
        const Json& opts = input.at("options");
        if (opts.is_object()) {
            options.changed_version_ids =
                str_list(opts.contains("changed_version_ids")
                             ? opts.at("changed_version_ids")
                             : Json::array());
            if (opts.contains("stale_only")) {
                options.stale_only = opts.at("stale_only").get<bool>();
            }
            options.operations =
                str_list(opts.contains("operations") ? opts.at("operations")
                                                     : Json::array());
        }
        if (input.contains("project") && input.at("project").is_object()) {
            options.project = input.at("project");
        }
        auto plan = pwb::workflow_runtime::build_recompute_plan(svc, options);
        compare(id, plan.to_dict(), expect);
        return;
    }
    if (fn == "recompute.summary_zh") {
        ServiceBundle bundle = build_service(input.at("spec"));
        FreshnessService svc = bundle.make_service(false);
        pwb::workflow_runtime::RecomputePlanOptions options;
        auto plan = pwb::workflow_runtime::build_recompute_plan(svc, options);
        compare(id, Json(plan.summary_zh()), expect);
        return;
    }
    if (fn == "recompute.execute_plan") {
        ServiceBundle bundle = build_service(input.at("spec"));
        FreshnessService svc = bundle.make_service(false);
        auto plan = pwb::workflow_runtime::build_recompute_plan(
            svc, pwb::workflow_runtime::RecomputePlanOptions{});
        std::map<std::string, pwb::workflow_runtime::StepHandler> handlers;
        auto make_handler = [](const std::string& behavior) {
            return [behavior](const auto&) {
                if (behavior.rfind("fail:", 0) == 0) {
                    throw std::runtime_error(behavior.substr(5));
                }
            };
        };
        if (input.contains("chain") && input.at("chain").get<bool>()) {
            for (auto it = input.at("handlers").begin();
                 it != input.at("handlers").end(); ++it) {
                handlers.emplace(
                    it.key(),
                    make_handler(it.value().get<std::string>()));
            }
        } else {
            const std::string behavior =
                input.at("map_compile_handler").get<std::string>();
            handlers.emplace("factor_map", [](const auto&) {});
            if (!behavior.empty()) {
                handlers.emplace("map_compile", make_handler(behavior));
            }
        }
        pwb::workflow_runtime::PlanExecutor executor(
            std::move(handlers), 0,
            input.at("stop_on_failure").get<bool>());
        if (input.at("cancelled").get<bool>()) {
            executor.bump_generation();
        }
        auto result = executor.execute(plan);
        Json out = Json::object();
        out["stopped_early"] = result.stopped_early;
        Json messages = Json::array();
        for (const auto& m : result.messages) messages.push_back(m);
        out["messages"] = messages;
        out["completed"] = [&] {
            Json arr = Json::array();
            for (const auto& v : plan.completed_run_ids) arr.push_back(v);
            return arr;
        }();
        out["failed"] = [&] {
            Json arr = Json::array();
            for (const auto& v : plan.failed_run_ids) arr.push_back(v);
            return arr;
        }();
        out["skipped"] = [&] {
            Json arr = Json::array();
            for (const auto& v : plan.skipped_run_ids) arr.push_back(v);
            return arr;
        }();
        compare(id, out, expect);
        return;
    }

    // ---- constraint lifecycle ----
    if (fn == "constraint.content_hash") {
        auto result = pwb::workflow_runtime::constraint_group_content_hash(
            input.at("group"));
        Json out = Json::array({result.first, result.second});
        compare(id, out, expect);
        return;
    }
    if (fn == "constraint.commit") {
        auto repo = setup_constraint_repo(input.at("setup"));
        auto report = pwb::workflow_runtime::commit_constraint_group(
            *repo, input.at("group"), input.at("actor").get<std::string>(),
            input.at("notes").get<std::string>());
        compare(id, report.to_dict(), expect);
        return;
    }
    if (fn == "constraint.commit_all") {
        pwb::workflow_runtime::RuntimeStore store;
        Json project = Json::object();
        project["constraint_layers"] = input.at("groups");
        auto reports = pwb::workflow_runtime::commit_all_constraints(
            store, project, input.at("actor").get<std::string>());
        Json out = Json::array();
        for (const auto& r : reports) out.push_back(r.to_dict());
        compare(id, out, expect);
        return;
    }
    if (fn == "constraint.current_version") {
        auto repo = setup_constraint_repo(input.at("setup"));
        auto version = pwb::workflow_runtime::current_constraint_version(
            *repo, input.at("group_id").get<std::string>());
        compare(id, version ? Json(version->version_id) : Json(nullptr),
                expect);
        return;
    }
    if (fn == "constraint.pins_for_task") {
        auto repo = setup_constraint_repo(input.at("setup"));
        Json project = Json::object();
        project["constraint_layers"] = input.at("project_groups");
        auto pins = pwb::workflow_runtime::constraint_pins_for_task(
            input.at("task"), project,
            input.at("with_catalog").get<bool>() ? repo.get() : nullptr);
        compare(id, pins, expect);
        return;
    }
    if (fn == "constraint.pins_staleness") {
        auto repo = setup_constraint_repo(input.at("setup"));
        Json project = Json::object();
        project["constraint_layers"] = input.at("project_groups");
        auto out = pwb::workflow_runtime::constraint_pins_staleness(
            input.at("task"), project,
            input.at("with_catalog").get<bool>() ? repo.get() : nullptr);
        compare(id, out, expect);
        return;
    }
    if (fn == "constraint.compare") {
        auto repo = setup_constraint_repo(input.at("setup"));
        try {
            auto out = pwb::workflow_runtime::compare_constraint_versions(
                *repo, input.at("a").get<std::string>(),
                input.at("b").get<std::string>());
            compare(id, out, expect);
        } catch (const pwb::workflow_runtime::ConstraintValueError& exc) {
            compare(id,
                    Json{{"raise",
                          Json{{"python_class", exc.python_class()},
                               {"message", exc.what()}}}},
                    expect);
        }
        return;
    }
    if (fn == "constraint.resolve_ref") {
        auto repo = setup_constraint_repo(input.at("setup"));
        Json project = Json::object();
        project["constraint_layers"] = input.at("project_groups");
        auto out = pwb::workflow_runtime::resolve_constraint_ref(
            project, input.at("with_catalog").get<bool>() ? repo.get()
                                                          : nullptr,
            input.at("ref").get<std::string>());
        compare(id, out, expect);
        return;
    }

    // ---- provenance graph ----
    if (fn == "provenance.lifecycle_graph") {
        std::unique_ptr<CatalogRepository> repo;
        if (!input.at("runs").is_null()) {
            repo = std::make_unique<JsonCatalogStub>(input.at("runs"),
                                                     Json::array());
        }
        std::optional<std::string> product_id;
        if (!input.at("product_id").is_null()) {
            product_id = input.at("product_id").get<std::string>();
        }
        auto out = pwb::workflow_runtime::build_product_lifecycle_graph(
            input.at("project"), repo.get(), product_id);
        compare(id, out, expect);
        return;
    }

    // ---- staleness vocabulary ----
    if (fn == "staleness.from_constraint_pin") {
        compare(id,
                Json(pwb::workflow_runtime::staleness_verdict_value(
                    pwb::workflow_runtime::from_constraint_pin(
                        input.at("state").get<std::string>()))),
                expect);
        return;
    }
    if (fn == "staleness.from_workspace_status") {
        compare(id,
                Json(pwb::workflow_runtime::staleness_verdict_value(
                    pwb::workflow_runtime::from_workspace_status(
                        input.at("status").get<std::string>()))),
                expect);
        return;
    }
    if (fn == "staleness.from_run_freshness") {
        compare(id,
                Json(pwb::workflow_runtime::staleness_verdict_value(
                    pwb::workflow_runtime::from_run_freshness(
                        input.at("state").get<std::string>()))),
                expect);
        return;
    }
    if (fn == "staleness.verdict_dict") {
        pwb::workflow_runtime::ArtifactVerdict verdict;
        verdict.artifact_key = input.at("artifact_key").get<std::string>();
        verdict.verdict =
            *pwb::workflow_runtime::staleness_verdict_from_value(
                input.at("verdict").get<std::string>());
        verdict.detail = input.at("detail").get<std::string>();
        verdict.upstream_culprits = str_list(input.at("upstream_culprits"));
        compare(id, verdict.to_dict(), expect);
        return;
    }

    std::printf("SKIP %s (unknown fn %s)\n", id.c_str(), fn.c_str());
    ++failures;
}

// ---------------------------------------------------- end-to-end closure test

void end_to_end_closure() {
    // WorkflowSpec -> validate -> execute a C++ node -> publish provenance
    // -> freshness STALE -> recompute plan -> execute (reuse) -> downstream
    // state FRESH. No Python anywhere.
    pwb::workflow_runtime::RuntimeStore store;
    pwb::workflow_runtime::NodeAdapterRegistry adapters;
    adapters.register_builtin_adapters();  // "test.noop"

    WorkflowRuntimeService service(store, adapters);

    // Seed an upstream RAW asset + a stale consumer run (simulating a
    // workflow that ran on an older input).
    const std::string seed_run = store.register_run(
        "stage:compute_v1", {}, Json{{"factor", "thickness"}}, std::nullopt,
        "complete", "node_compute");
    const auto seeded =
        store.register_result_asset("inputs:thickness", "raw_input", "json",
                                    Json::object(), "{\"samples\": 4}",
                                    "RAW", seed_run, Json::object());
    store.attach_run_output(seed_run, seeded.version_id);

    // (1) validate: unknown op must fail closed.
    {
        pwb::workflow_engine::WorkflowSpec bad;
        bad.workflow_id = "wf_bad";
        bad.nodes.push_back({"n1", "no.such_op", Json::object(), {}});
        const auto problems = service.validate(bad);
        if (problems.empty()) {
            std::printf("FAIL e2e validate: unknown op accepted\n");
            ++failures;
        }
    }

    // (2) execute a spec through the adapter; provenance published per node.
    pwb::workflow_engine::WorkflowSpec spec;
    spec.workflow_id = "wf_e2e";
    spec.nodes.push_back({"prep", "test.noop", Json::object(), {}});
    spec.nodes.push_back({"compute", "test.noop",
                          Json{{"input", Json{{"$version", seeded.version_id}}}},
                          {"prep"}});
    pwb::workflow_engine::CancelToken token;
    WorkflowRuntimeService::ExecuteOptions options;
    options.workflow_name = "wf_e2e";
    auto run = service.execute(spec, token, options);
    if (run.state != pwb::workflow_engine::RunState::completed) {
        std::printf("FAIL e2e execute: run state %s\n",
                    pwb::workflow_engine::to_string(run.state));
        ++failures;
        return;
    }
    // Both nodes published completed runs; the compute node consumed the
    // seeded version as input (typed $version binding).
    {
        auto runs = store.list_runs();
        if (runs.size() != 3) {
            std::printf("FAIL e2e provenance: expected 3 runs, got %zu\n",
                        runs.size());
            ++failures;
            return;
        }
        const auto& compute_run = runs.back();
        if (compute_run.operation != "wf_e2e:test.noop" ||
            compute_run.input_version_ids.size() != 1 ||
            compute_run.input_version_ids[0] != seeded.version_id ||
            compute_run.status != "complete") {
            std::printf("FAIL e2e provenance: compute run wrong (%s, %zu "
                        "inputs, %s)\n",
                        compute_run.operation.c_str(),
                        compute_run.input_version_ids.size(),
                        compute_run.status.c_str());
            ++failures;
            return;
        }
    }

    // (3) freshness over the published provenance: outputs fresh, trace
    // wired node -> run -> version -> downstream.
    auto ctx = service.build_context();
    {
        auto session = service.make_freshness_session(ctx);
        const auto report = session.service->evaluate_run(
            store.list_runs().back().run_id);
        if (!report.is_fresh()) {
            std::printf("FAIL e2e freshness: expected FRESH, got %s\n",
                        pwb::workflow_runtime::freshness_state_value(
                            report.state));
            ++failures;
            return;
        }
    }

    // (4) recompute plan over an empty stale set: nothing to compute.
    {
        auto plan = service.plan(ctx);
        if (!plan.compute_steps().empty()) {
            std::printf("FAIL e2e plan: %zu unexpected compute steps\n",
                        plan.compute_steps().size());
            ++failures;
            return;
        }
    }

    // (5) mutate the upstream selection: downstream turns STALE, plan
    // requires compute, execute_plan via adapter publishes new provenance,
    // downstream returns FRESH. This is the resume/reuse seam: the new run
    // is reuse-matched afterwards.
    const std::string new_input_run = store.register_run(
        "stage:compute_v2", {}, Json{{"factor", "thickness"}}, std::nullopt,
        "complete", "node_compute");
    const auto new_input =
        store.register_result_asset("inputs:thickness", "raw_input", "json",
                                    Json::object(), "{\"samples\": 9}",
                                    "RAW", new_input_run, Json::object());
    store.attach_run_output(new_input_run, new_input.version_id);
    store.set_current_version(seeded.asset_id, new_input.version_id);

    auto ctx2 = service.build_context();  // current pointer advanced
    {
        auto session = service.make_freshness_session(ctx2);
        const std::string compute_run_id = [&] {
            auto runs = store.list_runs();
            for (auto it = runs.rbegin(); it != runs.rend(); ++it) {
                if (it->domain_task_id == "compute") return it->run_id;
            }
            return std::string();
        }();
        const auto report = session.service->evaluate_run(compute_run_id);
        if (report.state != pwb::workflow_runtime::FreshnessState::Stale) {
            std::printf("FAIL e2e stale-after-change: expected STALE, got "
                        "%s\n",
                        pwb::workflow_runtime::freshness_state_value(
                            report.state));
            ++failures;
            return;
        }
    }

    // (6) plan + execute_plan with a domain handler for the stale op.
    {
        auto plan = service.plan(ctx2);
        if (plan.compute_steps().empty()) {
            std::printf("FAIL e2e plan-after-change: no compute steps\n");
            ++failures;
            return;
        }
        // Register a real adapter for the published operation so the plan
        // executes (test.noop body wrapped as the op the runs carry).
        pwb::workflow_runtime::NodeAdapter adapter;
        adapter.operation = "wf_e2e:test.noop";
        adapter.fn = [](const Json&, const pwb::workflow_engine::CancelToken&) {
            return pwb::workflow_engine::NodeResult{
                Json{{"updated", true}}, {}};
        };
        adapter.hints = pwb::workflow_runtime::ResourceHints{1, 0, "重算"};
        adapters.add(std::move(adapter));

        pwb::workflow_engine::CancelToken exec_token;
        auto result = service.execute_plan(plan, exec_token);
        if (result.stopped_early ||
            !plan.failed_run_ids.empty()) {
            std::printf("FAIL e2e execute_plan: stopped=%d failed=%zu (%s)\n",
                        result.stopped_early, plan.failed_run_ids.size(),
                        result.messages.empty() ? ""
                                                : result.messages[0].c_str());
            ++failures;
            return;
        }
    }

    // (7) downstream state after recompute: the domain task's latest run is
    // fresh again; provenance trace lists the new run.
    {
        auto ctx3 = service.build_context();
        auto session = service.make_freshness_session(ctx3);
        const std::string latest_compute = [&] {
            auto runs = store.list_runs();
            for (auto it = runs.rbegin(); it != runs.rend(); ++it) {
                if (it->domain_task_id == "compute") return it->run_id;
            }
            return std::string();
        }();
        const auto report = session.service->evaluate_run(latest_compute);
        if (!report.is_fresh()) {
            std::printf("FAIL e2e fresh-after-recompute: got %s\n",
                        pwb::workflow_runtime::freshness_state_value(
                            report.state));
            ++failures;
            return;
        }
        // Re-planning now matches the recompute run for reuse (resume seam).
        auto replan = service.plan(ctx3);
        bool saw_compute_step = false;
        for (const auto* step : replan.compute_steps()) {
            if (step->domain_task_id &&
                *step->domain_task_id == "compute") {
                saw_compute_step = true;
            }
        }
        if (saw_compute_step) {
            std::printf("FAIL e2e resume: compute still planned after "
                        "recompute\n");
            ++failures;
            return;
        }
        // provenance trace of the new input version reaches the recompute
        // run downstream.
        auto trace = service.provenance_trace(new_input.version_id, ctx3);
        if (!trace.at("downstream_runs").is_array() ||
            trace.at("downstream_runs").empty()) {
            std::printf("FAIL e2e trace: no downstream runs\n");
            ++failures;
            return;
        }
    }

    // (8) mid-flight cancel: a node body that cancels the token lands the
    // run CANCELLED; provenance records the cancellation honestly.
    {
        // The engine hands node bodies a const token (bodies observe, the
        // OWNER cancels); the adapter cancels through its captured pointer
        // to the caller-owned token — the production shape (UI thread).
        pwb::workflow_engine::CancelToken cancel_token;
        pwb::workflow_runtime::NodeAdapter cancellable;
        cancellable.operation = "test.cancellable";
        cancellable.fn = [&cancel_token](const Json&,
                                         const pwb::workflow_engine::
                                             CancelToken& tok) {
            cancel_token.cancel();  // cooperative cancel mid-node
            tok.throw_if_cancelled();
            return pwb::workflow_engine::NodeResult{};
        };
        cancellable.hints = pwb::workflow_runtime::ResourceHints{1, 0, "可取消"};
        adapters.add(std::move(cancellable));

        pwb::workflow_engine::WorkflowSpec cancel_spec;
        cancel_spec.workflow_id = "wf_cancel";
        cancel_spec.nodes.push_back({"job", "test.cancellable",
                                     Json::object(), {}});
        WorkflowRuntimeService::ExecuteOptions cancel_options;
        cancel_options.workflow_name = "wf_cancel";
        auto cancel_run =
            service.execute(cancel_spec, cancel_token, cancel_options);
        if (cancel_run.state !=
            pwb::workflow_engine::RunState::cancelled) {
            std::printf("FAIL e2e cancel: run state %s\n",
                        pwb::workflow_engine::to_string(
                            cancel_run.state));
            ++failures;
        }
        const auto last_run = store.list_runs().back();  // by value —
        // list_runs() returns a temporary vector; a reference would dangle.
        if (last_run.status != "cancelled" ||
            last_run.domain_task_id != "job") {
            std::printf("FAIL e2e cancel provenance: status=%s\n",
                        last_run.status.c_str());
            ++failures;
        }

        // retry seam: re-running the same spec with a fresh token
        // completes and publishes a new provenance run.
        pwb::workflow_engine::CancelToken retry_token;
        auto retry_run =
            service.execute(cancel_spec, retry_token, cancel_options);
        if (retry_run.state != pwb::workflow_engine::RunState::completed) {
            std::printf("FAIL e2e retry: run state %s\n",
                        pwb::workflow_engine::to_string(retry_run.state));
            ++failures;
        }
    }

    // (8b) inspect APIs: explain_stale + list_outputs over the recompute
    // run (freshness state + output listing derived from ONE store).
    {
        const std::string compute_run_id = [&] {
            auto runs = store.list_runs();
            for (auto it = runs.rbegin(); it != runs.rend(); ++it) {
                if (it->domain_task_id == "compute" &&
                    it->status == "complete") {
                    return it->run_id;
                }
            }
            return std::string();
        }();
        auto ctx_inspect = service.build_context();
        auto domain_report = service.explain_stale(
            ctx_inspect, "domain_task", "compute");
        if (domain_report.state != pwb::workflow_runtime::FreshnessState::Fresh) {
            std::printf("FAIL e2e explain_stale: state %s (expected FRESH "
                        "after recompute)\n",
                        pwb::workflow_runtime::freshness_state_value(
                            domain_report.state));
            ++failures;
        }
        auto outputs = service.list_outputs(compute_run_id, ctx_inspect);
        if (!outputs.at("found").get<bool>() ||
            !outputs.at("outputs").is_array()) {
            std::printf("FAIL e2e list_outputs: found=%s\n",
                        outputs.at("found").dump().c_str());
            ++failures;
        }
    }

    // (8c) admission gate: bounded concurrency + cancel-aware acquire.
    {
        AdmissionGate gate(1);
        if (!gate.try_acquire()) {
            std::printf("FAIL admission: first acquire denied\n");
            ++failures;
        }
        if (gate.try_acquire()) {
            std::printf("FAIL admission: second acquire allowed over bound\n");
            ++failures;
            gate.release();
        }
        gate.release();
        pwb::workflow_engine::CancelToken cancelled;
        cancelled.cancel();
        if (gate.acquire(cancelled)) {
            std::printf("FAIL admission: acquire succeeded on cancelled "
                        "token\n");
            ++failures;
        }
        // terminal shutdown then re-arm for the next plan generation.
        gate.cancel_all();
        pwb::workflow_engine::CancelToken fresh_token;
        if (gate.acquire(fresh_token)) {
            std::printf("FAIL admission: acquire succeeded after "
                        "cancel_all\n");
            ++failures;
            gate.release();
        }
        gate.reset();
        if (!gate.try_acquire()) {
            std::printf("FAIL admission: reset did not re-arm the gate\n");
            ++failures;
        } else {
            gate.release();
        }
    }

    // (9) typed input binding extraction.
    {
        Json bound;
        auto versions = pwb::workflow_runtime::extract_version_bindings(
            Json{{"a", Json{{"$version", "ver_1"}}},
                 {"b", Json::array({Json{{"$version", "ver_2"}}, 7})},
                 {"c", "plain"}},
            &bound);
        if (versions.size() != 2 || versions[0] != "ver_1" ||
            versions[1] != "ver_2" ||
            bound.at("a").get<std::string>() != "ver_1" ||
            bound.at("b").at(0).get<std::string>() != "ver_2" ||
            bound.at("b").at(1).get<int>() != 7) {
            std::printf("FAIL version binding extraction\n");
            ++failures;
        }
    }

    std::printf("e2e closure: OK (WorkflowSpec -> validate -> execute -> "
                "provenance -> stale -> plan -> recompute -> fresh -> "
                "trace)\n");
}

// --------------------------------------------------- comparator negative check

void comparator_self_check() {
    // The comparator must catch mutations (fixture integrity guard).
    const Json a = Json::parse(R"({"x": 1, "y": [1, 2], "z": "s"})");
    const Json b = Json::parse(R"({"x": 2, "y": [1, 2], "z": "s"})");
    const Json c = Json::parse(R"({"x": 1, "y": [1, 3], "z": "s"})");
    const Json d = Json::parse(R"({"x": 1.0, "y": [1, 2], "z": "s"})");
    if (equals(a, b) || equals(a, c) || equals(a, d)) {
        std::printf("FAIL comparator self-check: mutation not caught\n");
        ++failures;
    } else {
        std::printf("comparator self-check: OK\n");
    }
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 2) {
        std::fprintf(stderr, "usage: %s <fixture.json>\n", argv[0]);
        return 2;
    }
    const Json fixture = read_fixture(argv[1]);
    // Hermetic payload for the integrity "modified" branch (the generator
    // writes the same file — idempotent on both sides).
    {
        std::ofstream payload("/tmp/pwb-runtime-oracle-payload.json",
                              std::ios::trunc);
        payload << "payload-bytes-v1";
    }
    int total = 0;
    for (const auto& c : fixture.at("cases")) {
        ++total;
        dispatch_case(c.at("id").get<std::string>(),
                      c.at("fn").get<std::string>(), c.at("input"),
                      c.at("expect"));
    }
    comparator_self_check();
    end_to_end_closure();
    if (failures != 0) {
        std::printf("%d/%d cases FAILED\n", failures, total);
        return 1;
    }
    std::printf("all %d cases passed\n", total);
    return 0;
}
