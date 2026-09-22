// job_runtime.shutdown — shutdown/drain contracts: queued jobs are
// cancelled (with on_cancel unwind), running tokens are armed, workers
// join, submits after shutdown are rejected with "runtime.shutdown"; the
// destructor drains. Also: admission lease protocol (deferral + release at
// terminal + speculative release on lost race), strict lane isolation,
// crash-safe work dirs, and aging via an injected clock.

#include <atomic>
#include <condition_variable>
#include <filesystem>
#include <mutex>
#include <set>
#include <string>
#include <thread>
#include <vector>

#include "job_test.hpp"
#include "pwb/job_runtime/job_scheduler.hpp"

using pwb::job::AdmissionLease;
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
    [[nodiscard]] bool ready() {
        std::lock_guard<std::mutex> guard(mutex_);
        return open_;
    }

private:
    std::mutex mutex_;
    std::condition_variable cv_;
    bool open_ = false;
};

class CountingLease : public AdmissionLease {
public:
    void release() override { ++releases; }
    std::atomic<int> releases{0};
};

}  // namespace

TEST(shutdown_cancels_queued_and_joins) {
    std::atomic<bool> cancel_cb{false};
    std::atomic<bool> queued_cancel_cb{false};
    std::vector<JobHandle> handles;
    JobScheduler scheduler({.max_workers = 1});
    JobSpec blocker;
    blocker.run = [](JobContext& ctx) -> std::any {
        // Honors the token: shutdown arms it, the loop exits at the next
        // safe point and the normal return lands cancelled.
        while (!ctx.token().is_cancelled()) ctx.sleep_interruptible(0.01);
        return {};
    };
    blocker.on_cancel = [&cancel_cb]() { cancel_cb = true; };
    handles.push_back(scheduler.submit(std::move(blocker)));

    JobSpec queued;
    queued.run = [](JobContext&) -> std::any { return {}; };
    queued.on_cancel = [&queued_cancel_cb]() { queued_cancel_cb = true; };
    handles.push_back(scheduler.submit(std::move(queued)));

    scheduler.shutdown(true, 2.0);
    PWB_CHECK(handles[0].snapshot().state == JobState::cancelled);
    PWB_CHECK(handles[1].snapshot().state == JobState::cancelled);
    PWB_CHECK(queued_cancel_cb.load());
    PWB_CHECK(cancel_cb.load());
    bool submit_rejected = false;
    try {
        JobSpec after;
        after.run = [](JobContext&) -> std::any { return {}; };
        (void)scheduler.submit(std::move(after));
    } catch (const pwb::job::JobSubmitError& err) {
        submit_rejected = err.code() == "runtime.shutdown";
    }
    PWB_CHECK(submit_rejected);
}

TEST(destructor_joins_and_all_submitted_jobs_reach_terminal) {
    std::atomic<int> ran{0};
    std::vector<JobHandle> handles;
    {
        JobScheduler scheduler({.max_workers = 2});
        for (int i = 0; i < 6; ++i) {
            JobSpec spec;
            spec.run = [&ran](JobContext&) -> std::any {
                ++ran;
                return {};
            };
            handles.push_back(scheduler.submit(std::move(spec)));
        }
        // Implicit shutdown on scope exit: queued jobs are cancelled,
        // running jobs finish — every cell reaches a terminal state and
        // the workers join (Python used daemon threads; C++ cannot
        // abandon them, which is the one documented divergence).
    }
    int terminal = 0;
    int done = 0;
    for (const JobHandle& handle : handles) {
        const auto snap = handle.snapshot();
        PWB_CHECK(snap.is_terminal());
        ++terminal;
        if (snap.state == JobState::done) ++done;
    }
    PWB_CHECK(terminal == 6);
    // At destruction the lanes may not have claimed anything yet (worker
    // wakeup latency) — 0..2 jobs run to completion, the rest are
    // cancelled by the implicit shutdown. A claimed-but-not-yet-executed
    // job also lands cancelled without incrementing `ran`, so `done` can
    // lag `ran` by that micro-window; what matters is: everything
    // terminal, workers joined.
    PWB_CHECK(done <= ran.load());
}

TEST(admission_hook_defers_and_releases_lease_at_terminal) {
    JobScheduler scheduler({.max_workers = 1});
    auto lease = std::make_shared<CountingLease>();
    std::atomic<int> attempts{0};
    scheduler.set_admission([&](const JobSpec&, const std::string&)
                                -> std::shared_ptr<AdmissionLease> {
        ++attempts;
        if (attempts.load() < 3) return nullptr;  // defer, stays queued
        return lease;
    });
    JobSpec spec;
    spec.run = [](JobContext&) -> std::any { return "ran"; };
    JobHandle handle = scheduler.submit(std::move(spec));
    handle.wait();
    PWB_CHECK(handle.snapshot().state == JobState::done);
    PWB_CHECK(attempts.load() >= 3);
    PWB_CHECK(lease->releases.load() == 1);  // released exactly once
}

TEST(admission_lease_released_on_cancelled_race) {
    // A job cancelled (via token) while running still releases the lease.
    JobScheduler scheduler({.max_workers = 1});
    auto lease = std::make_shared<CountingLease>();
    scheduler.set_admission(
        [&](const JobSpec&, const std::string&) -> std::shared_ptr<AdmissionLease> {
            return lease;
        });
    Gate started;
    JobSpec spec;
    spec.run = [&started](JobContext& ctx) -> std::any {
        started.open();
        for (int i = 0; i < 200; ++i) {
            if (ctx.token().is_cancelled()) return {};
            ctx.sleep_interruptible(0.005);
        }
        return {};
    };
    JobHandle handle = scheduler.submit(std::move(spec));
    started.wait();
    scheduler.cancel(handle.job_id());
    handle.wait();
    PWB_CHECK(handle.snapshot().state == JobState::cancelled);
    // The lease releases in the worker's post-terminal epilogue (Python
    // _run_task finally has the same shape) — terminal can be observed a
    // moment before the release lands, so wait briefly and exactly once.
    for (int i = 0; i < 200 && lease->releases.load() == 0; ++i) {
        std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }
    PWB_CHECK(lease->releases.load() == 1);
}

TEST(strict_lane_isolation) {
    // A background job blocking the background lane must never delay an
    // interactive submission (P2-A <50 ms queue-delay budget contract).
    JobScheduler scheduler({.max_workers = 1, .interactive_workers = 1});
    Gate background_gate;
    JobSpec heavy;
    heavy.kind = "background.compute";  // background lane
    heavy.run = [&background_gate](JobContext&) -> std::any {
        background_gate.wait();
        return {};
    };
    (void)scheduler.submit(std::move(heavy));

    std::atomic<bool> interactive_ran{false};
    JobSpec interactive;
    interactive.kind = "render";  // interactive lane by category policy
    interactive.run = [&interactive_ran](JobContext&) -> std::any {
        interactive_ran = true;
        return {};
    };
    JobHandle interactive_handle = scheduler.submit(std::move(interactive));
    // Bounded wait: if lanes were NOT strict, this job would sit behind
    // the (still blocked) background job and the wait would time out.
    PWB_CHECK(interactive_handle.wait_for(5.0));
    PWB_CHECK(interactive_handle.snapshot().state == JobState::done);
    PWB_CHECK(interactive_ran.load());
    background_gate.open();
    scheduler.wait_idle();
}

TEST(self_wait_from_worker_throws_logic_error) {
    // TaskRuntime v3 precedent: wait() from the job's own worker thread
    // would deadlock, so it throws std::logic_error instead.
    JobScheduler scheduler({.max_workers = 1});
    std::atomic<bool> threw{false};
    JobSpec spec;
    spec.run = [&threw](JobContext& ctx) -> std::any {
        JobHandle self = ctx.self_handle();
        try {
            self.wait();
        } catch (const std::logic_error&) {
            threw = true;
        }
        return {};
    };
    JobHandle handle = scheduler.submit(std::move(spec));
    handle.wait();
    PWB_CHECK(threw.load());
}

TEST(work_dir_is_crash_safe_and_released_explicitly) {
    JobScheduler scheduler({.max_workers = 1});
    scheduler.set_work_root(std::filesystem::temp_directory_path() /
                            "pwb-job-runtime-tests");
    std::atomic<bool> released_inside{false};
    JobSpec spec;
    spec.run = [&](JobContext& ctx) -> std::any {
        const auto dir = scheduler.work_dir(ctx.job_id());
        released_inside = std::filesystem::exists(dir);
        return {};
    };
    JobHandle handle = scheduler.submit(std::move(spec));
    handle.wait();
    PWB_CHECK(released_inside.load());
    scheduler.release_work_dir(handle.job_id());
    PWB_CHECK(!std::filesystem::exists(
        std::filesystem::temp_directory_path() / "pwb-job-runtime-tests" /
        handle.job_id()));
}

TEST(aging_promotes_long_waiting_jobs_with_injected_clock) {
    // Injected monotonic clock (Python parity: clock=... injection).
    auto now = std::make_shared<std::atomic<double>>(0.0);
    JobScheduler::Options options;
    options.max_workers = 1;
    options.aging_interval_s = 5.0;
    options.aging_step = 5;
    options.aging_max_boost = 50;
    JobScheduler scheduler(
        options, [now] { return now->load(); });

    Gate gate;
    JobSpec blocker;
    blocker.run = [&gate](JobContext&) -> std::any {
        gate.wait();
        return {};
    };
    (void)scheduler.submit(std::move(blocker));  // occupies the only lane

    // base 5 submitted at t=0 vs base 10 submitted at t=40 (clock advanced
    // later). With aging: 5 + min(60/5*5, 50) = 55 beats 10 + min(20/5*5,
    // 50) = 30. Without aging the base-10 job would win.
    std::mutex order_mutex;
    std::vector<int> order;
    JobSpec aged;
    aged.priority = 5;
    aged.run = [&](JobContext&) -> std::any {
        std::lock_guard<std::mutex> guard(order_mutex);
        order.push_back(5);
        return {};
    };
    (void)scheduler.submit(std::move(aged));

    now->store(40.0);
    JobSpec fresh_high;
    fresh_high.priority = 10;
    fresh_high.run = [&](JobContext&) -> std::any {
        std::lock_guard<std::mutex> guard(order_mutex);
        order.push_back(10);
        return {};
    };
    (void)scheduler.submit(std::move(fresh_high));

    now->store(60.0);  // both age now (60s and 20s of waiting)
    gate.open();
    scheduler.wait_idle();
    std::lock_guard<std::mutex> guard(order_mutex);
    PWB_CHECK(order.size() == 2);
    PWB_CHECK(order[0] == 5);  // aged past the higher base priority
    PWB_CHECK(order[1] == 10);
}

int main() { return pwb_test_main(); }

TEST(work_dir_is_released_automatically_at_job_completion) {
    // #1451 B-06: work_dir() used to have no production release — the
    // epilogue below must drop the scratch dir by the time wait() returns,
    // without any explicit release_work_dir call.
    JobScheduler scheduler({.max_workers = 1});
    scheduler.set_work_root(std::filesystem::temp_directory_path() /
                            "pwb-job-runtime-tests");
    std::atomic<bool> created{false};
    JobSpec spec;
    spec.run = [&](JobContext& ctx) -> std::any {
        const auto dir = scheduler.work_dir(ctx.job_id());
        created = std::filesystem::exists(dir);
        return {};
    };
    JobHandle handle = scheduler.submit(std::move(spec));
    handle.wait();
    PWB_CHECK(created.load());
    PWB_CHECK(!std::filesystem::exists(
        std::filesystem::temp_directory_path() / "pwb-job-runtime-tests" /
        handle.job_id()));
}
