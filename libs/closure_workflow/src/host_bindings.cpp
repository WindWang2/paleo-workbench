// host_bindings.cpp — see include/pwb/closure_workflow/host_bindings.hpp.

#include <pwb/closure_workflow/host_bindings.hpp>

#include <pwb/closure_workflow/persistent_catalog.hpp>
#include <pwb/workflow_runtime/freshness.hpp>
#include <pwb/workflow_runtime/qc.hpp>
#include <pwb/workflow_runtime/resolve_context.hpp>
#include <pwb/workflow_runtime/service.hpp>

namespace pwb::closure_workflow {

namespace {

using pwb::domain::Json;
namespace wr = pwb::workflow_runtime;

Json step_to_json(const pwb::project::WorkflowStep& step) {
    return step.to_dict();
}

}  // namespace

void SessionPointerBridge::restore_session_pointers(const Json& outputs) {
    if (!outputs.is_object()) return;
    const auto it = outputs.find("document_id");
    if (it == outputs.end() || !it->is_string()) return;
    const std::string document_id = it->get<std::string>();
    // Python: only restore when the SAME process still holds the handle
    // (document_id in context.map_documents) — across a process boundary
    // the pointer is unrecoverable and downstream consumers fail honestly
    // instead of binding to a wrong document.
    if (has_document_ != nullptr && has_document_(document_id) &&
        current_map_id_ != nullptr) {
        *current_map_id_ = document_id;
    }
}

WorkflowUiServiceBindings bind_workflow_ui_services(
    wr::CatalogRepository* catalog) {
    WorkflowUiServiceBindings bindings;
    bindings.dashboard_state = [](const Json& project_root) {
        return wr::dashboard_state(project_root);
    };
    bindings.home_workflow_steps =
        [catalog](const Json& project_root) {
            // home_workflow_steps mutates the active run's step progress
            // (persisted on save); the controller's seam passes the
            // project root by value, so the Json& overload lands on a
            // local copy — the returned steps carry the progress.
            Json project = project_root;
            wr::StepStatusOptions options;
            options.catalog = catalog;
            const std::vector<pwb::project::WorkflowStep> steps =
                wr::home_workflow_steps(project, options);
            Json list = Json::array();
            for (const pwb::project::WorkflowStep& step : steps) {
                list.push_back(step_to_json(step));
            }
            return list;
        };
    bindings.active_quality_reports = [](const Json& project_root) {
        const std::vector<pwb::project::QualityReport> reports =
            wr::active_quality_reports(project_root);
        Json list = Json::array();
        for (const pwb::project::QualityReport& report : reports) {
            list.push_back(report.to_dict());
        }
        return list;
    };
    bindings.build_affected_plan =
        [catalog](const Json& project_root) {
            return wr::build_affected_products_plan(project_root, std::nullopt,
                                                    catalog);
        };
    return bindings;
}

ReopenedWorkflow reopen_project_workflow(
    const Json& project, wr::WorkflowRuntimeService& runtime) {
    ReopenedWorkflow reopened;

    // 1. The five-segment current context over the persisted store.
    wr::CurrentProjectVersionContext context =
        wr::resolve_current_project_version_context(
            &runtime.repository(), &project);
    reopened.context = context;

    // 2. Persisted runs: the store authority (id → state + node ladder).
    {
        Json runs = Json::array();
        for (const wr::RunRecord& run : runtime.repository().list_runs()) {
            Json entry = Json::object();
            entry["run_id"] = run.run_id;
            entry["operation"] = run.operation;
            entry["status"] = run.status;
            runs.push_back(std::move(entry));
        }
        reopened.runs = std::move(runs);
    }

    // 3. Freshness over the resolved context (every persisted run, the
    // dashboard's staleness question) + the minimal recompute plan
    // (REUSE_EXISTING for finished work; REQUIRES_COMPUTE for the rest —
    // the resume path).
    auto session = runtime.make_freshness_session(context);
    {
        Json staleness = Json::array();
        for (const wr::RunRecord& run : runtime.repository().list_runs()) {
            wr::FreshnessReport report =
                session.service->evaluate_run(run.run_id);
            Json entry = report.to_dict();
            entry["status"] = run.status;
            staleness.push_back(std::move(entry));
        }
        reopened.staleness = std::move(staleness);
    }

    reopened.recompute_plan = runtime.plan(context);
    return reopened;
}

}  // namespace pwb::closure_workflow
