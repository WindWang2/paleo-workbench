#pragma once

// CONV-30 — Qt queued event bridge for the job runtime (target pwb_job_qt).
//
// Port of the PySide glue in paleo_workbench/ui/owned_worker_job.py
// (OwnedWorkerJob) and ui/thread_keeper.py (DetachedJobKeeper) onto the
// C++ scheduler. The frozen safety contracts:
//
//  - NO CROSS-THREAD QObject MISUSE: worker-side callbacks never touch Qt
//    state directly; completions/progress/errors are re-delivered on the
//    GUI thread through queued QMetaObject::invokeMethod aimed at the
//    app-lifetime delivery pump (a plain QObject on the GUI thread).
//  - SAFE DESTRUCTION (destroyed receiver): the queued body re-checks the
//    owner's released flag at delivery time, so a delivery racing an owner
//    that was destroyed or shutdown is dropped, never committed. The pump
//    itself outlives every owner, so the worker-side invokeMethod can
//    never target a dead QObject.
//  - LATE-CALLBACK GUARD: after shutdown() the released flag drops any
//    already-queued delivery (a QMetaCall queued before shutdown must not
//    commit after release — OwnedWorkerJob parity).
//  - WINDOW CLOSE WHILE RUNNING: JobOwner::shutdown waits a bounded time;
//    on timeout the job is adopted by the process-lifetime
//    DetachedJobKeeper so the work continues and results stay queryable
//    without the page.
//  - APP QUIT: install_quit_drain connects QCoreApplication::aboutToQuit
//    to a bounded scheduler drain — the process must not die with live
//    jobs (C++ jthreads cannot be abandoned the way Python daemon threads
//    can).

#include <atomic>
#include <functional>
#include <memory>
#include <vector>

#include <QObject>
#include <QString>

#include <pwb/job_runtime/job_scheduler.hpp>

class QTimer;

namespace pwb::job::qtbridge {

// Deterministic terminal outcome delivered to the GUI thread. Computed on
// the worker thread inside the terminal callbacks (so the frozen
// callback-before-terminal ordering is preserved) and carried into the
// queued hop by value — no shared state crosses threads.
struct JobOutcome {
    JobState state{JobState::cancelled};  // done / degraded / failed / cancelled
    std::string error;                    // failed only
    std::any result;                      // done / degraded (the callable's return)
};

using FinishedFn = std::function<void(const JobOutcome&)>;
using ProgressFn = std::function<void(double, const QString&)>;

// One ownership slot for a UI surface — port of OwnedWorkerJob.
//
// Completion delivery contract: the outcome dispatch runs on the worker
// thread (Qt-free, deterministic values only); the observer call hops to
// the GUI thread as a queued invocation carrying the JobOutcome by value.
// The degraded refinement runs inside the done wrapper (after the Python
// on_done side effects, before delivery) so the GUI never sees a plain
// done for a degraded result.
class JobOwner : public QObject {
    Q_OBJECT
public:
    explicit JobOwner(QObject* parent = nullptr);
    ~JobOwner() override;

    JobOwner(const JobOwner&) = delete;
    JobOwner& operator=(const JobOwner&) = delete;

    // Submits through `scheduler` and owns the job until terminal.
    // Throws std::logic_error when this owner already runs a job
    // (OwnedWorkerJob "already owns a thread" parity). Completions are
    // delivered on the owner's thread; after shutdown()/destruction they
    // are dropped. `scheduler` must outlive every JobHandle it produced —
    // the product hosts it in a shared_ptr captured by the quit drain.
    JobHandle start(JobScheduler& scheduler, JobSpec spec,
                    FinishedFn on_finished, ProgressFn on_progress = {});

    [[nodiscard]] bool is_running() const;

    // Cooperative cancellation without tearing anything down (the job
    // keeps running until it observes the token).
    void cancel();

    // Cancel and wait up to wait_ms. On timeout the job is adopted by the
    // detached keeper (kept app-lifetime) and released() is emitted.
    // Returns true when the job reached a terminal state within the wait.
    bool shutdown(int wait_ms = 3000);

signals:
    void released();

private:
    void detach_to_keeper();

    std::shared_ptr<std::atomic<bool>> released_;
    JobHandle handle_;  // GUI-thread only (owner lives on the GUI thread)
};

// Process-lifetime keeper for jobs that outlive their owner (port of
// DetachedJobKeeper). Adopted jobs are held until terminal so results stay
// queryable; a poll timer reaps terminal jobs. job_count() is part of the
// self-check surface (adopted jobs must eventually drain to zero).
class DetachedJobKeeper : public QObject {
    Q_OBJECT
public:
    explicit DetachedJobKeeper(QObject* parent = nullptr);

    void adopt(const JobHandle& handle);
    [[nodiscard]] int job_count();

    // App-lifetime singleton, parented to QCoreApplication::instance().
    // Intentionally heap-allocated: the app owns it, no static-destruction
    // ordering hazard at exit.
    static DetachedJobKeeper& instance();

private:
    void reap();

    std::vector<JobHandle> jobs_;
    QTimer* poll_timer_;
};

// Connect QCoreApplication::aboutToQuit to a bounded drain of `scheduler`.
// The scheduler is captured through its shared_ptr so the drain always
// runs on a live object even when the owning surface died first.
void install_quit_drain(std::shared_ptr<JobScheduler> scheduler,
                        int drain_timeout_ms = 5000);

}  // namespace pwb::job::qtbridge
