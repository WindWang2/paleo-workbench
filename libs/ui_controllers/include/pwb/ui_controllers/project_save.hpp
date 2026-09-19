#pragma once

// UI-14 — project_save_worker.py + the save-phase seam
// (project_controller.py save orchestration).
//
// The C++ ProjectManager now carries the real three-phase API
// (prepare_save / execute_save / commit_save — the Python manager's #1040
// split), so ProjectSaveApi is a thin abstract port over it. Tests fake
// the seam; the production adapter is ManagerProjectSaveApi.
//
// ProjectSaveTaskState is ProjectSaveTask's worker-side bookkeeping:
// outcome_stats/outcome_error are written by the worker BEFORE the
// terminal bookkeeping runs so a session drain that beats the queued
// completion delivery can still commit a finished write (review C1 —
// dropping the commit would make the next save raise a false stale-write
// refusal).

#include <atomic>
#include <memory>
#include <optional>
#include <string>

#include <pwb/job_runtime/job_contract.hpp>
#include <pwb/project/manager.hpp>

namespace pwb::ui_controllers {

namespace fs = std::filesystem;

// The save manager port — one instance per save attempt (Python builds a
// fresh ProjectManager(path) per save; the adapter does the same).
class ProjectSaveApi {
public:
    virtual ~ProjectSaveApi() = default;

    virtual const fs::path& project_path() const = 0;

    // GUI thread — guards + detached payload. Returns
    // DataError(FutureSchema/ConflictBaseVersion/IoError) on failure.
    virtual domain::Result<project::PreparedSave> prepare_save(
        project::ProjectDocument& document) = 0;

    // Worker thread — detached payload only.
    virtual domain::Result<project::SaveStats> execute_save(
        const project::PreparedSave& prepared) = 0;

    // GUI thread — publish post-save state onto the LIVE document.
    virtual void commit_save(project::ProjectDocument& document,
                             const project::PreparedSave& prepared,
                             const project::SaveStats& stats) = 0;
};

// Production adapter over pwb::project::ProjectManager.
class ManagerProjectSaveApi final : public ProjectSaveApi {
public:
    explicit ManagerProjectSaveApi(fs::path project_path)
        : manager_(std::move(project_path)) {}

    const fs::path& project_path() const override { return manager_.path(); }
    domain::Result<project::PreparedSave> prepare_save(
        project::ProjectDocument& document) override {
        return manager_.prepare_save(document);
    }
    domain::Result<project::SaveStats> execute_save(
        const project::PreparedSave& prepared) override {
        return manager_.execute_save(prepared);
    }
    void commit_save(project::ProjectDocument& document,
                     const project::PreparedSave& prepared,
                     const project::SaveStats& stats) override {
        manager_.commit_save(document, prepared, stats);
    }

private:
    project::ProjectManager manager_;
};

// Factory seam — one manager per save (Python `ProjectManager(path)`).
using ProjectSaveApiFactory =
    std::function<std::unique_ptr<ProjectSaveApi>(const fs::path& path)>;

// ProjectSaveTask parity — the outcome bookkeeping a drain inspects.
// outcome_stats/outcome_error are guarded by the mutex: the worker writes
// them before its terminal bookkeeping; the GUI reads them after join.
struct ProjectSaveTaskState {
    int generation = -1;
    std::shared_ptr<ProjectSaveApi> api;       // the per-save manager
    project::PreparedSave prepared;            // captured at prepare time
    std::atomic<bool> committed{false};

    mutable std::mutex outcome_mutex;
    std::optional<project::SaveStats> outcome_stats;
    std::optional<std::string> outcome_error;
};

// Build the JobSpec for the I/O half (ProjectSaveTask.run parity):
// run() = progress("writing") → api.execute_save → record outcome_stats →
// progress("committing") → return the stats. on_fail records
// outcome_error ("{Type}: {message}" parity is carried by the error
// string the runtime produces — "<code>: <message>").
job::JobSpec make_project_save_job_spec(
    std::shared_ptr<ProjectSaveApi> api,
    project::PreparedSave prepared,
    std::shared_ptr<ProjectSaveTaskState> task_state);

// Drain-side commit test (the #1040 review-C1 rule): a completed write
// whose queued completion delivery was dropped may still be committed
// when its project path still matches the LIVE project path.
bool may_commit_drained_save(
    const ProjectSaveTaskState& task_state,
    const std::optional<fs::path>& live_project_path);

}  // namespace pwb::ui_controllers
