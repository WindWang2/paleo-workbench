#include <pwb/ui_controllers/qt/job_owner_runner.hpp>

namespace pwb::ui_controllers::qt {

JobOwnerRunner::JobOwnerRunner(job::JobScheduler& scheduler,
                               QObject* parent)
    : QObject(parent), scheduler_(scheduler), owner_(this) {}

JobOwnerRunner::~JobOwnerRunner() {
    // JobOwner's destructor runs the bounded shutdown; a job that refuses
    // is adopted by the detached keeper (job_bridge contract).
}

bool JobOwnerRunner::is_running() const { return owner_.is_running(); }

job::JobHandle JobOwnerRunner::start(
    job::JobSpec spec, UiJobFinishedFn on_finished,
    std::function<void(double, const std::string&)> on_progress) {
    job::qtbridge::FinishedFn finish;
    if (on_finished) {
        finish = [on_finished = std::move(on_finished)](
                     const job::qtbridge::JobOutcome& outcome) {
            UiJobOutcome mapped;
            mapped.state = outcome.state;
            mapped.error = outcome.error;
            mapped.result = outcome.result;
            on_finished(mapped);
        };
    }
    job::qtbridge::ProgressFn progress;
    if (on_progress) {
        progress = [on_progress = std::move(on_progress)](
                       double ratio, const QString& message) {
            on_progress(ratio, message.toStdString());
        };
    }
    return owner_.start(scheduler_, std::move(spec), std::move(finish),
                        std::move(progress));
}

void JobOwnerRunner::cancel() { owner_.cancel(); }

bool JobOwnerRunner::shutdown(int wait_ms) {
    return owner_.shutdown(wait_ms);
}

}  // namespace pwb::ui_controllers::qt
