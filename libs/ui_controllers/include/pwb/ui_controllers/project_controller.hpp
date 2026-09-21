#pragma once

// UI-14 — ProjectController Qt-free core (project_controller.py parity).
//
// Orchestrates project lifecycle: open/new/sample/save/save-as/session
// teardown + the deferred catalog-maintenance thread + staged domain
// migration. Everything Qt (dialogs, timers, worker ownership) and every
// window attribute arrive as seams on ProjectHostApi so the orchestration
// runs against plain C++ in tests — the Qt shell binds them onto the real
// MainWindow + JobOwner + QMetaObject::invokeLater.
//
// Document ownership stays with the host (window.project parity):
// document() returns the live pointer, replace_document() moves a new
// document in. Every catalog/service call goes through CatalogRuntimeApi
// (never a process global) and every worker through UiJobRunner.

#include <atomic>
#include <functional>
#include <future>
#include <memory>
#include <optional>
#include <string>
#include <vector>

#include <pwb/project/document.hpp>
#include <pwb/project/manager.hpp>

#include <pwb/ui_controllers/catalog_api.hpp>
#include <pwb/ui_controllers/job_runner.hpp>
#include <pwb/ui_controllers/project_save.hpp>

namespace pwb::ui_controllers {

namespace fs = std::filesystem;

// The MainWindow/AppShell surface the controller consumes. An unset
// std::function is "the host has no such surface" — the controller treats
// it exactly like Python's getattr(..., None): a no-op, never a crash.
struct ProjectHostApi {
    // window.project / window.project_path
    std::function<project::ProjectDocument*()> document;
    std::function<void(project::ProjectDocument&&)> replace_document;
    std::function<std::optional<fs::path>()> project_path;
    std::function<void(const std::optional<fs::path>&)> set_project_path;

    // window._refresh_shell(defer_nonvisible_bindings=…)
    std::function<void(bool defer_nonvisible_bindings)> refresh_shell;
    // window._show_project_error(title, message)
    std::function<void(const std::string& title, const std::string& message)>
        show_error;
    // _confirm_replace_project → QMessageBox.question Yes/No.
    std::function<bool(const std::string& title, const std::string& message)>
        confirm;
    // _choose_open_project / _choose_save_project (QFileDialog).
    std::function<std::optional<fs::path>()> choose_open_project;
    std::function<std::optional<fs::path>()> choose_save_project;

    // Save gates (all run on the GUI thread):
    //   flush_mapping_draft — False → topology gate refused the save;
    //   flush_composite_edits — #1126 composite session commit (count out);
    //   flush_joint_analysis — geomodel joint state → document.
    std::function<bool()> flush_mapping_draft;
    std::function<int()> flush_composite_edits;
    std::function<void(project::ProjectDocument&)> flush_joint_analysis;

    // app_shell.shutdown_workers() → false when a worker refused to stop.
    std::function<bool()> shutdown_workers;
    // detached_job_keeper().job_count() — the C18 teardown gate.
    std::function<int()> detached_job_count;
    // data_page.refresh_domain_views() after a staged migration binds.
    std::function<void()> refresh_domain_views;

    // Marshal a callable onto the GUI thread's next event turn
    // (QTimer(0)/invokeLater parity — the maintenance kickoff AND the
    // migration_staged delivery both ride this).
    std::function<void(std::function<void()>)> post_next_turn;
};

// bootstrap_sample_project result slice (sample_project.py parity).
struct SampleProjectSlice {
    project::ProjectDocument document;
};

// The open-time service factories the controller calls (module functions
// in Python — injected here so no process global exists).
struct ProjectServiceApi {
    // ProjectManager(target).load() — the v6 recovery decision table.
    std::function<domain::Result<project::LoadedProject>(const fs::path&)>
        load_project;
    // resolve_sample_data_root + bootstrap_sample_project.
    std::function<domain::Result<SampleProjectSlice>(
        const std::optional<fs::path>& data_root)>
        bootstrap_sample;
    // ensure_demo_prediction(project, seed=0).
    std::function<void(project::ProjectDocument&)> ensure_demo_prediction;
    // project.domain.sync_workarea_with_coordinate(project) — prepare-side
    // CRS mirror (unset → skipped, Python's try/except: pass parity).
    std::function<void(project::ProjectDocument&)> sync_workarea;
};

class ProjectControllerCore {
public:
    ProjectControllerCore(ProjectHostApi host,
                          CatalogRuntimeApi catalog_runtime,
                          ProjectServiceApi services,
                          ProjectSaveApiFactory save_factory,
                          UiJobRunner* save_runner);

    int session_generation() const { return session_generation_; }
    const std::string& last_open_error() const { return last_open_error_; }

    // ---- session lifecycle ------------------------------------------------
    // _end_current_session parity: drain save → cancel+join maintenance →
    // flush composite → shutdown shell workers → detached-keeper gate →
    // close catalog → reset runtime. Returns false when a worker refused
    // (the session stays live; the caller restores the shell and aborts).
    bool end_current_session();
    bool shutdown_current_session() { return end_current_session(); }
    void restore_shell_after_failed_stop();

    // ---- project operations -----------------------------------------------
    void new_project(const std::string& name = "Untitled Project");
    bool open_project_path(const fs::path& path);
    bool open_sample_project(const std::optional<fs::path>& data_root =
                                 std::nullopt);
    bool create_project_from_document(project::ProjectDocument&& doc,
                                      const fs::path& intermediate_dir);

    // ---- saves --------------------------------------------------------------
    std::optional<fs::path> save_project();       // blocking facade
    bool save_project_async();                    // #1040 worker save
    bool save_job_running() const;
    std::optional<fs::path> save_project_as(
        const std::optional<fs::path>& path);

    // _drain_save_job parity — public so window close can drive it too.
    bool drain_save_job(int wait_ms = 2000);

    // ---- dialog-facing helpers ----------------------------------------------
    std::string project_properties_text() const;
    static fs::path normalize_project_path(const fs::path& path);
    static std::string default_project_start_dir(
        const std::optional<fs::path>& project_path,
        const std::vector<fs::path>& workspace_roots,
        const fs::path& home);

    // _on_domain_migration_staged — the GUI-thread bind the maintenance
    // thread's payload lands on (called via post_next_turn).
    void on_domain_migration_staged(const std::string& project_path,
                                    int generation,
                                    std::map<std::string, std::string> mapping,
                                    const std::any& staged);

private:
    // _close_catalog / _open_catalog / _schedule_catalog_maintenance parity.
    void close_catalog_();
    std::optional<std::string> open_catalog_(const fs::path& target);
    void schedule_catalog_maintenance_(const fs::path& target,
                                       project::ProjectDocument* loaded);
    void run_catalog_maintenance_(int generation, fs::path target,
                                  project::ProjectDocument* loaded,
                                  domain::Json resources_snapshot,
                                  std::shared_ptr<std::atomic<bool>> cancel);
    void register_persisted_factor_grids_(const fs::path& project_path);
    void rebase_factor_grid_artifact_paths_(const fs::path& old_path,
                                            const fs::path& new_path);
    void rebase_interpretation_artifact_paths_(const fs::path& old_path,
                                               const fs::path& new_path);
    void rebase_staged_catalog_artifact_paths_(const fs::path& target);
    void flush_composite_vector_edits_();
    void finish_async_save_(const UiJobOutcome& outcome,
                            std::shared_ptr<ProjectSaveTaskState> task_state);
    bool maintenance_running_() const;
    void join_maintenance_(std::chrono::milliseconds timeout);

    ProjectHostApi host_;
    CatalogRuntimeApi catalog_;
    ProjectServiceApi services_;
    ProjectSaveApiFactory save_factory_;
    UiJobRunner* save_runner_;  // non-owning — the shell owns the runner

    // Atomic (#1449): the catalog-maintenance std::async worker reads it
    // for staleness while the GUI thread increments it — a plain int was
    // a data race (UB).
    std::atomic<int> session_generation_{0};
    std::string last_open_error_;
    // The save task state a drain inspects (survives runner shutdown).
    std::shared_ptr<ProjectSaveTaskState> save_task_state_;
    std::vector<job::JobHandle> detached_save_jobs_;  // observability only

    std::shared_ptr<std::atomic<bool>> maintenance_cancel_;
    std::future<void> maintenance_future_;
};

}  // namespace pwb::ui_controllers
