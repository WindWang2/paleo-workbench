#pragma once

// UI-14 — UiJobRunner over job::qtbridge::JobOwner + the shared
// JobScheduler. One runner per UI job slot (save / recompute / prepare /
// catalog-copy / verify), matching OwnedWorkerJob ownership.
//
// Thread contract: constructed and used on the GUI thread only.
// on_finished/on_progress are delivered on this object's thread through
// the bridge's queued hop — after shutdown()/destruction deliveries are
// dropped (released-flag parity), and a timed-out job is adopted by the
// detached keeper so its write can still be queried.

#include <QObject>
#include <QString>

#include <pwb/job_runtime/qt/job_bridge.hpp>
#include <pwb/ui_controllers/job_runner.hpp>

namespace pwb::ui_controllers::qt {

class JobOwnerRunner final : public QObject, public UiJobRunner {
    Q_OBJECT
public:
    // `scheduler` must outlive every JobHandle it produced (the product
    // hosts it app-lifetime). `parent` owns the runner — QObject lifetime.
    explicit JobOwnerRunner(job::JobScheduler& scheduler,
                            QObject* parent = nullptr);
    ~JobOwnerRunner() override;

    bool is_running() const override;
    const void* target() const override { return target_; }
    void set_target(const void* target) override { target_ = target; }

    job::JobHandle start(
        job::JobSpec spec, UiJobFinishedFn on_finished,
        std::function<void(double, const std::string&)> on_progress =
            nullptr) override;

    void cancel() override;
    bool shutdown(int wait_ms) override;

private:
    job::JobScheduler& scheduler_;
    job::qtbridge::JobOwner owner_;
    const void* target_ = nullptr;  // owned by the host (the live document)
};

}  // namespace pwb::ui_controllers::qt
