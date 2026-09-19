// CONV-30 — Qt bridge implementation (see qt/job_bridge.hpp for the frozen
// safety contracts ported from ui/owned_worker_job.py / ui/thread_keeper.py).

#include "pwb/job_runtime/qt/job_bridge.hpp"

#include <QCoreApplication>
#include <QThread>
#include <QTimer>

#include <algorithm>
#include <stdexcept>
#include <thread>
#include <utility>

namespace pwb::job::qtbridge {

namespace {

// Plain app-lifetime QObject living on the GUI thread. Worker threads aim
// queued invocations at it; because it outlives every owner, the
// worker-side invokeMethod never touches a dead receiver. Per-owner
// suppression (late-callback guard, destroyed receiver) is the released
// flag re-checked inside the queued body at delivery time — a delivery
// racing an owner that was shutdown or destroyed is dropped, never
// committed.
class DeliveryPump : public QObject {
public:
    using QObject::QObject;
};

DeliveryPump& delivery_pump() {
    // Heap-allocated with NO parent at construction (first call may happen
    // on a worker thread — parenting across threads is silently dropped),
    // then moved to the GUI thread and adopted by the app FROM the GUI
    // thread via a queued call: the app owns it, so there is no
    // static-destruction ordering hazard at exit.
    static DeliveryPump* pump = [] {
        auto* created = new DeliveryPump();
        created->moveToThread(QCoreApplication::instance()->thread());
        QMetaObject::invokeMethod(
            created,
            [created] {
                created->setParent(QCoreApplication::instance());
            },
            Qt::QueuedConnection);
        return created;
    }();
    return *pump;
}

// Queue a hop onto the GUI thread. `guard` is the owner's released flag: a
// QMetaCall already queued before shutdown/destruction must not commit
// after release (OwnedWorkerJob guarded-slot parity).
void queue_delivery(std::shared_ptr<std::atomic<bool>> guard,
                    std::function<void()> body) {
    DeliveryPump& pump = delivery_pump();
    QMetaObject::invokeMethod(
        &pump,
        [guard = std::move(guard), body = std::move(body)]() {
            if (guard != nullptr && guard->load()) return;
            body();
        },
        Qt::QueuedConnection);
}

}  // namespace

// ------------------------------------------------------------- JobOwner --

JobOwner::JobOwner(QObject* parent)
    : QObject(parent), released_(std::make_shared<std::atomic<bool>>(false)) {}

JobOwner::~JobOwner() {
    // Destroyed while running (window closed without an explicit shutdown):
    // non-blocking detach — cancel, adopt into the process-lifetime keeper.
    // Mirrors OwnedWorkerJob's destroyed-hook adopt path. Already-queued
    // deliveries are dropped by the released flag at delivery time.
    released_->store(true);
    if (handle_.valid() && !handle_.snapshot().is_terminal()) {
        detach_to_keeper();
    }
}

JobHandle JobOwner::start(JobScheduler& scheduler, JobSpec spec,
                          FinishedFn on_finished, ProgressFn on_progress) {
    if (is_running()) {
        // Fail loudly so this wiring bug can never regress silently
        // (OwnedWorkerJob C17 parity).
        throw std::logic_error("worker job already owns a running job");
    }
    // Fresh guard per start (OwnedWorkerJob state-dict parity): a delivery
    // already queued for the PREVIOUS job keeps its own guard (true after
    // its shutdown) and stays suppressed even after this reset.
    released_ = std::make_shared<std::atomic<bool>>(false);

    auto guard = released_;
    if (on_finished) {
        // Wrap the Python-shaped callbacks (on_done/on_fail/on_cancel)
        // preserving their order and side effects; the outcome hop is
        // queued AFTER the original side effect completed. The degraded
        // refinement is evaluated ONCE through a memoizing predicate that
        // both this wrapper and the scheduler's terminal step share, so
        // the delivered outcome and the cell state can never diverge
        // (Python evaluates degraded_when exactly once; the cache replays
        // that single evaluation).
        struct CachedPredicate {
            std::atomic<int> state{0};  // 0 uncomputed, 1 computing,
                                        // 2 value, 3 threw
            bool value = false;
            // Python parity: degraded_when=None ⇒ the job is never
            // degraded. An empty inner short-circuits to false instead of
            // throwing std::bad_function_call (which would degrade every
            // plain-success job).
            bool evaluate(const std::function<bool(const std::any&)>& inner,
                          const std::any& result) {
                if (!inner) return false;
                int expected = 0;
                if (state.compare_exchange_strong(expected, 1)) {
                    try {
                        value = inner(result);
                        state.store(2);
                    } catch (...) {
                        state.store(3);
                    }
                } else {
                    while (state.load() == 1) std::this_thread::yield();
                }
                if (state.load() == 3) throw std::runtime_error("degraded_when");
                return value;
            }
        };
        auto cache = std::make_shared<CachedPredicate>();
        auto inner_when = std::move(spec.degraded_when);
        std::function<bool(const std::any&)> cached_when =
            [cache, inner_when](const std::any& result) {
                return cache->evaluate(inner_when, result);
            };
        spec.degraded_when = cached_when;

        auto prev_done = std::move(spec.on_done);
        auto prev_fail = std::move(spec.on_fail);
        auto prev_cancel = std::move(spec.on_cancel);
        spec.on_done = [prev_done = std::move(prev_done),
                        cached_when, guard,
                        on_finished](const std::any& result) {
            if (prev_done) prev_done(result);
            bool degraded = false;
            try {
                degraded = cached_when(result);
            } catch (...) {
                degraded = true;  // predicate failure is a caveat
            }
            JobOutcome outcome;
            outcome.state = degraded ? JobState::degraded : JobState::done;
            outcome.result = result;
            queue_delivery(guard, [on_finished, outcome = std::move(outcome)] {
                on_finished(outcome);
            });
        };
        spec.on_fail = [prev_fail = std::move(prev_fail), guard,
                        on_finished](const std::string& error) {
            if (prev_fail) prev_fail(error);
            JobOutcome outcome;
            outcome.state = JobState::failed;
            outcome.error = error;
            queue_delivery(guard, [on_finished, outcome = std::move(outcome)] {
                on_finished(outcome);
            });
        };
        spec.on_cancel = [prev_cancel = std::move(prev_cancel), guard,
                          on_finished]() {
            if (prev_cancel) prev_cancel();
            JobOutcome outcome;
            outcome.state = JobState::cancelled;
            queue_delivery(guard, [on_finished, outcome = std::move(outcome)] {
                on_finished(outcome);
            });
        };
    }
    if (on_progress) {
        spec.on_progress = [guard, on_progress](double ratio,
                                                const std::string& message) {
            queue_delivery(guard, [on_progress, ratio,
                                   text = QString::fromStdString(message)] {
                on_progress(ratio, text);
            });
        };
    }
    handle_ = scheduler.submit(std::move(spec));
    return handle_;
}

bool JobOwner::is_running() const {
    return handle_.valid() && !handle_.snapshot().is_terminal();
}

void JobOwner::cancel() {
    if (handle_.valid()) handle_.cancel();
}

bool JobOwner::shutdown(int wait_ms) {
    if (!handle_.valid()) return true;
    // Mark released BEFORE the wait so any already-queued result delivery
    // is dropped by the guarded slot (OwnedWorkerJob parity).
    released_->store(true);
    handle_.cancel();
    const bool finished = handle_.wait_for(wait_ms / 1000.0);
    if (!finished) detach_to_keeper();
    handle_ = {};
    emit released();
    return finished;
}

void JobOwner::detach_to_keeper() {
    DetachedJobKeeper::instance().adopt(handle_);
}

// ------------------------------------------------------- DetachedJobKeeper --

DetachedJobKeeper::DetachedJobKeeper(QObject* parent)
    : QObject(parent), poll_timer_(new QTimer(this)) {
    poll_timer_->setInterval(200);
    connect(poll_timer_, &QTimer::timeout, this, [this] { reap(); });
}

void DetachedJobKeeper::adopt(const JobHandle& handle) {
    if (!handle.valid()) return;
    for (const JobHandle& existing : jobs_) {
        if (existing.job_id() == handle.job_id()) return;  // idempotent
    }
    jobs_.push_back(handle);
    if (!poll_timer_->isActive()) poll_timer_->start();
}

int DetachedJobKeeper::job_count() {
    reap();
    return static_cast<int>(jobs_.size());
}

void DetachedJobKeeper::reap() {
    jobs_.erase(std::remove_if(jobs_.begin(), jobs_.end(),
                               [](const JobHandle& handle) {
                                   return !handle.valid() ||
                                          handle.snapshot().is_terminal();
                               }),
                jobs_.end());
    if (jobs_.empty() && poll_timer_->isActive()) poll_timer_->stop();
}

DetachedJobKeeper& DetachedJobKeeper::instance() {
    QCoreApplication* app = QCoreApplication::instance();
    static DetachedJobKeeper* keeper = new DetachedJobKeeper(app);
    return *keeper;
}

// -------------------------------------------------------------- quit drain --

void install_quit_drain(std::shared_ptr<JobScheduler> scheduler,
                        int drain_timeout_ms) {
    QCoreApplication* app = QCoreApplication::instance();
    if (app == nullptr) return;
    // The shared_ptr capture keeps the scheduler alive for the drain even
    // when the owning surface was destroyed first; the lambda runs on the
    // GUI thread inside aboutToQuit (direct is correct there).
    QObject::connect(
        app, &QCoreApplication::aboutToQuit, app,
        [scheduler = std::move(scheduler), drain_timeout_ms] {
            scheduler->shutdown(true, drain_timeout_ms / 1000.0);
        },
        Qt::DirectConnection);
}

}  // namespace pwb::job::qtbridge
