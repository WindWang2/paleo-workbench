#include <pwb/ui_controllers/qt/job_owner_runner.hpp>

#include <pwb/qgis_processing/job_compat.hpp>

namespace pwb::ui_controllers::qt {

JobOwnerRunner::JobOwnerRunner(QObject* parent)
    : QObject(parent), owner_(this) {}

JobOwnerRunner::~JobOwnerRunner() {
    // PwbTaskOwner's destructor runs the bounded shutdown; a task that
    // refuses keeps running under QgsTaskManager (adoption is inherent).
}

bool JobOwnerRunner::is_running() const { return owner_.is_running(); }

job::JobHandle JobOwnerRunner::start(
    job::JobSpec spec, UiJobFinishedFn on_finished,
    std::function<void(double, const std::string&)> on_progress) {
    qgis_processing::PwbTaskOwner::Progress progress;
    if (on_progress) {
        // The bridge reports (fraction >= 0, "") for progress ticks and
        // (-1.0, stage) for stage labels — merge into the runner's
        // (ratio, message) vocabulary (a stage hop keeps the last ratio).
        auto last_fraction = std::make_shared<double>(0.0);
        progress = [last_fraction,
                    on_progress = std::move(on_progress)](
                       double fraction, const QString& stage) {
            if (fraction >= 0.0) *last_fraction = fraction;
            on_progress(fraction >= 0.0 ? fraction : *last_fraction,
                        stage.toStdString());
        };
    }
    qgis_processing::start_job_spec(
        owner_, std::move(spec),
        [on_finished = std::move(on_finished)](
            const qgis_processing::CompatJobOutcome& outcome) {
            if (!on_finished) return;
            UiJobOutcome mapped;
            mapped.state = outcome.state;
            mapped.error = outcome.error;
            mapped.result = outcome.result;
            on_finished(mapped);
        },
        std::move(progress));
    return {};
}

void JobOwnerRunner::start(
    QString kind, QString title,
    pwb::qgis_processing::PaleoFunctionTask::Body body,
    UiJobFinishedFn on_done,
    std::function<void(double, const QString&)> on_progress,
    QString task_key) {
    qgis_processing::PwbTaskOwner::Progress progress;
    if (on_progress) {
        progress = [on_progress = std::move(on_progress)](
                       double fraction, const QString& stage) {
            on_progress(fraction, stage);
        };
    }
    owner_.start(std::move(kind), std::move(title), std::move(body),
                 [on_done = std::move(on_done)](
                     const qgis_processing::PaleoTaskOutcome& outcome) {
                     if (!on_done) return;
                     UiJobOutcome mapped;
                     if (outcome.cancelled) {
                         mapped.state = job::JobState::cancelled;
                     } else if (outcome.failed) {
                         mapped.state = job::JobState::failed;
                         mapped.error = outcome.error.toStdString();
                     } else if (outcome.degraded) {
                         mapped.state = job::JobState::degraded;
                     } else {
                         mapped.state = job::JobState::done;
                     }
                     // Best-effort std::any round-trip: bodies that
                     // ctx.set_result(QVariant::fromValue(std::any(x)))
                     // land in UiJobOutcome::result (other payloads stay
                     // in the QVariant — read outcome directly instead).
                     if (!outcome.result.isNull()) {
                         mapped.result = outcome.result.value<std::any>();
                     }
                     on_done(mapped);
                 },
                 std::move(progress), std::move(task_key));
}

void JobOwnerRunner::cancel() { owner_.cancel(); }

bool JobOwnerRunner::shutdown(int wait_ms) {
    return owner_.shutdown(wait_ms);
}

}  // namespace pwb::ui_controllers::qt
