#pragma once

// UI-14 — UI-side job runner seam (OwnedWorkerJob parity).
//
// The controller cores build pwb::job::JobSpec values (worker callable +
// worker-thread on_done/on_fail/on_cancel bookkeeping) and hand them to a
// runner that guarantees the *finished* observer lands back on the owner
// (GUI) thread — exactly the result_connections semantics of
// OwnedWorkerJob.start. The Qt binding lives in
// pwb_ui_controllers_qt (JobOwnerRunner over job::qtbridge::JobOwner);
// InlineJobRunner below executes synchronously for tests and Qt-free
// hosts.
//
// `target` mirrors OwnedWorkerJob.target: the object the job is bound to
// (the live project document for save/prepare/verify jobs). Completion
// slots compare `runner.target() != live` to drop stale results — the
// #937-10 stale-completion guard.

#include <any>
#include <functional>

#include <pwb/job_runtime/job_contract.hpp>
#include <pwb/job_runtime/job_scheduler.hpp>

namespace pwb::ui_controllers {

// Deterministic terminal outcome (qtbridge::JobOutcome vocabulary — kept
// local so the Qt-free core never includes the Qt bridge header).
struct UiJobOutcome {
    job::JobState state = job::JobState::cancelled;  // done/degraded/failed/cancelled
    std::string error;                               // failed only
    std::any result;                                 // done/degraded/cancelled(partial)

    template <typename T>
    const T* try_result() const {
        return std::any_cast<T>(&result);
    }
};

using UiJobFinishedFn = std::function<void(const UiJobOutcome&)>;

class UiJobRunner {
public:
    virtual ~UiJobRunner() = default;

    virtual bool is_running() const = 0;

    // OwnedWorkerJob.target — the object a completion must still match.
    virtual const void* target() const = 0;
    virtual void set_target(const void* target) = 0;

    // Submits the spec; on_finished fires on the owner thread with the
    // terminal outcome (dropped after shutdown/destruction, JobOwner
    // parity). on_progress hops ctx.report_progress calls to the owner
    // thread (JobOwner::ProgressFn parity). Returns the live handle for
    // waits/drain-side result reads.
    virtual job::JobHandle start(
        job::JobSpec spec, UiJobFinishedFn on_finished,
        std::function<void(double, const std::string&)> on_progress =
            nullptr) = 0;

    virtual void cancel() = 0;

    // Cancel + bounded wait. Returns false when the job refused to stop
    // (adopted by the detached keeper on the Qt side).
    virtual bool shutdown(int wait_ms) = 0;
};

// Inline runner: executes the callable synchronously and delivers the
// outcome in-line (the same thread). Deterministic — tests drive the
// whole orchestration without a scheduler or an event loop. Cancel +
// shutdown semantics match a cooperative worker: shutdown() joins the
// (already synchronous) run, so it always reports success.
class InlineJobRunner final : public UiJobRunner {
public:
    bool is_running() const override { return running_; }
    const void* target() const override { return target_; }
    void set_target(const void* target) override { target_ = target; }

    job::JobHandle start(
        job::JobSpec spec, UiJobFinishedFn on_finished,
        std::function<void(double, const std::string&)> on_progress =
            nullptr) override {
        running_ = true;
        (void)on_progress;  // JobContext's progress sink is scheduler-owned;
                            // the inline path cannot observe reports.
        UiJobOutcome outcome;
        try {
            job::CancellationToken token;
            job::JobContext ctx("inline-job", token);
            ctx.check_cancelled();
            std::any result = spec.run(ctx);
            outcome.result = result;
            try {
                ctx.check_cancelled();
                outcome.state =
                    (spec.degraded_when && spec.degraded_when(result))
                        ? job::JobState::degraded
                        : job::JobState::done;
            } catch (const job::JobCancelled&) {
                outcome.state = job::JobState::cancelled;
            }
        } catch (const std::exception& exc) {
            outcome.state = job::JobState::failed;
            outcome.error = exc.what();
        }
        if (outcome.state == job::JobState::done ||
            outcome.state == job::JobState::degraded) {
            if (spec.on_done) spec.on_done(outcome.result);
        } else if (outcome.state == job::JobState::failed) {
            if (spec.on_fail) spec.on_fail(outcome.error);
        } else {
            if (spec.on_cancel) spec.on_cancel();
        }
        running_ = false;
        if (on_finished) on_finished(outcome);
        return {};
    }

    void cancel() override {}
    bool shutdown(int /*wait_ms*/) override { return true; }

private:
    bool running_ = false;
    const void* target_ = nullptr;
};

}  // namespace pwb::ui_controllers
