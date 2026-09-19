// job_runtime.cancel — cooperative cancellation contracts (Python
// test_task_scheduler.py parity): cancel-before-start never runs the job;
// cancel-while-running is cooperative and a normal return after the token
// was set lands cancelled with a partial result; the cancelling state is
// visible; cancel-during-cancel is accepted; progress reports clamp and a
// throwing progress observer never kills a job.

#include <atomic>
#include <condition_variable>
#include <mutex>
#include <string>
#include <thread>

#include "job_test.hpp"
#include "pwb/job_runtime/job_scheduler.hpp"

using pwb::job::JobContext;
using pwb::job::JobHandle;
using pwb::job::JobScheduler;
using pwb::job::JobSpec;
using pwb::job::JobState;

namespace {

class Gate {
public:
    void wait() {
        std::unique_lock<std::mutex> lock(mutex_);
        cv_.wait(lock, [this] { return open_; });
    }
    void open() {
        std::lock_guard<std::mutex> guard(mutex_);
        open_ = true;
        cv_.notify_all();
    }

private:
    std::mutex mutex_;
    std::condition_variable cv_;
    bool open_ = false;
};

}  // namespace

TEST(cancel_queued_job_never_runs) {
    JobScheduler scheduler({.max_workers = 1});
    Gate gate;
    JobSpec blocker;
    blocker.run = [&gate](JobContext&) -> std::any {
        gate.wait();
        return {};
    };
    (void)scheduler.submit(std::move(blocker));

    std::atomic<bool> ran{false};
    std::atomic<bool> cancel_cb{false};
    JobSpec victim;
    victim.run = [&ran](JobContext&) -> std::any {
        ran = true;
        return {};
    };
    victim.on_cancel = [&cancel_cb]() { cancel_cb = true; };
    JobHandle handle = scheduler.submit(std::move(victim));
    PWB_CHECK(scheduler.cancel(handle.job_id()));
    // Second cancel on a terminal job reports false.
    PWB_CHECK(!scheduler.cancel(handle.job_id()));
    PWB_CHECK(handle.snapshot().state == JobState::cancelled);
    PWB_CHECK(handle.snapshot().cancel_requested);
    gate.open();
    scheduler.wait_idle();
    PWB_CHECK(!ran.load());
    PWB_CHECK(cancel_cb.load());
}

TEST(cancel_running_job_is_cooperative_and_keeps_partial) {
    JobScheduler scheduler({.max_workers = 1});
    Gate started;
    std::atomic<bool> cancel_cb{false};
    JobSpec spec;
    spec.run = [&started](JobContext& ctx) -> std::any {
        started.open();
        // Cooperative loop: sees the token at the next safe point and
        // returns a partial result.
        for (int i = 0; i < 200; ++i) {
            if (ctx.token().is_cancelled()) return 42;  // partial
            ctx.sleep_interruptible(0.005);
        }
        return -1;
    };
    spec.on_cancel = [&cancel_cb]() { cancel_cb = true; };
    JobHandle handle = scheduler.submit(std::move(spec));
    started.wait();
    PWB_CHECK(handle.snapshot().state == JobState::running);
    PWB_CHECK(scheduler.cancel(handle.job_id()));
    // cancelling is the request-visible state; a job that observes the
    // token at its very next safe point may already be terminal-cancelled.
    const JobState after_cancel = handle.snapshot().state;
    PWB_CHECK(after_cancel == JobState::cancelling ||
              after_cancel == JobState::cancelled);
    handle.wait();
    const pwb::job::JobSnapshot snap = handle.snapshot();
    PWB_CHECK(snap.state == JobState::cancelled);
    PWB_CHECK(cancel_cb.load());
    const int* partial = handle.try_result<int>();
    PWB_CHECK(partial != nullptr && *partial == 42);
    // Idempotent: cancel-during-cancel / after terminal is accepted-noop or
    // false, never a failure.
    PWB_CHECK(!handle.cancel());
}

TEST(double_cancel_while_running_is_accepted) {
    JobScheduler scheduler({.max_workers = 1});
    Gate started;
    Gate release;
    JobSpec spec;
    spec.run = [&started, &release](JobContext& ctx) -> std::any {
        started.open();
        ctx.sleep_interruptible(0.5);
        release.wait();
        return {};
    };
    JobHandle handle = scheduler.submit(std::move(spec));
    started.wait();
    PWB_CHECK(handle.cancel());
    PWB_CHECK(handle.cancel());  // R3-F8: cancel-during-cancel accepted
    release.open();
    handle.wait();
    PWB_CHECK(handle.snapshot().state == JobState::cancelled);
}

TEST(progress_reports_clamp_and_survive_bad_observers) {
    JobScheduler scheduler({.max_workers = 1});
    std::atomic<bool> saw_over_one{false};
    JobSpec spec;
    spec.on_progress = [&saw_over_one](double ratio, const std::string&) {
        if (ratio > 1.0) saw_over_one = true;
        throw std::runtime_error("bad observer");  // must never kill a task
    };
    spec.run = [](JobContext& ctx) -> std::any {
        ctx.report_progress(7, 4, "over");   // clamps to 1.0
        ctx.report_progress(-3, 0, "under");  // total=0 → ratio=done → clamp 0
        return "ok";
    };
    JobHandle handle = scheduler.submit(std::move(spec));
    handle.wait();
    PWB_CHECK(!saw_over_one.load());
    PWB_CHECK(handle.snapshot().state == JobState::done);
    PWB_CHECK(handle.snapshot().progress == 1.0);
}

TEST(check_cancelled_raises_and_maps_to_cancelled_state) {
    JobScheduler scheduler({.max_workers = 1});
    Gate started;
    JobSpec spec;
    spec.run = [&started](JobContext& ctx) -> std::any {
        started.open();
        for (int i = 0; i < 200; ++i) {
            ctx.check_cancelled();  // raises JobCancelled at the safe point
            ctx.sleep_interruptible(0.005);
        }
        return {};
    };
    JobHandle handle = scheduler.submit(std::move(spec));
    started.wait();
    scheduler.cancel(handle.job_id());
    handle.wait();
    PWB_CHECK(handle.snapshot().state == JobState::cancelled);
    PWB_CHECK(handle.try_result<int>() == nullptr);
}

int main() { return pwb_test_main(); }
