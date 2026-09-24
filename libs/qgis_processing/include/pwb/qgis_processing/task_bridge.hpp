#pragma once

// QgsTaskManager bridge: the Paleo product's background execution layer.
//
// Replaces the retired JobScheduler/JobOwner/WorkerHost stack:
//   * PaleoFunctionTask — generic body runner (progress via setProgress,
//     cooperative cancel via isCanceled(), admission via the retained
//     governance stack when a PwbTaskGate is attached);
//   * PwbTaskGate — thin Paleo policy QGIS does not have: resource
//     admission (governor leases), task_key dedupe/supersede (#1224
//     parity) and kind tagging;
//   * PwbTaskOwner — GUI ownership slot (JobOwner parity: single-flight,
//     released-flag delivery suppression, bounded shutdown; adoption is
//     free because QgsTaskManager owns every task);
//   * reissue_when_terminal — #1471 parity on the new owner.
//
// Provenance: attach a run id via set_run_id(); it is a projection column
// only — the catalog rail records provenance after completion.

#include <atomic>
#include <functional>
#include <memory>

#include <QObject>
#include <QPointer>
#include <QString>
#include <QVariant>

#include <qgstaskmanager.h>

namespace pwb::job {
struct TaskRequest;
class ResourceLease;
class ResourceGovernor;
}  // namespace pwb::job

namespace pwb::qgis_processing {

// ---------------------------------------------------------------------------
// PaleoFunctionTask
// ---------------------------------------------------------------------------

class PaleoFunctionTask;

// What a body sees. Thread of execution: the task's worker thread. All
// calls are safe from any thread; GUI delivery happens via the task's
// signals (queued) or finished() on the main thread — never from here.
class PaleoTaskBodyContext {
public:
    explicit PaleoTaskBodyContext(PaleoFunctionTask& task) : task_(&task) {}

    // fraction in [0,1]; optional stage label (projection text).
    void report_progress(double fraction, const QString& stage = QString());
    [[nodiscard]] bool cancel_requested() const;
    // Cooperative cancellation check — returns false when cancelled.
    [[nodiscard]] bool check_cancelled() const { return !cancel_requested(); }
    // Interruptible sleep: wakes early on cancel; returns false when
    // cancelled (parity with JobContext::sleep_interruptible).
    [[nodiscard]] bool sleep_interruptible(double seconds) const;
    // Marks the outcome as success-with-caveat (JobState::degraded parity).
    void mark_degraded(QString caveat);
    // Arbitrary copyable payload delivered with the outcome.
    void set_result(QVariant result);
    [[nodiscard]] QgsTask* task() const;

private:
    PaleoFunctionTask* task_;
};

class PaleoFunctionTask final : public QgsTask {
    Q_OBJECT
public:
    using Body = std::function<bool(PaleoTaskBodyContext& ctx)>;

    // `kind` follows the job_categories vocabulary (e.g.
    // "seismic.attribute", "export") and drives gate policy; empty kind
    // falls back to "background.io".
    PaleoFunctionTask(QString kind, QString title, Body body,
                      QgsTask::Flags flags = QgsTask::CanCancel);
    ~PaleoFunctionTask() override;

    void cancel() override;

    // --- body API (also used by the owner/gate) ---------------------------
    void report_progress(double fraction, const QString& stage = QString());
    [[nodiscard]] bool cancel_requested() const;
    [[nodiscard]] bool sleep_interruptible(double seconds) const;
    void mark_degraded(QString caveat);
    void set_result(QVariant result);
    [[nodiscard]] QVariant take_result();
    [[nodiscard]] bool degraded() const;
    [[nodiscard]] QString caveat() const;

    // --- projection tags ----------------------------------------------------
    void set_task_key(QString key);
    void set_run_id(QString run_id);
    [[nodiscard]] QString kind() const { return kind_; }
    [[nodiscard]] QString error_text() const { return error_text_; }

signals:
    // Progress text for the task center projection (progress itself flows
    // through QgsTask::progressChanged).
    void stage_changed(const QString& stage);
    void outcome_degraded(const QString& caveat);

protected:
    bool run() override;
    void finished(bool result) override;

private:
    friend class PaleoTaskBodyContext;
    friend class PwbTaskGate;
    void set_gate(class PwbTaskGate* gate);
    void set_property_outcome(const QString& outcome);

    QString kind_;
    Body body_;
    QVariant result_;
    QString caveat_;
    QString error_text_;
    // Not owned. QPointer-guarded: a gate destroyed while this task sits in
    // admission deferral nulls the pointer instead of leaving a dangling
    // one (run() treats a vanished gate as cancelled).
    QPointer<PwbTaskGate> gate_;
};

// ---------------------------------------------------------------------------
// PwbTaskGate — admission + dedupe/supersede (thin Paleo policy)
// ---------------------------------------------------------------------------

// Stable rejection codes (JobSubmitError parity).
inline constexpr auto kRejectDuplicateTaskKey = "duplicate.task_key";

class PaleoTaskRejected : public std::runtime_error {
public:
    PaleoTaskRejected(std::string code, QString message)
        : std::runtime_error(code), code_(std::move(code)), message_(std::move(message)) {}
    [[nodiscard]] const std::string& code() const { return code_; }
    [[nodiscard]] const QString& message() const { return message_; }

private:
    std::string code_;
    QString message_;
};

class PwbTaskGate : public QObject {
    Q_OBJECT
public:
    // `governor` may be null (no resource admission — tests); the product
    // installs the global governance governor.
    explicit PwbTaskGate(QObject* parent = nullptr);
    ~PwbTaskGate() override;

    void set_governor(pwb::job::ResourceGovernor* governor);

    // Tags the task (kind/task_key/run-id properties) and hands it to the
    // manager. Admission happens inside the task body (worker thread),
    // mirroring the retired scheduler's dequeue-time admission hook.
    // Throws PaleoTaskRejected(kRejectDuplicateTaskKey) when `task_key`
    // matches a RUNNING task; a QUEUED task with the same key is
    // superseded (cancelled) first — #1224 parity.
    long submit(PaleoFunctionTask* task, QString task_key = QString());

    // Admission lease acquisition used by PaleoFunctionTask::run. Returns
    // nullptr when the task was cancelled while waiting. Throws
    // PaleoTaskRejected("resource.exhausted") when the governor denies
    // non-retryably.
    [[nodiscard]] std::unique_ptr<pwb::job::ResourceLease> acquire_admission(
        const QString& kind, const std::function<bool()>& cancelled);

    [[nodiscard]] int deferred_count() const;

private:
    struct ActiveKey {
        QPointer<QgsTask> task;
    };
    void release_key(const QString& key);

    pwb::job::ResourceGovernor* governor_ = nullptr;  // not owned
    QHash<QString, ActiveKey> active_keys_;
    std::atomic<int> deferred_count_{0};
};

// ---------------------------------------------------------------------------
// PwbTaskOwner — GUI ownership slot (JobOwner parity)
// ---------------------------------------------------------------------------

struct PaleoTaskOutcome {
    bool completed = false;   // body returned true
    bool degraded = false;    // completed with caveat
    bool failed = false;      // body returned false or threw
    bool cancelled = false;   // task cancelled (partial results dropped)
    QString error;            // failure detail
    QString caveat;           // degraded detail
    QVariant result;          // copyable payload from ctx.set_result
};

class PwbTaskOwner : public QObject {
    Q_OBJECT
public:
    using Finished = std::function<void(const PaleoTaskOutcome& outcome)>;
    using Progress = std::function<void(double fraction, const QString& stage)>;

    explicit PwbTaskOwner(QObject* parent = nullptr);
    ~PwbTaskOwner() override;

    // Single-flight like JobOwner::start: throws std::logic_error when a
    // task is already running. The body runs on a QgsTaskManager thread;
    // `on_done`/`on_progress` are invoked on this owner's thread (GUI).
    void start(QString kind, QString title,
               PaleoFunctionTask::Body body, Finished on_done,
               Progress on_progress = nullptr, QString task_key = QString());

    [[nodiscard]] bool is_running() const;
    void cancel();
    // Window-close protocol: suppresses late deliveries, cancels, bounded
    // wait; the task keeps running under the manager (adoption is inherent
    // to QgsTaskManager ownership). Emit-safety for ~QObject is preserved.
    // wait_ms <= 0 skips the wait entirely (QGIS would read a 0 timeout as
    // "wait forever"); the slot is released either way once the wait ends.
    bool shutdown(int wait_ms = 3000);

signals:
    void released();

private:
    void on_task_state(int status);
    // Terminal-signal handler: snapshots the task outcome at emission time
    // (the task is alive then — QGIS deletes it via a deferred delete
    // posted from the earlier statusChanged emission) and queues the
    // user callback for a later event-loop round, so cancel() of a QUEUED
    // task never re-enters on_done_ synchronously.
    void queue_terminal_delivery(bool completed);

    QPointer<QgsTask> active_;
    std::shared_ptr<std::atomic<bool>> released_ =
        std::make_shared<std::atomic<bool>>(false);
    Finished on_done_;
    Progress on_progress_;
    QString task_key_;
};

// #1471 parity: run `fn` on `context`'s thread once `owner` reached a
// terminal state; defers through GUI rounds while the owner is still busy.
void reissue_when_terminal(PwbTaskOwner& owner, QObject* context,
                           std::function<void()> fn);

// Process-wide convenience: the product's shared gate (JobCenter installs
// it; tests may replace it). May be null in non-product hosts.
PwbTaskGate* shared_task_gate();
void set_shared_task_gate(PwbTaskGate* gate);

}  // namespace pwb::qgis_processing
