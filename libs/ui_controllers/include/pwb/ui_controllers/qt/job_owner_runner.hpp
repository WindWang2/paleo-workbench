#pragma once

// UI-14 — UiJobRunner over the QGIS task bridge (PwbTaskOwner /
// QgsTaskManager). One runner per UI job slot (save / recompute / prepare /
// catalog-copy / verify), matching OwnedWorkerJob ownership.
//
// Two start paths:
//   * typed start(kind, title, body, on_done, ...) — new-style
//     PaleoFunctionTask::Body consumers (migration-patterns.md);
//   * the inherited UiJobRunner::start(JobSpec, ...) — the Qt-free cores
//     keep building job::JobSpec values; the spec is adapted onto the
//     bridge through pwb::qgis_processing::body_from_job_spec (JobContext
//     calls map onto PaleoTaskBodyContext; results ride a std::any stash,
//     cancelled-with-partial included).
//
// Thread contract: constructed and used on the GUI thread only.
// on_finished/on_progress are delivered on this object's thread through
// the task bridge's queued hop — after shutdown()/destruction deliveries
// are dropped (released-flag parity); a task that outlives the wait keeps
// running under QgsTaskManager (adoption is inherent).

#include <QObject>
#include <QString>

#include <functional>
#include <string>

#include <pwb/qgis_processing/task_bridge.hpp>
#include <pwb/ui_controllers/job_runner.hpp>

namespace pwb::ui_controllers::qt {

class JobOwnerRunner final : public QObject, public UiJobRunner {
    Q_OBJECT
public:
    // `parent` owns the runner — QObject lifetime. The wrapped
    // PwbTaskOwner takes tasks to the process-shared gate when one is
    // installed (JobCenter), else straight to QgsTaskManager.
    explicit JobOwnerRunner(QObject* parent = nullptr);
    ~JobOwnerRunner() override;

    bool is_running() const override;
    const void* target() const override { return target_; }
    void set_target(const void* target) override { target_ = target; }

    // Legacy JobSpec path (the Qt-free cores' vocabulary). The handle is
    // void — drain-side waits go through shutdown().
    job::JobHandle start(
        job::JobSpec spec, UiJobFinishedFn on_finished,
        std::function<void(double, const std::string&)> on_progress =
            nullptr) override;

    // Typed QGIS-bridge path: body runs on a task-manager thread,
    // on_done/on_progress land on this object's thread. UiJobOutcome is
    // mapped from the PaleoTaskOutcome (typed payloads must round-trip
    // through the result stash — prefer the JobSpec path for std::any
    // results).
    void start(QString kind, QString title,
               pwb::qgis_processing::PaleoFunctionTask::Body body,
               UiJobFinishedFn on_done,
               std::function<void(double, const QString&)> on_progress =
                   nullptr,
               QString task_key = QString());

    void cancel() override;
    bool shutdown(int wait_ms) override;

private:
    pwb::qgis_processing::PwbTaskOwner owner_;
    const void* target_ = nullptr;  // owned by the host (the live document)
};

}  // namespace pwb::ui_controllers::qt
