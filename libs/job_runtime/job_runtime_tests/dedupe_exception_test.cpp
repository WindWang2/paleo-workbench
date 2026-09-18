// job_runtime.dedupe — task_key contracts (#1224 / Python parity): a
// queued key resubmission SUPERSEDES the old job (cancelled + on_cancel
// unwind), a running/cancelling key resubmission is rejected with the
// Python message; exceptions map to failed (never killed-by-crash) and the
// degraded predicate finishes degraded, never plain done.

#include <atomic>
#include <condition_variable>
#include <mutex>
#include <optional>
#include <string>

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

TEST(duplicate_key_rejected_while_active) {
    JobScheduler scheduler({.max_workers = 1});
    Gate started;
    Gate release;
    JobSpec first;
    first.task_key = "transcode/version-1";
    first.run = [&started, &release](JobContext&) -> std::any {
        started.open();
        release.wait();
        return {};
    };
    (void)scheduler.submit(std::move(first));
    started.wait();

    bool rejected = false;
    try {
        JobSpec dup;
        dup.task_key = "transcode/version-1";
        dup.run = [](JobContext&) -> std::any { return {}; };
        (void)scheduler.submit(std::move(dup));
    } catch (const pwb::job::JobSubmitError& err) {
        rejected = true;
        PWB_CHECK(err.code() == "duplicate.task_key");
        // Python wording verbatim, key prefix included (running case).
        PWB_CHECK(std::string(err.what()) ==
                  "task with key 'transcode/version-1' "
                  "正在运行且尚未退出（已请求取消的旧任务需先实际结束）");
    }
    PWB_CHECK(rejected);
    release.open();
    scheduler.wait_idle();

    // After completion the key is free again (re-run skips finished work
    // by implementation convention, the scheduler only guards active keys).
    JobSpec again;
    again.task_key = "transcode/version-1";
    again.run = [](JobContext&) -> std::any { return {}; };
    JobHandle again_handle = scheduler.submit(std::move(again));
    again_handle.wait();
    PWB_CHECK(again_handle.snapshot().state == JobState::done);
}

TEST(resubmit_against_queued_supersedes_it) {
    JobScheduler scheduler({.max_workers = 1});
    Gate gate;
    JobSpec blocker;
    blocker.run = [&gate](JobContext&) -> std::any {
        gate.wait();
        return {};
    };
    (void)scheduler.submit(std::move(blocker));

    std::atomic<bool> old_ran{false};
    std::atomic<bool> old_cancel_cb{false};
    JobSpec old_job;
    old_job.task_key = "attribute/version-1";
    old_job.run = [&old_ran](JobContext&) -> std::any {
        old_ran = true;
        return {};
    };
    old_job.on_cancel = [&old_cancel_cb]() { old_cancel_cb = true; };
    JobHandle old_handle = scheduler.submit(std::move(old_job));

    // #1224: the resubmit must succeed (replacing the queued job), never
    // make the next request hang.
    JobSpec new_job;
    new_job.task_key = "attribute/version-1";
    new_job.run = [](JobContext&) -> std::any { return "new"; };
    JobHandle new_handle = scheduler.submit(std::move(new_job));

    PWB_CHECK(old_handle.snapshot().state == JobState::cancelled);
    PWB_CHECK(old_cancel_cb.load());   // superseded unwinds like a cancel
    PWB_CHECK(!old_ran.load());
    PWB_CHECK(new_handle.snapshot().state == JobState::queued);

    gate.open();
    new_handle.wait();
    PWB_CHECK(new_handle.snapshot().state == JobState::done);
    PWB_CHECK(!old_ran.load());
}

TEST(exception_maps_to_failed) {
    JobScheduler scheduler({.max_workers = 1});
    std::atomic<bool> on_fail_called{false};
    std::atomic<bool> on_fail_saw_error{false};
    JobSpec spec;
    spec.run = [](JobContext&) -> std::any {
        throw std::runtime_error("transcode shard 3 exploded");
    };
    spec.on_fail = [&](const std::string& error) {
        on_fail_called = true;
        on_fail_saw_error =
            error.find("transcode shard 3 exploded") != std::string::npos;
    };
    JobHandle handle = scheduler.submit(std::move(spec));
    handle.wait();
    const pwb::job::JobSnapshot snap = handle.snapshot();
    PWB_CHECK(snap.state == JobState::failed);
    PWB_CHECK(snap.error.find("transcode shard 3 exploded") != std::string::npos);
    PWB_CHECK(on_fail_called.load());
    PWB_CHECK(on_fail_saw_error.load());
    PWB_CHECK(handle.try_result<int>() == nullptr);
}

TEST(degraded_predicate_finishes_degraded_never_done) {
    JobScheduler scheduler({.max_workers = 1});
    JobSpec spec;
    spec.run = [](JobContext&) -> std::any { return std::string("partial"); };
    spec.degraded_when = [](const std::any& result) {
        return std::any_cast<std::string>(result) == "partial";
    };
    JobHandle handle = scheduler.submit(std::move(spec));
    handle.wait();
    PWB_CHECK(handle.snapshot().state == JobState::degraded);
    PWB_CHECK(handle.snapshot().progress == 1.0);
}

TEST(degraded_predicate_failure_is_itself_a_caveat) {
    JobScheduler scheduler({.max_workers = 1});
    JobSpec spec;
    spec.run = [](JobContext&) -> std::any { return 1; };
    spec.degraded_when = [](const std::any&) -> bool {
        throw std::runtime_error("predicate bug");
    };
    JobHandle handle = scheduler.submit(std::move(spec));
    handle.wait();
    PWB_CHECK(handle.snapshot().state == JobState::degraded);
}

TEST(on_done_precedes_terminal_state) {
    // Frozen contract: callbacks run BEFORE the terminal state lands, so an
    // observer that sees the on_done side effect can rely on it having
    // completed — and at on_done time the state is still running.
    JobScheduler scheduler({.max_workers = 1});
    std::atomic<bool> observed_running{false};
    JobSpec spec;
    spec.task_key = "on-done-order";
    spec.run = [](JobContext&) -> std::any { return 7; };
    spec.on_done = [&observed_running, &scheduler](const std::any&) {
        for (const auto& snap : scheduler.statuses()) {
            if (snap.task_key == "on-done-order") {
                observed_running = snap.state == JobState::running;
            }
        }
    };
    JobHandle handle = scheduler.submit(std::move(spec));
    handle.wait();
    PWB_CHECK(handle.snapshot().state == JobState::done);
    PWB_CHECK(observed_running.load());
}

int main() { return pwb_test_main(); }
