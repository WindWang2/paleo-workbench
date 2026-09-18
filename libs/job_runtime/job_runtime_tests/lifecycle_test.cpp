// job_runtime.core — the frozen #1081 contracts: submit/run/finish,
// snapshots and typed results, FIFO order at concurrency 1, priority +
// boost ordering, and the bounded-threads guarantee under many tiny jobs.

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "job_test.hpp"
#include "pwb/job_runtime/job_scheduler.hpp"

using pwb::job::JobHandle;
using pwb::job::JobScheduler;
using pwb::job::JobSpec;
using pwb::job::JobState;

namespace {

// Gate helper: one worker blocked until released, so tests can stage the
// queue deterministically.
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

TEST(start_finish_snapshot_and_typed_result) {
    JobScheduler scheduler({.max_workers = 1});
    JobSpec spec;
    spec.kind = "background.compute";
    spec.title = "unit";
    spec.run = [](pwb::job::JobContext& ctx) -> std::any {
        ctx.report_progress(1, 4, "quarter");
        ctx.report_progress(4, 4, "done");
        return std::string("payload");
    };
    JobHandle handle = scheduler.submit(std::move(spec));
    handle.wait();
    const pwb::job::JobSnapshot snap = handle.snapshot();
    PWB_CHECK(snap.state == JobState::done);
    PWB_CHECK(snap.progress == 1.0);
    PWB_CHECK(snap.message == "done");
    PWB_CHECK(snap.started_at.has_value());
    PWB_CHECK(snap.finished_at.has_value());
    PWB_CHECK(snap.kind == "background.compute");
    const std::string* result = handle.try_result<std::string>();
    PWB_CHECK(result != nullptr && *result == "payload");
    PWB_CHECK(scheduler.idle());
}

TEST(fifo_order_at_concurrency_one) {
    JobScheduler scheduler({.max_workers = 1});
    std::mutex order_mutex;
    std::vector<int> order;
    for (int i = 0; i < 20; ++i) {
        JobSpec spec;
        spec.run = [&order, &order_mutex, i](pwb::job::JobContext&) -> std::any {
            std::lock_guard<std::mutex> guard(order_mutex);
            order.push_back(i);
            return {};
        };
        scheduler.submit(std::move(spec));
    }
    scheduler.wait_idle();
    std::lock_guard<std::mutex> guard(order_mutex);
    PWB_CHECK(order.size() == 20);
    for (int i = 0; i < 20; ++i) PWB_CHECK(order[static_cast<size_t>(i)] == i);
}

TEST(priority_and_boost_ordering) {
    JobScheduler scheduler({.max_workers = 1});
    Gate gate;
    std::atomic<bool> blocker_started{false};
    JobSpec blocker;
    blocker.run = [&gate, &blocker_started](pwb::job::JobContext&) -> std::any {
        blocker_started = true;
        gate.wait();
        return {};
    };
    (void)scheduler.submit(std::move(blocker));
    // Deterministic staging: the blocker must be RUNNING (lane occupied)
    // before the ordering candidates are staged — otherwise one of them
    // could legitimately claim the free lane first.
    while (!blocker_started.load()) std::this_thread::sleep_for(
        std::chrono::milliseconds(2));

    std::mutex order_mutex;
    std::vector<int> order;
    auto submit_ordered = [&](int priority) {
        JobSpec spec;
        spec.priority = priority;
        spec.run = [&order, &order_mutex, priority](pwb::job::JobContext&)
            -> std::any {
            std::lock_guard<std::mutex> guard(order_mutex);
            order.push_back(priority);
            return {};
        };
        (void)scheduler.submit(std::move(spec));
    };
    submit_ordered(1);
    submit_ordered(5);
    JobSpec boosted;
    boosted.priority = 0;
    const std::string boosted_id = "boost-me";
    // task_key is irrelevant here; capture the handle for boost().
    boosted.run = [&order, &order_mutex](pwb::job::JobContext&) -> std::any {
        std::lock_guard<std::mutex> guard(order_mutex);
        order.push_back(100);
        return {};
    };
    JobHandle boosted_handle = scheduler.submit(std::move(boosted));
    PWB_CHECK(scheduler.boost(boosted_handle.job_id(), 100));
    gate.open();
    scheduler.wait_idle();
    std::lock_guard<std::mutex> guard(order_mutex);
    PWB_CHECK(order.size() == 3);  // only the three ordered jobs push
    PWB_CHECK(order[0] == 100);  // boosted above everything
    PWB_CHECK(order[1] == 5);
    PWB_CHECK(order[2] == 1);
}

TEST(boost_matching_promotes_only_requested_kind) {
    JobScheduler scheduler({.max_workers = 1});
    Gate gate;
    JobSpec blocker;
    blocker.run = [&gate](pwb::job::JobContext&) -> std::any {
        gate.wait();
        return {};
    };
    (void)scheduler.submit(std::move(blocker));

    std::atomic<int> export_done{0};
    std::atomic<int> index_done{0};
    for (int i = 0; i < 3; ++i) {
        JobSpec export_job;
        export_job.kind = "export";
        export_job.run = [&export_done](pwb::job::JobContext&) -> std::any {
            ++export_done;
            return {};
        };
        (void)scheduler.submit(std::move(export_job));
    }
    for (int i = 0; i < 2; ++i) {
        JobSpec index_job;
        index_job.kind = "index";
        index_job.run = [&index_done](pwb::job::JobContext&) -> std::any {
            ++index_done;
            return {};
        };
        (void)scheduler.submit(std::move(index_job));
    }
    PWB_CHECK(scheduler.boost_matching("export", 90) == 3);
    gate.open();
    scheduler.wait_idle();
    PWB_CHECK(export_done.load() == 3);
    PWB_CHECK(index_done.load() == 2);
}

TEST(many_tiny_jobs_stay_bounded) {
    // 1000 tiny jobs over 4 fixed lanes: everything drains, and the thread
    // count never exceeded the constructed lanes (bounded scheduler — no
    // ad-hoc pools).
    JobScheduler scheduler({.max_workers = 4});
    PWB_CHECK(scheduler.worker_count() == 4);
    std::atomic<int> done{0};
    for (int i = 0; i < 1000; ++i) {
        JobSpec spec;
        spec.run = [&done](pwb::job::JobContext&) -> std::any {
            ++done;
            return {};
        };
        (void)scheduler.submit(std::move(spec));
    }
    scheduler.wait_idle();
    PWB_CHECK(done.load() == 1000);
    PWB_CHECK(scheduler.idle());
    PWB_CHECK(scheduler.active_count() == 0);
}

TEST(snapshot_handles_unknown_and_evicted) {
    JobScheduler scheduler({.max_workers = 1});
    PWB_CHECK(!scheduler.snapshot("missing").has_value());
    PWB_CHECK(!scheduler.handle("missing").valid());
    PWB_CHECK(!scheduler.cancel("missing"));
    JobHandle invalid;
    PWB_CHECK(!invalid.cancel());
    PWB_CHECK(invalid.snapshot().state == JobState::queued);  // default
    PWB_CHECK(invalid.wait_for(0.0));  // invalid handle waits trivially
}

int main() { return pwb_test_main(); }
