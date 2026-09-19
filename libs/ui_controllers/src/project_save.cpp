#include <pwb/ui_controllers/project_save.hpp>

namespace pwb::ui_controllers {

job::JobSpec make_project_save_job_spec(
    std::shared_ptr<ProjectSaveApi> api,
    project::PreparedSave prepared,
    std::shared_ptr<ProjectSaveTaskState> task_state) {
    job::JobSpec spec;
    spec.kind = "io";
    spec.title = "project-save";
    spec.run = [api, prepared, task_state](job::JobContext& ctx) -> std::any {
        ctx.report_progress(0.0, {}, "writing");
        auto stats = api->execute_save(prepared);
        if (!stats.is_ok()) {
            const auto error = std::string(domain::to_string(stats.error().code)) +
                               ": " + stats.error().message;
            {
                std::lock_guard<std::mutex> guard(task_state->outcome_mutex);
                task_state->outcome_error = error;
            }
            // Any non-JobCancelled exception lands the job failed (the
            // worker's failed-signal parity); outcome_error was recorded
            // first so a drain can still diagnose it.
            throw std::runtime_error(error);
        }
        {
            // Written BEFORE the terminal bookkeeping so a drain that beats
            // the queued completion delivery still sees the finished write
            // (review C1).
            std::lock_guard<std::mutex> guard(task_state->outcome_mutex);
            task_state->outcome_stats = stats.value();
        }
        ctx.report_progress(1.0, {}, "committing");
        return stats.value();
    };
    return spec;
}

bool may_commit_drained_save(
    const ProjectSaveTaskState& task_state,
    const std::optional<fs::path>& live_project_path) {
    if (task_state.committed.load()) return false;
    if (!task_state.api) return false;
    std::lock_guard<std::mutex> guard(task_state.outcome_mutex);
    if (!task_state.outcome_stats) return false;
    if (!live_project_path) return false;
    return task_state.api->project_path() == *live_project_path;
}

}  // namespace pwb::ui_controllers
