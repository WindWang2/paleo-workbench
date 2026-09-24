#include <pwb/qgis_processing/task_bridge.hpp>

#include <QPointer>
#include <QTimer>

#include <qgsapplication.h>
#include <qgstaskmanager.h>

#include <pwb/job_runtime/job_categories.hpp>
#include <pwb/job_runtime/job_contract.hpp>
#include <pwb/job_runtime/resource_governor.hpp>

#include <algorithm>
#include <limits>
#include <chrono>
#include <cmath>
#include <mutex>
#include <stdexcept>
#include <thread>

namespace pwb::qgis_processing {

namespace {
// Property names carrying Paleo semantics on the QObject that QgsTask
// already is — consumed by the TaskCenter projection.
constexpr auto kPropKind = "pwb.kind";
constexpr auto kPropTaskKey = "pwb.task_key";
constexpr auto kPropRunId = "pwb.run_id";
constexpr auto kPropOutcome = "pwb.outcome";
}  // namespace

// ---------------------------------------------------------------------------
// PaleoTaskBodyContext
// ---------------------------------------------------------------------------

void PaleoTaskBodyContext::report_progress(double fraction, const QString& stage) {
    if (task_ != nullptr) task_->report_progress(fraction, stage);
}

bool PaleoTaskBodyContext::cancel_requested() const {
    return task_ == nullptr || task_->cancel_requested();
}

bool PaleoTaskBodyContext::sleep_interruptible(double seconds) const {
    return task_ != nullptr && task_->sleep_interruptible(seconds);
}

void PaleoTaskBodyContext::mark_degraded(QString caveat) {
    if (task_ != nullptr) task_->mark_degraded(std::move(caveat));
}

void PaleoTaskBodyContext::set_result(QVariant result) {
    if (task_ != nullptr) task_->set_result(std::move(result));
}

QgsTask* PaleoTaskBodyContext::task() const { return task_; }

// ---------------------------------------------------------------------------
// PaleoFunctionTask
// ---------------------------------------------------------------------------

PaleoFunctionTask::PaleoFunctionTask(QString kind, QString title, Body body,
                                     QgsTask::Flags flags)
    : QgsTask(std::move(title), flags),
      kind_(kind.isEmpty() ? QStringLiteral("background.io") : std::move(kind)),
      body_(std::move(body)) {
    setProperty(kPropKind, kind_);
}

PaleoFunctionTask::~PaleoFunctionTask() = default;

void PaleoFunctionTask::cancel() {
    // Base implementation arms isCanceled() and cancels subtasks — required
    // by the QgsTask contract for overriding subclasses.
    QgsTask::cancel();
}

bool PaleoFunctionTask::run() {
    std::unique_ptr<pwb::job::ResourceLease> lease;
    // Gate-lifetime guard: hold the gate via QPointer so a gate destroyed
    // while this task waits in admission deferral is observed (null) —
    // never dereferenced after free.
    const QPointer<PwbTaskGate> gate = gate_;
    if (gate != nullptr) {
        // Dequeue-time admission parity: the retired scheduler ran its
        // admission hook when a worker claimed a job; run() is that moment.
        try {
            lease = gate->acquire_admission(
                kind_, [&gate, this]() { return isCanceled() || gate.isNull(); });
        } catch (const PaleoTaskRejected& rejected) {
            error_text_ = rejected.message();
            setProperty("pwb.error", error_text_);
            set_property_outcome(QStringLiteral("failed"));
            return false;
        }
        // A null lease means either "cancelled while deferred" (governed
        // gate, or the gate itself vanished) or "no admission configured"
        // (governor-less gate admits everything — the header contract).
        // Only the cancelled case ends the task here; a governor-less gate
        // proceeds lease-free.
        if (lease == nullptr && (isCanceled() || gate.isNull())) {
            set_property_outcome(QStringLiteral("cancelled"));
            return false;
        }
    }

    PaleoTaskBodyContext context(*this);
    bool body_result = false;
    try {
        body_result = body_(context);
    } catch (const pwb::job::JobCancelled&) {
        // Kernel-safe-point cancellation (JobCancelled parity): the retired
        // scheduler translated this exception into a cancelled terminal
        // state, never a failure.
        set_property_outcome(QStringLiteral("cancelled"));
        return false;
    } catch (const std::exception& error) {
        error_text_ = QString::fromStdString(error.what());
        body_result = false;
    } catch (...) {
        error_text_ = QStringLiteral("unknown task body error");
        body_result = false;
    }
    if (!error_text_.isEmpty()) setProperty("pwb.error", error_text_);

    if (isCanceled()) {
        set_property_outcome(QStringLiteral("cancelled"));
        return false;
    }
    if (!body_result) {
        set_property_outcome(QStringLiteral("failed"));
        return false;
    }
    set_property_outcome(caveat_.isEmpty() ? QStringLiteral("completed")
                                           : QStringLiteral("degraded"));
    return true;
}

void PaleoFunctionTask::finished(bool result) {
    Q_UNUSED(result);
    // finished() runs on the main thread; outcome properties are already
    // set — this hook exists for subclass parity only.
}

void PaleoFunctionTask::report_progress(double fraction, const QString& stage) {
    const double clamped =
        std::clamp(fraction, std::numeric_limits<double>::lowest(), 1.0);
    setProgress(clamped < 0.0 ? 0.0 : 100.0 * clamped);
    if (!stage.isEmpty()) emit stage_changed(stage);
}

bool PaleoFunctionTask::cancel_requested() const {
    return const_cast<PaleoFunctionTask*>(this)->isCanceled();
}

bool PaleoFunctionTask::sleep_interruptible(double seconds) const {
    const auto deadline =
        std::chrono::steady_clock::now() + std::chrono::duration<double>(seconds);
    for (;;) {
        if (cancel_requested()) return false;
        const auto now = std::chrono::steady_clock::now();
        if (now >= deadline) return true;
        const auto until_deadline =
            std::chrono::duration_cast<std::chrono::milliseconds>(deadline - now);
        std::this_thread::sleep_for(
            std::min<std::chrono::milliseconds>(until_deadline,
                                                std::chrono::milliseconds(50)));
    }
}

void PaleoFunctionTask::mark_degraded(QString caveat) {
    caveat_ = std::move(caveat);
    emit outcome_degraded(caveat_);
}

void PaleoFunctionTask::set_result(QVariant result) { result_ = std::move(result); }

QVariant PaleoFunctionTask::take_result() { return result_; }

bool PaleoFunctionTask::degraded() const { return !caveat_.isEmpty(); }

QString PaleoFunctionTask::caveat() const { return caveat_; }

void PaleoFunctionTask::set_task_key(QString key) {
    setProperty(kPropTaskKey, key);
}

void PaleoFunctionTask::set_run_id(QString run_id) {
    setProperty(kPropRunId, std::move(run_id));
}

void PaleoFunctionTask::set_gate(PwbTaskGate* gate) { gate_ = gate; }

void PaleoFunctionTask::set_property_outcome(const QString& outcome) {
    setProperty(kPropOutcome, outcome);
}

// ---------------------------------------------------------------------------
// PwbTaskGate
// ---------------------------------------------------------------------------

PwbTaskGate::PwbTaskGate(QObject* parent) : QObject(parent) {}

PwbTaskGate::~PwbTaskGate() = default;

void PwbTaskGate::set_governor(pwb::job::ResourceGovernor* governor) {
    governor_ = governor;
}

long PwbTaskGate::submit(PaleoFunctionTask* task, QString task_key) {
    const pwb::job::JobCategory category =
        pwb::job::category_for_kind(task->kind().toStdString());
    const pwb::job::CategoryPolicy* policy = pwb::job::policy_for(category);
    const int priority = policy != nullptr ? policy->base_priority : 30;

    if (!task_key.isEmpty()) {
        task->set_task_key(task_key);
        const auto found = active_keys_.constFind(task_key);
        if (found != active_keys_.constEnd() && found.value().task != nullptr) {
            QgsTask* existing = found.value().task.data();
            const QgsTask::TaskStatus status = existing->status();
            if (status == QgsTask::Running) {
                throw PaleoTaskRejected(
                    kRejectDuplicateTaskKey,
                    QStringLiteral("任务正在运行：同 task_key 的任务不可重复提交 "
                                   "(%1)").arg(task_key));
            }
            if (status == QgsTask::Queued || status == QgsTask::OnHold) {
                existing->cancel();  // supersede (#1224)
            }
        }
        active_keys_.insert(task_key, ActiveKey{QPointer<QgsTask>(task)});
        // Terminal tasks release their key for reuse.
        connect(task, &QgsTask::statusChanged, this,
                [this, task_key](int status) {
                    if (status == static_cast<int>(QgsTask::Complete) ||
                        status == static_cast<int>(QgsTask::Terminated)) {
                        release_key(task_key);
                    }
                });
    }

    task->set_gate(this);
    QgsTaskManager* manager = QgsApplication::taskManager();
    return manager->addTask(task, priority);
}

std::unique_ptr<pwb::job::ResourceLease> PwbTaskGate::acquire_admission(
    const QString& kind, const std::function<bool()>& cancelled) {
    if (governor_ == nullptr) return std::unique_ptr<pwb::job::ResourceLease>();
    const pwb::job::TaskRequest request = pwb::job::TaskRequest::from_kind(
        kind.toStdString(), /*priority=*/{}, /*title=*/{});
    // Bounded deferral: retry at the scheduler's 200 ms poll cadence, but
    // cap the cumulative wait at kAdmissionTimeoutS. Past the cap the task
    // is rejected (resource.exhausted) instead of parking forever.
    //
    // KNOWN LIMITATION: a deferred task occupies its QgsTaskManager worker
    // thread while waiting (the manager has no re-queue hook we can use at
    // run()-time); the timeout bounds that occupancy but does not remove
    // it. A gate destroyed mid-deferral nulls the task's QPointer, the
    // cancelled callback observes it at the next 20 ms check, and the loop
    // exits reading the deferral as cancelled.
    constexpr int kAdmissionTimeoutS = 30;
    const auto overall_deadline = std::chrono::steady_clock::now() +
                                  std::chrono::seconds(kAdmissionTimeoutS);
    for (;;) {
        if (cancelled()) return std::unique_ptr<pwb::job::ResourceLease>();
        std::unique_ptr<pwb::job::ResourceLease> lease = governor_->try_admit(request);
        if (lease != nullptr) return lease;
        if (std::chrono::steady_clock::now() >= overall_deadline) {
            throw PaleoTaskRejected(
                "resource.exhausted",
                QStringLiteral("资源准入等待超过 %1 秒，任务被拒绝 "
                               "(resource.exhausted)")
                    .arg(kAdmissionTimeoutS));
        }
        // Defer, not error: retry with the scheduler's poll cadence until
        // resources free up, the task is cancelled or the cap is hit.
        deferred_count_.fetch_add(1, std::memory_order_relaxed);
        const auto slice_deadline = std::chrono::steady_clock::now() +
                                    std::chrono::milliseconds(200);
        while (std::chrono::steady_clock::now() < slice_deadline) {
            if (cancelled()) return std::unique_ptr<pwb::job::ResourceLease>();
            std::this_thread::sleep_for(std::chrono::milliseconds(20));
        }
    }
}

int PwbTaskGate::deferred_count() const {
    return deferred_count_.load(std::memory_order_relaxed);
}

void PwbTaskGate::release_key(const QString& key) {
    const auto found = active_keys_.constFind(key);
    if (found != active_keys_.constEnd() && found.value().task == nullptr) {
        active_keys_.erase(found);
    }
}

// ---------------------------------------------------------------------------
// PwbTaskOwner
// ---------------------------------------------------------------------------

PwbTaskOwner::PwbTaskOwner(QObject* parent) : QObject(parent) {}

PwbTaskOwner::~PwbTaskOwner() {
    // Window died mid-run: detach — cancel + let the manager keep the task
    // (DetachedJobKeeper parity without a second keeper, because the
    // manager already owns every task).
    released_->store(true);
    if (active_ != nullptr) active_->cancel();
}

void PwbTaskOwner::start(QString kind, QString title,
                         PaleoFunctionTask::Body body, Finished on_done,
                         Progress on_progress, QString task_key) {
    if (is_running()) {
        throw std::logic_error(
            "PwbTaskOwner::start while a task is running (single-flight)");
    }
    on_done_ = std::move(on_done);
    on_progress_ = std::move(on_progress);
    task_key_ = std::move(task_key);
    released_->store(false);

    PaleoFunctionTask* task =
        new PaleoFunctionTask(std::move(kind), std::move(title), std::move(body));
    active_ = task;

    // GUI-thread delivery: QgsTask emits from worker threads; connecting to
    // this owner (GUI) queues automatically. Released flags suppress
    // deliveries racing shutdown/destruction.
    std::shared_ptr<std::atomic<bool>> released = released_;
    connect(task, &QgsTask::progressChanged, this,
            [this, released](double progress) {
                if (released->load() || on_progress_ == nullptr) return;
                on_progress_(progress / 100.0, QString());
            });
    connect(task, &PaleoFunctionTask::stage_changed, this,
            [this, released](const QString& stage) {
                if (released->load() || on_progress_ == nullptr) return;
                on_progress_(-1.0, stage);
            });
    // Delivery deferral (P2-2): QgsTask::cancel() terminates a QUEUED task
    // synchronously on the caller's thread, so delivering on_done_ straight
    // from the signal would re-enter the user's callback inside cancel()'s
    // call stack. The terminal signal handler therefore only SNAPSHOTS the
    // outcome (the task is still alive at emission — QGIS deletes it via a
    // deferred delete posted from the earlier statusChanged emission) and
    // queues the callback through invokeMethod for a later event-loop round.
    connect(task, &QgsTask::taskCompleted, this, [this]() {
        queue_terminal_delivery(/*completed=*/true);
    });
    connect(task, &QgsTask::taskTerminated, this, [this]() {
        queue_terminal_delivery(/*completed=*/false);
    });

    PwbTaskGate* gate = shared_task_gate();
    if (gate != nullptr) {
        try {
            gate->submit(task, task_key_);
        } catch (...) {
            // Rejected (duplicate task_key, admission refusal, ...): the
            // manager never took ownership, so the task would leak and the
            // single-flight slot would stay stuck on a never-starting
            // task. Free both, then propagate.
            active_.clear();
            delete task;
            throw;
        }
    } else {
        QgsApplication::taskManager()->addTask(task);
    }
}

bool PwbTaskOwner::is_running() const {
    if (active_ == nullptr) return false;
    const QgsTask::TaskStatus status = active_->status();
    return status == QgsTask::Queued || status == QgsTask::OnHold ||
           status == QgsTask::Running;
}

void PwbTaskOwner::cancel() {
    if (active_ != nullptr) active_->cancel();
}

bool PwbTaskOwner::shutdown(int wait_ms) {
    released_->store(true);
    if (active_ == nullptr) {
        emit released();
        return true;
    }
    active_->cancel();
    // QGIS semantics: QgsTask::waitForFinished(0) treats 0 as INT_MAX
    // (wait forever), so wait_ms <= 0 must not call it at all — the
    // released flag already suppressed delivery and the manager adopts
    // the still-running task.
    bool finished_in_time = true;
    if (wait_ms > 0) {
        finished_in_time = active_->waitForFinished(wait_ms);
    } else {
        // No wait granted: report finished only when already terminal.
        const QgsTask::TaskStatus status = active_->status();
        finished_in_time = status == QgsTask::Complete ||
                           status == QgsTask::Terminated;
    }
    if (!finished_in_time) {
        // Timeout: the task keeps running under the manager (adoption,
        // baseline-JobOwner parity: handle_ = {} after detach). Free the
        // owner slot — queue_terminal_delivery already no-ops on a null
        // active_, so the late queued delivery is harmless.
        active_.clear();
    }
    emit released();
    return finished_in_time;
}

void PwbTaskOwner::queue_terminal_delivery(bool completed) {
    if (released_->load()) return;
    PaleoFunctionTask* task =
        qobject_cast<PaleoFunctionTask*>(active_.data());
    if (task == nullptr) return;  // late delivery after shutdown timeout

    // Snapshot everything the outcome needs while the task object is
    // guaranteed alive (we run inside the terminal signal emission, before
    // QGIS's deferred delete is processed).
    const QString stored = task->property("pwb.outcome").toString();
    const bool degraded = task->degraded();
    const QString caveat = task->caveat();
    const QVariant result = task->take_result();
    const QString error = task->property("pwb.error").toString();

    // Stale-delivery guard: between this signal and the queued lambda's
    // execution, is_running() is already false and start() may legally
    // replace the slot. Only deliver when the queued lambda still targets
    // THIS task — otherwise the new task's own terminal delivery would be
    // dropped by the clear() below.
    QPointer<QgsTask> expected = active_;
    QMetaObject::invokeMethod(
        this,
        [this, expected, completed, stored, degraded, caveat, result, error]() {
            if (released_->load()) return;
            if (active_ != expected) return;  // slot was recycled
            PaleoTaskOutcome outcome;
            if (stored == QLatin1String("cancelled")) {
                outcome.cancelled = true;
            } else if (completed) {
                outcome.completed = true;
                outcome.degraded = degraded;
                outcome.caveat = caveat;
                outcome.result = result;
            } else {
                outcome.failed = true;
                outcome.error = error;
            }
            // Terminal: free the single-flight slot BEFORE the callback
            // runs so a #1471-style reissue in the callback sees a free
            // owner.
            active_.clear();
            if (on_done_ != nullptr) on_done_(outcome);
        },
        Qt::QueuedConnection);
}

void PwbTaskOwner::on_task_state(int status) {
    Q_UNUSED(status);
}

void reissue_when_terminal(PwbTaskOwner& owner, QObject* context,
                           std::function<void()> fn) {
    if (context == nullptr) return;
    // #1471 parity: defer through GUI rounds until the owner's slot is
    // free, then run exactly once; a destroyed context drops the chain.
    QTimer::singleShot(0, context, [&owner, context, fn = std::move(fn)]() {
        if (owner.is_running()) {
            reissue_when_terminal(owner, context, std::move(fn));
            return;
        }
        fn();
    });
}

namespace {
PwbTaskGate* g_shared_gate = nullptr;
}

PwbTaskGate* shared_task_gate() { return g_shared_gate; }

void set_shared_task_gate(PwbTaskGate* gate) { g_shared_gate = gate; }

}  // namespace pwb::qgis_processing
