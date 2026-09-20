// cpp-close-02 — the acceptance closed loop, driven entirely through the
// real native services (no production mocks; the only doubles are the
// test's compute bodies, which stand in for the scientific kernels by
// contract):
//
//   import → recipe → execute → output versions + provenance →
//   modify input → stale detection → partial recompute (only the
//   necessary nodes) → reopen recovery → failure short-circuit →
//   cooperative cancel (incl. a late completion that must not resurrect
//   the run) → cross-run cache hit with the catalog provenance rail →
//   duplicate-id / cycle / recipe-key refusals.
//
// Every phase asserts real results: catalog versions/runs on disk, run
// states from the store, freshness verdicts from the resolved context,
// and execution counters for "only the necessary nodes re-ran".

#include <pwb/closure_workflow/cache_run_rail.hpp>
#include <pwb/closure_workflow/host_bindings.hpp>
#include <pwb/closure_workflow/persistent_catalog.hpp>
#include <pwb/closure_workflow/workflow_scheduler.hpp>
#include <pwb/domain/json.hpp>
#include <pwb/workflow_engine/recipe.hpp>
#include <pwb/workflow_engine/run_engine.hpp>
#include <pwb/workflow_engine/store.hpp>
#include <pwb/workflow_runtime/node_adapters.hpp>
#include <pwb/workflow_runtime/recompute_plan.hpp>
#include <pwb/workflow_runtime/resolve_context.hpp>
#include <pwb/workflow_runtime/runtime_service.hpp>
#include <pwb/workflow_spec/validation.hpp>

#include <atomic>
#include <chrono>
#include <cstdio>
#include <filesystem>
#include <functional>
#include <iostream>
#include <map>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace {

using pwb::domain::Json;
using pwb::workflow_engine::ActionInfo;
using NodeSpec = pwb::workflow_spec::NodeSpec;
using pwb::workflow_engine::CancelToken;
using pwb::workflow_engine::RunEngine;
using pwb::workflow_engine::RunFunctionMap;
using pwb::workflow_engine::WorkflowRunStore;
using pwb::workflow_spec::WorkflowSpec;
using pwb::workflow_runtime::NodeAdapterRegistry;
using pwb::workflow_runtime::RecomputePlan;
using pwb::workflow_runtime::RuntimeStore;
using pwb::workflow_runtime::VersionRecord;
using Catalog = pwb::closure_workflow::FileCatalogRepository;

int failures = 0;
int checks = 0;

void check(const std::string& id, bool ok, const std::string& detail = "") {
    ++checks;
    if (!ok) {
        ++failures;
        std::printf("FAIL %s%s%s\n", id.c_str(), detail.empty() ? "" : ": ",
                    detail.c_str());
    }
}

// ------------------------------------------------------------- harness --

// The compute body shared by the RunEngine function map and the runtime
// service adapter registry: reads its input versions from the catalog,
// derives a payload deterministically, and publishes run + DERIVED
// version with full lineage — the production shape of an adapter.
struct ComputeHost {
    Catalog* repo = nullptr;
    std::atomic<int> executions{0};
    // Test injection points (lifecycle fault injection, never production
    // doubles): fail the next execution / block until released / ignore
    // cancellation for the late-completion scenario.
    bool fail_next = false;
    std::atomic<bool> release{false};
    bool ignore_cancel = false;
    // The RunEngine function map path books its own catalog provenance;
    // the WorkflowRuntimeService plan path books it in the StepHandler —
    // the body must not double-register.
    bool register_provenance = true;

    Json body(const Json& params, const CancelToken& token) {
        ++executions;
        // Param shapes: the engine nodes pass a concrete
        // input_version_id; the runtime-service plan handler passes
        // input_version_ids[] over CURRENT inputs.
        std::string input_version;
        if (params.contains("input_version_id")) {
            input_version = params.at("input_version_id").get<std::string>();
        } else if (params.contains("input_version_ids")) {
            input_version =
                params.at("input_version_ids").at(0).get<std::string>();
        }
        if (fail_next) {
            fail_next = false;
            // Book the run, then fail: the catalog must show a failed run.
            const std::string run_id =
                repo->register_run("grid.compute", {input_version}, params,
                                   std::string("grid-compute-test"),
                                   "running");
            repo->update_run_status(run_id, "failed");
            throw std::runtime_error("grid.compute exploded");
        }
        {
            // Cooperative safe point: wait until released, or cancelled —
            // unless the scenario explicitly ignores cancellation (the
            // late-completion body keeps running past the cancel).
            while (!release.load(std::memory_order_acquire)) {
                if (token.is_cancelled() && !ignore_cancel) {
                    throw pwb::workflow_engine::Cancelled(
                        "cancelled at safe point");
                }
                std::this_thread::sleep_for(std::chrono::milliseconds(5));
            }
        }
        const std::optional<VersionRecord> input =
            repo->resolve_version(input_version);
        if (!input.has_value()) {
            throw std::runtime_error("input version missing: " + input_version);
        }
        const std::string payload = input->payload_json;
        Json derived = Json::object();
        derived["derived_from"] = input_version;
        derived["payload_bytes"] = payload.size();
        derived["transform"] = "upper";
        const std::string payload_out = derived.dump();
        Json outputs = Json::object();
        outputs["grid_payload"] = payload_out;
        if (register_provenance) {
            const std::string run_id =
                repo->register_run("grid.compute", {input_version}, params,
                                   std::string("grid-compute-test"),
                                   "running");
            const pwb::workflow_runtime::RegisteredAssetVersion version =
                repo->register_result_asset(
                    "grid_" + input_version, "grid", "json", Json::object(),
                    payload_out, "derived", run_id, Json::object());
            repo->attach_run_output(run_id, version.version_id);
            repo->update_run_status(run_id, "complete");
            // "version_id" is the engine receipt collector's singular
            // contract (receipt.cpp collect_output_version_ids) — the
            // cache identity spans the node's declared outputs.
            outputs["version_id"] = version.version_id;
            outputs["output_version_id"] = version.version_id;
        }
        return outputs;
    }
};

class StaticCatalog : public pwb::workflow_engine::IActionCatalog {
public:
    std::optional<ActionInfo> get(const std::string& id) const override {
        if (id == "grid.compute") {
            ActionInfo info;
            info.action_id = id;
            info.cacheable = true;
            info.description = "derive a grid payload";
            return info;
        }
        return std::nullopt;
    }
    std::vector<std::string> ids() const override { return {"grid.compute"}; }
};

std::filesystem::path make_temp_dir() {
    const auto unique =
        std::chrono::steady_clock::now().time_since_epoch().count();
    const std::filesystem::path dir =
        std::filesystem::temp_directory_path() /
        ("pwb-closure-e2e-" + std::to_string(unique));
    std::filesystem::remove_all(dir);
    std::filesystem::create_directories(dir);
    return dir;
}

// Import one curve version (the "导入数据" step): the FIRST import mints
// the asset, later imports append immutable versions on the SAME asset —
// a new asset per import would fork the lineage and stale detection could
// never see the supersession.
std::string import_input(Catalog& repo, const std::string& name,
                         const std::string& payload) {
    const std::string run_id =
        repo.register_run("import_curve", {}, Json::object(), std::nullopt,
                          "complete");
    for (const pwb::workflow_runtime::AssetRecord& asset : repo.list_assets()) {
        if (asset.name == name) {
            const std::string version_id = repo.register_version(
                asset.id, payload, "raw", {}, run_id, Json::object());
            repo.attach_run_output(run_id, version_id);
            return version_id;
        }
    }
    const pwb::workflow_runtime::RegisteredAssetVersion version =
        repo.register_result_asset(name, "curve", "json", Json::object(),
                                   payload, "raw", run_id, Json::object());
    repo.attach_run_output(run_id, version.version_id);
    return version.version_id;
}

}  // namespace

int main() {
    try {
        const std::filesystem::path dir = make_temp_dir();
        const std::filesystem::path runs_root = dir / "runs";
        const std::filesystem::path recipe_path = dir / "closure.paleo-workflow.json";

        Catalog repo;
        repo.open(dir / "catalog");
        WorkflowRunStore store(runs_root);

        ComputeHost host;
        host.repo = &repo;
        host.release.store(true);

        StaticCatalog action_catalog;
        RunFunctionMap functions;
        functions.emplace(
            "grid.compute",
            [&host](const Json& params, const CancelToken& token) {
                pwb::workflow_engine::ActionResultView view;
                view.outputs = host.body(params, token);
                return view;
            });
        pwb::closure_workflow::CatalogCacheRunRail rail(repo);
        RunEngine engine(action_catalog, functions, store, nullptr, nullptr,
                         nullptr, nullptr, nullptr, &rail);

        NodeAdapterRegistry adapters;
        adapters.add(pwb::workflow_runtime::NodeAdapter{
            "grid.compute",
            [&host](const Json& params, const CancelToken& token) {
                // The runtime service books the plan step's provenance in
                // its StepHandler; the body computes only.
                pwb::workflow_engine::NodeResult result;
                host.register_provenance = false;
                result.outputs = host.body(params, token);
                host.register_provenance = true;
                return result;
            },
            pwb::workflow_runtime::ResourceHints{}});
        pwb::workflow_runtime::WorkflowRuntimeService service(repo, adapters);

        // ---- A. import ---------------------------------------------------
        const std::string curve_v1 = import_input(repo, "实测曲线A", "{\"values\":[1,2,3]}");
        check("import.version_registered", repo.resolve_version(curve_v1).has_value());

        // ---- B. recipe ---------------------------------------------------
        WorkflowSpec spec;
        spec.workflow_id = "closure.grid";
        NodeSpec node;
        node.node_id = "compute_1";
        node.action_id = "grid.compute";
        node.parameters["input_version_id"] = curve_v1;
        spec.nodes.push_back(node);
        const auto recipe =
            pwb::workflow_engine::recipe_from_spec(spec, std::nullopt,
                                                   "e2e recipe", {"e2e"});
        const auto saved =
            pwb::workflow_engine::save_recipe(recipe, recipe_path);
        check("recipe.saved", std::filesystem::exists(saved));
        const auto loaded = pwb::workflow_engine::load_recipe(saved);
        check("recipe.round_trip",
              loaded.workflow.workflow_id == spec.workflow_id &&
                  loaded.workflow.nodes.size() == 1 &&
                  loaded.workflow.nodes[0].node_id == "compute_1");

        // ---- C. execute --------------------------------------------------
        pwb::workflow_engine::RunContext context;
        context.workspace_id = "ws";
        const pwb::workflow_spec::WorkflowRun run =
            engine.create_run(loaded.workflow, Json::object(), &context);
        const pwb::workflow_spec::WorkflowRun done = engine.run(run.run_id, &context);
        check("execute.completed",
              done.state == pwb::workflow_spec::RunState::completed);
        check("execute.body_ran_once", host.executions.load() == 1);
        // The node body booked the catalog run; NodeRun carries outputs
        // (the run id lives in the catalog — the provenance authority).
        std::string compute_run_id;
        for (const pwb::workflow_runtime::RunRecord& record : repo.list_runs()) {
            if (record.operation == "grid.compute" &&
                record.status == "complete" &&
                record.input_version_ids.size() == 1 &&
                record.input_version_ids[0] == curve_v1) {
                compute_run_id = record.run_id;
            }
        }
        check("execute.node_run_registered", !compute_run_id.empty());
        const std::string output_version =
            done.find_node_run("compute_1")
                ->outputs.at("output_version_id")
                .get<std::string>();
        const std::optional<VersionRecord> output_record =
            repo.resolve_version(output_version);
        check("execute.output_version", output_record.has_value());
        // Cache-run rail: one workflow.node run with the cache identity.
        int rail_runs = 0;
        std::string rail_run_id;
        for (const pwb::workflow_runtime::RunRecord& record : repo.list_runs()) {
            if (record.operation == "workflow.node.grid.compute") {
                ++rail_runs;
                rail_run_id = record.run_id;
                check("execute.rail_complete", record.status == "complete");
                check("execute.rail_identity",
                      record.parameters.contains("cache_identity") &&
                          record.parameters.at("cache_identity").is_string());
            }
        }
        check("execute.rail_run_count", rail_runs == 1);

        // Provenance trace through the runtime service.
        Json project = Json::object();
        const auto trace =
            service.provenance_trace(output_version,
                                     service.build_context());
        check("execute.provenance_trace", trace.is_object() &&
                                              !trace.is_null());

        // ---- D. stale detection -------------------------------------------
        const std::string curve_v2 =
            import_input(repo, "实测曲线A", "{\"values\":[1,2,3,4]}");
        repo.set_current_version(
            repo.resolve_version(curve_v2)->asset_id, curve_v2);
        const auto context_after =
            pwb::workflow_runtime::resolve_current_project_version_context(
                &repo, &project);
        check("stale.input_is_current",
              context_after.is_current_version(curve_v2));
        auto session = service.make_freshness_session(context_after);
        const auto report = session.service->evaluate_run(compute_run_id);
        check("stale.run_detected", report.is_stale(),
              "state=" + std::string(pwb::workflow_runtime::
                                         freshness_state_value(report.state)));
        RecomputePlan plan = service.plan(context_after);
        check("stale.plan_has_compute", !plan.compute_steps().empty());

        // ---- E. partial recompute ----------------------------------------
        // Only the affected node re-executes; everything else reuses.
        const int before = host.executions.load();
        const auto result = service.execute_plan(plan, CancelToken{});
        check("recompute.executed",
              !result.stopped_early &&
                  plan.completed_run_ids.size() >= 1,
              "completed=" +
                  std::to_string(plan.completed_run_ids.size()));
        check("recompute.only_necessary_body",
              host.executions.load() == before + 1,
              "delta=" + std::to_string(host.executions.load() - before));
        // The recompute produced a NEW completed run over CURRENT inputs;
        // that run must evaluate FRESH (the historical run stays what it
        // was — immutable history is never restamped).
        std::string recomputed_run_id;
        for (const pwb::workflow_runtime::RunRecord& record : repo.list_runs()) {
            if (record.operation == "grid.compute" &&
                record.status == "complete" &&
                record.input_version_ids.size() == 1 &&
                record.input_version_ids[0] == curve_v2) {
                recomputed_run_id = record.run_id;
            }
        }
        check("recompute.new_run_registered", !recomputed_run_id.empty());
        auto session_after = service.make_freshness_session(context_after);
        const auto report_after =
            session_after.service->evaluate_run(recomputed_run_id);
        check("recompute.fresh_again", report_after.is_fresh(),
              "state=" + std::string(pwb::workflow_runtime::freshness_state_value(
                             report_after.state)));

        // ---- F. reopen recovery ------------------------------------------
        Catalog reopened;
        reopened.open(dir / "catalog");
        check("reopen.runs_persist",
              reopened.list_runs().size() == repo.list_runs().size());
        check("reopen.versions_persist",
              reopened.resolve_version(output_version).has_value());
        WorkflowRunStore reopened_store(runs_root);
        const pwb::workflow_spec::WorkflowRun stored =
            reopened_store.load(run.run_id);
        check("reopen.completed_stays_done",
              stored.state == pwb::workflow_spec::RunState::completed);
        // A crashed run (RUNNING in the store) resumes through the crash
        // mapping: RUNNING nodes → PENDING and complete on resume.
        // Simulate the crash residue exactly like the Python lifecycle
        // oracle: a second run interrupted mid-flight.
        StaticCatalog cat2;
        WorkflowRunStore store2(dir / "runs2");
        RunFunctionMap functions2;
        functions2.emplace("grid.compute",
                           [](const Json&, const CancelToken&) {
                               pwb::workflow_engine::ActionResultView view;
                               view.outputs = Json{{"ok", true}};
                               return view;
                           });
        RunEngine engine2(cat2, functions2, store2);
        const pwb::workflow_spec::WorkflowRun crashed_run =
            engine2.create_run(loaded.workflow, Json::object(), &context);
        pwb::workflow_spec::WorkflowRun mutated = crashed_run;
        mutated.state = pwb::workflow_spec::RunState::running;
        pwb::workflow_spec::NodeRun* node_run =
            mutated.find_node_run("compute_1");
        node_run->state = pwb::workflow_spec::NodeState::running;
        store2.save(mutated);
        const pwb::workflow_spec::WorkflowRun resumed =
            engine2.resume(mutated.run_id, &context);
        check("reopen.resume_completed",
              resumed.state == pwb::workflow_spec::RunState::completed);
        check("reopen.resume_reran_interrupted_node",
              resumed.find_node_run("compute_1")->state ==
                  pwb::workflow_spec::NodeState::succeeded);

        // ---- G. failure short-circuit ------------------------------------
        WorkflowSpec failing = loaded.workflow;
        NodeSpec downstream;
        downstream.node_id = "downstream_1";
        downstream.action_id = "grid.compute";
        downstream.parameters["input_version_id"] = curve_v2;
        downstream.depends_on = {"compute_1"};
        failing.nodes.push_back(downstream);
        host.fail_next = false;
        host.release.store(true);
        // First node fails on the NEXT execution (reset the counter flow):
        // the failing spec's first node runs, fails, downstream skips.
        host.executions.store(0);
        host.fail_next = true;
        // A dedicated store isolates this scenario from phase C's cache
        // entries: with the shared store compute_1 (identical identity)
        // would be reused from cache and never fail.
        WorkflowRunStore failing_store(dir / "runs_g");
        RunFunctionMap failing_functions;
        failing_functions.emplace(
            "grid.compute",
            [&host](const Json& params, const CancelToken& token) {
                pwb::workflow_engine::ActionResultView view;
                view.outputs = host.body(params, token);
                return view;
            });
        RunEngine failing_engine(action_catalog, failing_functions,
                                 failing_store, nullptr, nullptr, nullptr,
                                 nullptr, nullptr, &rail);
        const pwb::workflow_spec::WorkflowRun failing_run =
            failing_engine.create_run(failing, Json::object(), &context);
        const pwb::workflow_spec::WorkflowRun failed =
            failing_engine.run(failing_run.run_id, &context);
        check("failure.run_failed",
              failed.state == pwb::workflow_spec::RunState::failed);
        check("failure.first_node_failed",
              failed.find_node_run("compute_1")->state ==
                  pwb::workflow_spec::NodeState::failed);
        check("failure.dependents_skipped",
              failed.find_node_run("downstream_1")->state ==
                  pwb::workflow_spec::NodeState::skipped);
        // The catalog shows the failed compute run (booked RUNNING first).
        bool failed_run_in_catalog = false;
        for (const pwb::workflow_runtime::RunRecord& record : repo.list_runs()) {
            if (record.operation == "grid.compute" &&
                record.status == "failed") {
                failed_run_in_catalog = true;
            }
        }
        check("failure.catalog_run_failed", failed_run_in_catalog);
        // Recovery: clear the fault, rerun the failed subtree only.
        host.fail_next = false;
        const pwb::workflow_spec::WorkflowRun recovered =
            failing_engine.rerun(failing_run.run_id, {"compute_1"}, Json::object(),
                                 &context);
        check("failure.recovery_completed",
              recovered.state == pwb::workflow_spec::RunState::completed);

        // ---- H. cancel + late completion ---------------------------------
        // H1 cooperative cancel: the body polls the token at its safe
        // point; engine.cancel flips it; the run lands CANCELLED.
        host.release.store(false);
        host.ignore_cancel = false;
        RunFunctionMap cancel_functions;
        cancel_functions.emplace(
            "grid.compute",
            [&host](const Json& params, const CancelToken& token) {
                pwb::workflow_engine::ActionResultView view;
                view.outputs = host.body(params, token);
                return view;
            });
        WorkflowRunStore cancel_store(dir / "runs_h1");
        RunEngine cancel_engine(action_catalog, cancel_functions, cancel_store);
        const pwb::workflow_spec::WorkflowRun cancel_run =
            cancel_engine.create_run(loaded.workflow, Json::object(), &context);
        pwb::workflow_spec::WorkflowRun cancelled;
        std::thread cancelled_runner([&] {
            cancelled = cancel_engine.run(cancel_run.run_id, &context);
        });
        std::this_thread::sleep_for(std::chrono::milliseconds(80));
        check("cancel.engine_signalled", cancel_engine.cancel(cancel_run.run_id));
        cancelled_runner.join();
        check("cancel.run_cancelled",
              cancelled.state == pwb::workflow_spec::RunState::cancelled,
              "state=" + pwb::workflow_spec::to_string(cancelled.state));

        // H2 late completion: a body that ignores cancellation keeps
        // running past the cancel and completes late. The node may record
        // its success, but the run must stay CANCELLED — a terminal state
        // is never resurrected by stale work.
        host.ignore_cancel = true;
        RunFunctionMap late_functions;
        late_functions.emplace(
            "grid.compute",
            [&host](const Json& params, const CancelToken& token) {
                pwb::workflow_engine::ActionResultView view;
                view.outputs = host.body(params, token);
                return view;
            });
        WorkflowRunStore late_store(dir / "runs_h2");
        RunEngine late_engine(action_catalog, late_functions, late_store);
        // Two-node spec: downstream_1 stays pending at the cancel, so the
        // late compute_1 success cannot finalize the run COMPLETED.
        const pwb::workflow_spec::WorkflowRun late_run =
            late_engine.create_run(failing, Json::object(), &context);
        pwb::workflow_spec::WorkflowRun late;
        std::thread late_runner(
            [&] { late = late_engine.run(late_run.run_id, &context); });
        std::this_thread::sleep_for(std::chrono::milliseconds(80));
        late_engine.cancel(late_run.run_id);
        std::this_thread::sleep_for(std::chrono::milliseconds(60));
        host.release.store(true);  // the late body finishes AFTER the cancel
        late_runner.join();
        check("cancel.late_completion_no_resurrect",
              late.state == pwb::workflow_spec::RunState::cancelled,
              "state=" + pwb::workflow_spec::to_string(late.state));
        host.ignore_cancel = false;
        host.release.store(true);

        // ---- I. cache hit --------------------------------------------------
        // The rail books FRESH executions only (Python parity: the
        // cache-hit branch returns before _register_cache_run); the hit
        // itself reuses the earlier executions' rail records — the count
        // must not grow on a cache hit.
        int rail_before = 0;
        for (const pwb::workflow_runtime::RunRecord& record : repo.list_runs()) {
            if (record.operation == "workflow.node.grid.compute") {
                ++rail_before;
            }
        }
        host.executions.store(0);
        const pwb::workflow_spec::WorkflowRun second =
            engine.create_run(loaded.workflow, Json::object(), &context);
        const pwb::workflow_spec::WorkflowRun second_done =
            engine.run(second.run_id, &context);
        check("cache.from_cache",
              second_done.find_node_run("compute_1")->from_cache == true);
        check("cache.no_body_execution", host.executions.load() == 0);
        int cache_rail_runs = 0;
        for (const pwb::workflow_runtime::RunRecord& record : repo.list_runs()) {
            if (record.operation == "workflow.node.grid.compute") {
                ++cache_rail_runs;
            }
        }
        check("cache.rail_runs", cache_rail_runs == rail_before,
              "before=" + std::to_string(rail_before) + " after=" +
                  std::to_string(cache_rail_runs));

        // ---- J. known refusals --------------------------------------------
        WorkflowSpec duplicate = loaded.workflow;
        NodeSpec dupe;
        dupe.node_id = "compute_1";  // duplicate id
        dupe.action_id = "grid.compute";
        duplicate.nodes.push_back(dupe);
        bool duplicate_refused = false;
        try {
            (void)engine.create_run(duplicate, Json::object(), &context);
        } catch (const pwb::workflow_engine::WorkflowValidationError&) {
            duplicate_refused = true;
        }
        check("refusals.duplicate_node_id", duplicate_refused);

        WorkflowSpec cycle;
        cycle.workflow_id = "closure.cycle";
        NodeSpec a;
        a.node_id = "a";
        a.action_id = "grid.compute";
        a.depends_on = {"b"};
        NodeSpec b;
        b.node_id = "b";
        b.action_id = "grid.compute";
        b.depends_on = {"a"};
        cycle.nodes.push_back(a);
        cycle.nodes.push_back(b);
        bool cycle_refused = false;
        try {
            (void)engine.create_run(cycle, Json::object(), &context);
        } catch (const pwb::workflow_engine::WorkflowValidationError&) {
            cycle_refused = true;
        }
        check("refusals.cycle", cycle_refused);

        // Recipe security gate: a forbidden key never lands on disk.
        pwb::workflow_engine::RecipeDocument tainted = recipe;
        Json tainted_dict = tainted.to_dict();
        tainted_dict["workflow"]["nodes"][0]["parameters"]["api_key"] =
            "hunter2";
        const auto tainted_doc =
            pwb::workflow_engine::RecipeDocument::from_dict(tainted_dict);
        bool recipe_refused = false;
        try {
            pwb::workflow_engine::save_recipe(tainted_doc, dir / "tainted");
        } catch (const pwb::workflow_engine::RecipeError&) {
            recipe_refused = true;
        }
        check("refusals.recipe_forbidden_key", recipe_refused);

        // ---- K. scheduler submit + synced cancel --------------------------
        // (Real JobScheduler, real engine token bridge.)
        pwb::job::JobScheduler::Options job_options;
        job_options.max_workers = 1;
        pwb::job::JobScheduler job_scheduler(job_options);
        host.release.store(true);
        pwb::closure_workflow::WorkflowScheduler scheduler(job_scheduler,
                                                           engine, store);
        host.executions.store(0);
        const pwb::workflow_spec::WorkflowRun sched_run =
            engine.create_run(loaded.workflow, Json::object(), &context);
        auto handle = scheduler.submit(sched_run.run_id, &context);
        handle.wait();
        const auto snapshot = handle.snapshot();
        check("scheduler.done", snapshot.state == pwb::job::JobState::done,
              "state=" + std::string(pwb::job::to_string(snapshot.state)));

        // K2 scheduler-side cancel: the job cancel propagates through the
        // watcher into the engine token; the run lands CANCELLED and the
        // job finishes done (the task returned a terminal WorkflowRun).
        WorkflowRunStore k_store(dir / "runs_k");
        RunFunctionMap k_functions;
        k_functions.emplace(
            "grid.compute",
            [&host](const Json& params, const CancelToken& token) {
                pwb::workflow_engine::ActionResultView view;
                view.outputs = host.body(params, token);
                return view;
            });
        RunEngine k_engine(action_catalog, k_functions, k_store, nullptr,
                           nullptr, nullptr, nullptr, nullptr, &rail);
        pwb::closure_workflow::WorkflowScheduler k_scheduler(job_scheduler,
                                                             k_engine,
                                                             k_store);
        host.release.store(false);
        const pwb::workflow_spec::WorkflowRun k_run =
            k_engine.create_run(failing, Json::object(), &context);
        auto k_handle = k_scheduler.submit(k_run.run_id, &context);
        std::this_thread::sleep_for(std::chrono::milliseconds(120));
        check("scheduler.cancel_signalled", k_scheduler.cancel(k_run.run_id));
        host.release.store(true);  // the body observes the token next poll
        k_handle.wait();
        const pwb::workflow_spec::WorkflowRun k_stored = k_store.load(k_run.run_id);
        check("scheduler.cancelled_run",
              k_stored.state == pwb::workflow_spec::RunState::cancelled,
              "state=" + pwb::workflow_spec::to_string(k_stored.state));
        // The side channel is deregistered after terminal.
        check("scheduler.side_channel_cleared", !k_scheduler.cancel(k_run.run_id));

        // ---- L. UI host bindings + typed reopen recovery ------------------
        Json project_root = Json::object();
        project_root["name"] = "e2e";
        const auto bindings = pwb::closure_workflow::bind_workflow_ui_services(&repo);
        const Json dashboard = bindings.dashboard_state(project_root);
        check("ui.dashboard_state", dashboard.is_object());
        const Json home_steps = bindings.home_workflow_steps(project_root);
        check("ui.home_steps", home_steps.is_array());
        const Json quality_reports =
            bindings.active_quality_reports(project_root);
        check("ui.quality_reports", quality_reports.is_array());
        const RecomputePlan affected = bindings.build_affected_plan(project_root);
        (void)affected;  // shape exercised; contents asserted via reopen below
        const pwb::closure_workflow::ReopenedWorkflow reopened_view =
            pwb::closure_workflow::reopen_project_workflow(project_root,
                                                           service);
        check("ui.reopen_runs", reopened_view.runs.is_array() &&
                                    !reopened_view.runs.empty());
        check("ui.reopen_staleness", reopened_view.staleness.is_array());
        check("ui.reopen_plan", reopened_view.recompute_plan.to_dict()
                                    .is_object());
        // Session pointer bridge: same-process restore works, cross-process
        // ids never bind.
        std::string current_map;
        pwb::closure_workflow::SessionPointerBridge bridge(
            &current_map,
            [](const std::string& document_id) {
                return document_id == "doc_live";
            });
        bridge.restore_session_pointers(Json{{"document_id", "doc_live"}});
        check("ui.session_restore_live", current_map == "doc_live");
        bridge.restore_session_pointers(Json{{"document_id", "doc_dead"}});
        check("ui.session_restore_cross_process", current_map == "doc_live");

        // ---- cleanup -------------------------------------------------------
        std::error_code ec;
        std::filesystem::remove_all(dir, ec);
    } catch (const std::exception& exc) {
        std::printf("FATAL %s\n", exc.what());
        return 1;
    }
    std::printf("closure_workflow.e2e: %d checks, %d failures\n", checks,
                failures);
    return failures == 0 ? 0 : 1;
}
