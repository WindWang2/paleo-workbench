#pragma once

// UI-14 — WorkflowController Qt-free core (workflow_controller.py parity).
//
// Cross-page workflow orchestration for the main window: the affected-
// products recompute run (plan build + PlanExecutor + staged factor-task
// commit on the GUI thread), the "发送制备" factor-prepare run (snapshot
// on the GUI thread, schedule on the worker, fingerprint-guarded commit
// back), page-update fan-out after prediction/QC/stratigraphy/contour
// events, prediction→mapping compile routing, demo-draft generation and
// the prediction-source import relay.
//
// Everything Qt (message boxes, dirty-confirm, preview-settings dialog,
// page widgets) and every window/app_shell attribute arrive as
// std::function seams — unset means getattr(..., None): a no-op surface.
// The scientific kernels that have no Pwb API yet (dashboard_state,
// build_affected_products_plan, compile_map_*, commit_prepare_batch_result,
// the live-grid store, the generation counter) are injected seams — the
// host binds the real services; tests inject fakes.
//
// Generation/cancellation contracts preserved verbatim:
//  - next_factor_prepare_generation() is the PROCESS-GLOBAL run identity
//    (#834): prepare AND recompute runs draw from it; a later draw
//    supersedes every earlier staged result;
//  - staged task metadata commits only when runner.target() == the LIVE
//    document AND result.generation == current generation;
//  - a superseded run clears ONLY grids it itself stored (fingerprint
//    compare) — never the cache entry a newer run keyed over (#881).

#include <any>
#include <filesystem>
#include <functional>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <utility>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/project/document.hpp>
#include <pwb/ui_shell/navigation.hpp>
#include <pwb/ui_workers/factor_prepare.hpp>
#include <pwb/workflow_runtime/recompute_plan.hpp>

#include <pwb/ui_controllers/catalog_api.hpp>
#include <pwb/ui_controllers/host_api.hpp>
#include <pwb/ui_controllers/job_runner.hpp>

namespace pwb::ui_controllers {

namespace fs = std::filesystem;

// ---------------------------------------------------------------------------
// Worker payloads
// ---------------------------------------------------------------------------

// _RecomputeWorker result payload (completed(plan, result, task_updates)
// + worker.grids/worker.generation ride the same object — the Python slot
// reads them off the worker it stashed, the JobOutcome carries them here).
struct RecomputeRunResult {
    workflow_runtime::RecomputePlan plan;
    workflow_runtime::PlanExecutionResult result;
    // (task_id, staged task Json) — deep copies the worker interpolated.
    std::vector<std::pair<std::string, domain::Json>> task_updates;
    // task_id -> grid payload this run stored (type-erased; the live-grid
    // store is host-owned).
    std::map<std::string, std::any> grids;
    int generation = 0;
};

// factor_map step seams (_factor_map_handler parity): the task row lives
// inside the project root snapshot the worker carries; interpolate_fn
// mutates the STAGED copy (never the live document) with the task's own
// recorded algorithm parameters (#919); grid_peek_fn reads the live-grid
// store entry the interpolation just produced.
struct FactorRecomputeSeams {
    std::function<void(domain::Json& staged_task,
                       const domain::Json& project_root)>
        interpolate_fn;
    std::function<std::any(const std::string& task_id)> grid_peek_fn;
};

// Worker body — plan build + PlanExecutor({"factor_map": handler}).
// `project_root` is the GUI-thread snapshot (the worker never touches the
// live document). Throws on plan/handler failure (the failed-signal
// parity: "{Type}: {message}" is carried by the thrown message).
RecomputeRunResult run_recompute(
    const domain::Json& project_root_snapshot, int generation,
    const std::function<workflow_runtime::RecomputePlan(
        const domain::Json& project_root)>& build_plan,
    const FactorRecomputeSeams& factor_seams, job::JobContext& ctx);

// JobSpec builder — kind "compute.recompute". The outcome carries the
// RecomputeRunResult; the GUI-thread finish consumes it.
job::JobSpec make_recompute_job_spec(
    domain::Json project_root_snapshot, int generation,
    std::function<workflow_runtime::RecomputePlan(const domain::Json&)>
        build_plan,
    FactorRecomputeSeams factor_seams);

// ---------------------------------------------------------------------------
// Host seams
// ---------------------------------------------------------------------------

// Process-global run identity (#834) — factor_prepare_scheduler's
// generation counter, host-owned.
struct PrepareGenerationApi {
    std::function<int()> next;
    std::function<int()> current;
};

// The live-grid store (factor_grid_artifacts.py parity — host-owned cache;
// every entry keyed by task id).
struct LiveFactorGridApi {
    // store_live_factor_grid(task_id, grid).
    std::function<void(const std::string& task_id, std::any grid)> store;
    // grid_result_fingerprint(grid) → fingerprint | nullopt.
    std::function<std::optional<std::string>(const std::any& grid)>
        fingerprint;
    // clear_live_factor_grid_if_fingerprint(task_id, fp) → cleared.
    std::function<bool(const std::string& task_id,
                       const std::string& fingerprint)>
        clear_if_fingerprint;
};

// Workflow/qc/pipeline service functions (Python module calls — injected;
// an unset function degrades honestly like the Python try/except paths).
struct WorkflowServiceApi {
    // workflow.service.dashboard_state(project) → Json dict.
    std::function<domain::Json(const domain::Json& project_root)>
        dashboard_state;
    // workflow.service.home_workflow_steps(project) → Json list.
    std::function<domain::Json(const domain::Json& project_root)>
        home_workflow_steps;
    // workflow.qc.active_quality_reports(project) → Json list.
    std::function<domain::Json(const domain::Json& project_root)>
        active_quality_reports;
    // workflow.service.build_affected_products_plan(project) → plan.
    std::function<workflow_runtime::RecomputePlan(
        const domain::Json& project_root)>
        build_affected_plan;
    // pipeline.compile_map.compile_map_draft(project, seed=0).
    std::function<void(domain::Json& project_root, int seed)>
        compile_map_draft;
    // pipeline.compile_map_production.compile_map_production(...) —
    // throws ProductionMapError (a std::exception) on compile failure.
    std::function<void(domain::Json& project_root,
                       const std::string& prediction_task_id,
                       const domain::Json& prediction_payload,
                       CatalogServiceApi* catalog_service,
                       const std::optional<std::string>&
                           prediction_version_id)>
        compile_map_production;
    // PrepareProjectSlice build (FactorTaskSlice conversion is host glue —
    // the scientific fields clone exactly like the scheduler's slice).
    std::function<ui_workers::PrepareProjectSlice(
        const project::ProjectDocument& document)>
        prepare_slice;
    // commit_prepare_batch_result(project, result, expected_generation) →
    // number of discarded stale results (host-side in Python too).
    std::function<int(project::ProjectDocument& document,
                      const ui_workers::FactorPrepareBatchResult& result,
                      int expected_generation)>
        commit_prepare;
};

// QMessageBox vocabulary + the modal dialogs the controller opens.
struct WorkflowDialogApi {
    // QMessageBox.information / .warning (title, text).
    std::function<void(const std::string& title, const std::string& text)>
        info;
    std::function<void(const std::string& title, const std::string& text)>
        warning;
    enum class DirtyChoice { save, discard, cancel };
    // QMessageBox.question Save|Discard|Cancel — returns the choice.
    std::function<DirtyChoice(const std::string& title,
                              const std::string& text)>
        dirty_confirm;
    // PreviewSettingsDialog.exec() — receives the reader panel's current
    // settings + mode, returns the applied settings (nullopt = cancelled).
    std::function<std::optional<domain::Json>(
        const domain::Json& current_settings, const std::string& mode)>
        preview_settings_editor;
};

// The app_shell/page-widget surface (window.app_shell.update_*_page +
// page attribute sinks). All Json payloads are the project-root sections
// the Python pages consume.
struct WorkflowPageApi {
    // window.project — the live document (nullptr before first open).
    std::function<project::ProjectDocument*()> document;
    // app_shell.navigate_to(hub, submodule) — hub is a kPageIndex* value.
    std::function<void(int hub, const std::string& submodule)> navigate_to;
    // update_home_page(dashboard_state, home_workflow_steps, project=…).
    std::function<void(const domain::Json& state,
                       const domain::Json& steps)>
        update_home_page;
    // update_data_page(dashboard_state, resources, export_artifacts).
    std::function<void(const domain::Json& state,
                       const domain::Json& resources,
                       const domain::Json& export_artifacts)>
        update_data_page;
    // update_review_export_page(reports, paleomap_documents, artifacts).
    std::function<void(const domain::Json& reports,
                       const domain::Json& paleomap_documents,
                       const domain::Json& export_artifacts)>
        update_review_export_page;
    std::function<void(const domain::Json& prediction_tasks)>
        update_seismic_prediction_page;
    std::function<void(const domain::Json& prediction_tasks)>
        update_well_log_prediction_page;
    // update_visualization_page(resources, prediction_tasks, paleomaps).
    std::function<void(const domain::Json& resources,
                       const domain::Json& prediction_tasks,
                       const domain::Json& paleomap_documents)>
        update_visualization_page;
    // update_mapping_page(paleomap_documents, factor_tasks, project_crs).
    std::function<void(const domain::Json& paleomap_documents,
                       const domain::Json& factor_map_tasks,
                       const std::string& project_crs)>
        update_mapping_page;
    // update_preparation_page(factor_map_tasks).
    std::function<void(const domain::Json& factor_map_tasks)>
        update_preparation_page;
    // update_sequence_framework_page(stratigraphy).
    std::function<void(const domain::Json& stratigraphy)>
        update_sequence_framework_page;
    // update_stratigraphy_correlation_page(project) — takes the document.
    std::function<void()> update_stratigraphy_correlation_page;

    // ---- widget-level sinks (hasattr(...) getattr parity) -------------
    // preparation page task_panel.summary_label.setText.
    std::function<void(const std::string& text)> prep_summary_text;
    // preparation page.update_state(factor_map_tasks).
    std::function<void(const domain::Json& factor_map_tasks)> update_prep_state;
    // mapping page is_dirty() / save_draft() / set_project(project).
    std::function<bool()> mapping_is_dirty;
    std::function<bool()> mapping_save_draft;
    std::function<void()> mapping_set_project;
    // visualization page.open_ref(ref string).
    std::function<void(const std::string& ref)> open_viz_ref;
    // prediction pages select_*_resource(resource_id) → bool.
    std::function<bool(const std::string& resource_id)> select_well_resource;
    std::function<bool(const std::string& resource_id)> select_seismic_resource;
    // data page.begin_import_well_log_paths(paths) → bool started.
    std::function<bool(const std::vector<fs::path>& paths)>
        begin_import_well_log_paths;
    // well-log page.set_source_import_status(text).
    std::function<void(const std::string& text)> set_source_import_status;

    // reader panel (preview settings): current values for the dialog and
    // the apply sink — "route to the current shell, never a stale page".
    std::function<domain::Json()> preview_settings;
    std::function<std::string()> preview_mode;
    std::function<void(const domain::Json&)> set_preview_settings;

    // window._refresh_shell() (demo-draft path).
    std::function<void()> refresh_shell;
    // Marshal onto the GUI thread (worker progress hops — the Qt shell
    // binds QMetaObject::invokeMethod queued; tests run inline).
    std::function<void(std::function<void()>)> post_to_gui;
};

// ---------------------------------------------------------------------------
// Core
// ---------------------------------------------------------------------------

class WorkflowCore {
public:
    WorkflowCore(WorkflowPageApi pages, WorkflowDialogApi dialogs,
                 WorkflowServiceApi services, CatalogRuntimeApi catalog,
                 PrepareGenerationApi generation, LiveFactorGridApi grids,
                 FactorRecomputeSeams factor_recompute,
                 ui_workers::FactorPrepareSeams prepare_seams,
                 UiJobRunner* recompute_job, UiJobRunner* prepare_job);

    // window.project (may be nullptr before first open).
    project::ProjectDocument* document() const;

    // ---- preview settings ---------------------------------------------------
    void show_preview_settings();
    void apply_preview_settings(const domain::Json& settings);

    // ---- recompute (「更新受影响成果」) ---------------------------------------
    void request_recompute();
    void on_recompute_completed(const RecomputeRunResult& payload);
    void on_recompute_failed(const std::string& message);

    // ---- page-update fan-out --------------------------------------------------
    void refresh_home_steps();
    void refresh_data_page();
    void on_qc_reports_updated();
    void on_well_log_prediction_updated();
    void on_seismic_prediction_updated();
    void on_factor_maps_updated();
    void on_contour_drafts_updated();
    void on_stratigraphy_updated();

    // ---- 发送制备 (well-log → preparation) ------------------------------------
    void on_well_log_send_to_prep();
    void on_prep_send_progress(const ui_workers::FactorPrepareProgress& update);
    void on_prep_send_completed(
        const ui_workers::FactorPrepareBatchResult& result);
    void on_prep_send_failed(const std::string& message);
    void on_prep_send_cancelled();

    // ---- 发送编图 (seismic → mapping) ------------------------------------------
    // Demo task → demo draft only; spatial production result → production
    // compiler; non-spatial scientific result → BLOCK honestly.
    void on_seismic_send_to_mapping();

    // ---- demo draft + navigation ------------------------------------------------
    void on_generate_demo_map_draft();
    void on_open_in_visualization(const std::string& ref);
    // getattr(resource, "id", "") parity — any handle shape routes by id.
    void on_open_in_well_prediction(const AssetHandle& resource);
    void on_open_in_seismic_prediction(const AssetHandle& resource);
    void on_home_navigation(int legacy_index);

    // ---- prediction-source import relay -----------------------------------------
    void on_well_log_import_requested(const std::vector<fs::path>& raw_paths);
    void on_prediction_source_import_finished(
        const std::vector<ResourceItem>& added);
    void on_prediction_source_import_failed(const std::string& message);

    static std::string well_log_import_path_key(const fs::path& path);

    int prepare_generation() const { return prepare_generation_; }

private:
    domain::Json root_section_(const char* key) const;
    std::string project_crs_() const;
    void info_(const std::string& title, const std::string& text) const;
    void warning_(const std::string& title, const std::string& text) const;
    void update_home_() const;
    void update_mapping_() const;
    void set_prep_summary_(const std::string& text) const;

    WorkflowPageApi pages_;
    WorkflowDialogApi dialogs_;
    WorkflowServiceApi services_;
    CatalogRuntimeApi catalog_;
    PrepareGenerationApi generation_;
    LiveFactorGridApi grids_;
    FactorRecomputeSeams factor_recompute_;
    ui_workers::FactorPrepareSeams prepare_seams_;
    UiJobRunner* recompute_job_;
    UiJobRunner* prepare_job_;

    int prepare_generation_ = 0;
    // (completed result, generation) of the last recompute submission —
    // the Python `self._recompute_worker` stash the commit slot reads.
    std::shared_ptr<RecomputeRunResult> last_recompute_;
    std::set<std::string> pending_well_log_import_paths_;
};

}  // namespace pwb::ui_controllers
