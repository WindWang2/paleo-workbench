// science.workflow.task_runtime — success/failure/cancel branches, publish
// invariants, state machine legality, shutdown join (test-plan G3).

#include "pwb_test.hpp"

#include <atomic>
#include <chrono>
#include <cmath>
#include <latch>
#include <stdexcept>
#include <stop_token>
#include <thread>

#include <pwb/science/algorithms/coherence_c3.hpp>
#include <pwb/workflow/task_runtime.hpp>

using namespace pwb;
using namespace pwb::science;
using namespace pwb::workflow;

namespace {

// Records every publication for invariant assertions.
class RecordingPublisher final : public IResultPublisherV1 {
public:
    void publish_success(const AlgorithmResultV1& result) override {
        const std::lock_guard<std::mutex> lock(mutex_);
        successes_.push_back(result.request_id);
    }
    void publish_failure(const Failure& failure) override {
        const std::lock_guard<std::mutex> lock(mutex_);
        failures_.push_back(failure);
    }
    [[nodiscard]] std::size_t success_count(const std::string& request_id) const {
        const std::lock_guard<std::mutex> lock(mutex_);
        return static_cast<std::size_t>(std::count(successes_.begin(), successes_.end(),
                                                   request_id));
    }
    [[nodiscard]] const Failure* find_failure(const std::string& request_id) const {
        const std::lock_guard<std::mutex> lock(mutex_);
        for (const Failure& failure : failures_) {
            if (failure.request_id == request_id) {
                return &failure;
            }
        }
        return nullptr;
    }

private:
    mutable std::mutex mutex_;
    std::vector<std::string> successes_;
    std::vector<Failure> failures_;
};

// Scripted algorithm: succeeds / fails / loops until cancelled, with optional
// slow phase so cancellation races the worker. The `gated` mode blocks inside
// run() until a latch is released (barrier-precise ordering for publish
// tests: the test wires handles into publishers while run() is parked).
class ScriptedAlgorithm final : public IAlgorithm {
public:
    enum class Mode { succeed, fail, cancel_cooperative, gated };

    explicit ScriptedAlgorithm(Mode mode) : mode_(mode) {}
    explicit ScriptedAlgorithm(std::latch& entered, std::latch& release)
        : mode_(Mode::gated), entered_(&entered), release_(&release) {}

    [[nodiscard]] const AlgorithmDescriptor& descriptor() const override {
        return descriptor_;
    }

    Result<AlgorithmResultV1> run(const AlgorithmRequestV1& request, ProgressSink progress,
                                  std::stop_token stop) override {
        runs_++;
        if (mode_ == Mode::fail) {
            return AlgorithmError{{Diagnostic{"scripted.failure", "planned failure", "error"}}};
        }
        if (mode_ == Mode::gated) {
            entered_->count_down();
            release_->wait();
            if (progress) {
                progress(ProgressReport{0.5, "gated"});
            }
            AlgorithmResultV1 result;
            result.request_id = request.request_id;
            result.outputs.push_back(ProducedVolume{"out", VolumeView{}, ""});
            result.provenance.algorithm_id = descriptor_.algorithm_id;
            result.provenance.algorithm_version = descriptor_.version;
            result.provenance.build_identity = "scripted";
            return result;
        }
        if (progress) {
            progress(ProgressReport{0.5, "half"});
        }
        while (mode_ == Mode::cancel_cooperative && !stop.stop_requested()) {
            std::this_thread::sleep_for(std::chrono::milliseconds(2));
        }
        if (stop.stop_requested()) {
            return TaskCancelled{"scripted"};
        }
        AlgorithmResultV1 result;
        result.request_id = request.request_id;
        result.outputs.push_back(ProducedVolume{"out", VolumeView{}, ""});
        result.provenance.algorithm_id = descriptor_.algorithm_id;
        result.provenance.algorithm_version = descriptor_.version;
        result.provenance.build_identity = "scripted";
        result.provenance.params_json = request.params_json;
        result.provenance.input_refs = request.input_refs;
        return result;
    }

    [[nodiscard]] int runs() const noexcept { return runs_; }

private:
    AlgorithmDescriptor descriptor_ = [] {
        AlgorithmDescriptor descriptor;
        descriptor.algorithm_id = "test.scripted";
        descriptor.version = "1.0.0";
        descriptor.display_name = "Scripted";
        descriptor.supports_cancel = true;
        descriptor.inputs.push_back(PortSpec{}); // no required volume ports
        descriptor.inputs.front().name = "none";
        descriptor.inputs.front().required = false;
        descriptor.inputs.front().kind = PortKind::path;
        return descriptor;
    }();
    Mode mode_;
    std::latch* entered_{nullptr};
    std::latch* release_{nullptr};
    std::atomic<int> runs_{0};
};

AlgorithmRequestV1 scripted_request(const char* request_id) {
    AlgorithmRequestV1 request;
    request.request_id = request_id;
    request.algorithm_id = "test.scripted";
    request.algorithm_version = "1.0.0";
    request.params_json = {{"kind", "1"}};
    request.input_refs.push_back(VersionRef{"asset-a", "version-7", ""});
    return request;
}

} // namespace

TEST(success_path_publishes_once_with_full_provenance) {
    TaskRuntime runtime;
    auto publisher = std::make_shared<RecordingPublisher>();
    TaskHandle handle =
        runtime.submit(std::make_shared<ScriptedAlgorithm>(ScriptedAlgorithm::Mode::succeed),
                       scripted_request("ok-1"), publisher);
    handle.wait();
    const TaskSnapshot snapshot = handle.snapshot();
    PWB_CHECK(snapshot.status == TaskStatus::succeeded);
    PWB_CHECK(publisher->success_count("ok-1") == 1);
    PWB_CHECK(publisher->find_failure("ok-1") == nullptr);
    PWB_CHECK(snapshot.progress.has_value());
    PWB_CHECK(snapshot.progress->fraction == 0.5);
}

TEST(failure_path_publishes_failure_and_never_success) {
    TaskRuntime runtime;
    auto publisher = std::make_shared<RecordingPublisher>();
    TaskHandle handle =
        runtime.submit(std::make_shared<ScriptedAlgorithm>(ScriptedAlgorithm::Mode::fail),
                       scripted_request("bad-1"), publisher);
    handle.wait();
    const TaskSnapshot snapshot = handle.snapshot();
    PWB_CHECK(snapshot.status == TaskStatus::failed);
    PWB_CHECK(snapshot.error_code == "scripted.failure");
    PWB_CHECK(publisher->success_count("bad-1") == 0);
    const IResultPublisherV1::Failure* failure = publisher->find_failure("bad-1");
    PWB_CHECK(failure != nullptr);
    PWB_CHECK(!failure->cancelled);
    PWB_CHECK(failure->code == "scripted.failure");
}

TEST(cancel_during_run_ends_cancelled_without_success) {
    TaskRuntime runtime;
    auto publisher = std::make_shared<RecordingPublisher>();
    auto algorithm =
        std::make_shared<ScriptedAlgorithm>(ScriptedAlgorithm::Mode::cancel_cooperative);
    TaskHandle handle = runtime.submit(algorithm, scripted_request("cxl-1"), publisher);
    // Wait until the algorithm is actually inside run(), then cancel.
    while (algorithm->runs() == 0) {
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    handle.cancel();
    handle.wait();
    const TaskSnapshot snapshot = handle.snapshot();
    PWB_CHECK(snapshot.status == TaskStatus::cancelled);
    PWB_CHECK(publisher->success_count("cxl-1") == 0);
    const IResultPublisherV1::Failure* failure = publisher->find_failure("cxl-1");
    PWB_CHECK(failure != nullptr);
    PWB_CHECK(failure->cancelled);
    PWB_CHECK(failure->code == "task.cancelled");
}

TEST(cancel_while_queued_never_runs_the_algorithm) {
    // Occupying the single worker with a slow task makes the second submit
    // stay queued, which is where queued-cancellation is observable.
    TaskRuntime runtime;
    auto publisher = std::make_shared<RecordingPublisher>();
    auto blocker =
        std::make_shared<ScriptedAlgorithm>(ScriptedAlgorithm::Mode::cancel_cooperative);
    TaskHandle blocking_handle = runtime.submit(blocker, scripted_request("blk-1"), nullptr);
    while (blocker->runs() == 0) {
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    auto queued_algorithm =
        std::make_shared<ScriptedAlgorithm>(ScriptedAlgorithm::Mode::succeed);
    TaskHandle queued_handle = runtime.submit(queued_algorithm, scripted_request("q-1"), publisher);
    queued_handle.cancel(); // still queued: worker is busy with blk-1
    blocking_handle.cancel();
    blocking_handle.wait();
    queued_handle.wait();

    const TaskSnapshot snapshot = queued_handle.snapshot();
    PWB_CHECK(snapshot.status == TaskStatus::cancelled);
    PWB_CHECK(queued_algorithm->runs() == 0); // run() never invoked
    PWB_CHECK(publisher->success_count("q-1") == 0);
    const IResultPublisherV1::Failure* failure = publisher->find_failure("q-1");
    PWB_CHECK(failure != nullptr);
    PWB_CHECK(failure->cancelled);
}

TEST(cancel_after_terminal_is_a_no_op) {
    TaskRuntime runtime;
    auto publisher = std::make_shared<RecordingPublisher>();
    TaskHandle handle =
        runtime.submit(std::make_shared<ScriptedAlgorithm>(ScriptedAlgorithm::Mode::succeed),
                       scripted_request("done-1"), publisher);
    handle.wait();
    PWB_CHECK(handle.snapshot().status == TaskStatus::succeeded);
    handle.cancel(); // no-op: already terminal
    PWB_CHECK(handle.snapshot().status == TaskStatus::succeeded);
    PWB_CHECK(publisher->success_count("done-1") == 1);
    PWB_CHECK(publisher->find_failure("done-1") == nullptr);
}

TEST(runtime_destructor_joins_without_hanging_or_duplicate_publishes) {
    std::shared_ptr<RecordingPublisher> publisher;
    TaskHandle handle;
    {
        TaskRuntime runtime;
        publisher = std::make_shared<RecordingPublisher>();
        handle = runtime.submit(
            std::make_shared<ScriptedAlgorithm>(ScriptedAlgorithm::Mode::cancel_cooperative),
            scripted_request("dtor-1"), publisher);
        while (handle.snapshot().status == TaskStatus::queued) {
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
        // Destructor must join the running task (it keeps running until stop;
        // the jthread stop_token of the worker itself is not the task token,
        // so the destructor blocks — document that runtimes must be drained
        // or tasks cancelled before destruction in real hosts).
        handle.cancel();
    } // ~TaskRuntime joins here
    PWB_CHECK(handle.snapshot().status == TaskStatus::cancelled);
    PWB_CHECK(publisher->success_count("dtor-1") == 0);
    PWB_CHECK(publisher->find_failure("dtor-1") != nullptr);
}

TEST(real_coherence_runs_end_to_end_through_the_runtime) {
    TaskRuntime runtime;
    auto publisher = std::make_shared<RecordingPublisher>();
    auto algorithm = algorithms::make_coherence_c3("runtime-e2e");
    std::shared_ptr<IAlgorithm> shared_algorithm = std::move(algorithm);
    std::vector<float> pattern(8 * 8 * 16);
    for (std::size_t i = 0; i < pattern.size(); ++i) {
        pattern[i] = std::sin(0.05f * static_cast<float>(i % 97));
    }
    auto owned = std::make_shared<const std::vector<float>>(std::move(pattern));
    AlgorithmRequestV1 request;
    request.algorithm_id = "seismic.coherence_c3";
    request.algorithm_version = "1.0.0";
    request.params_json = {{"win_il", "2"}, {"win_xl", "2"}, {"win_t", "2"},
                           {"power_iterations", "30"}};
    request.input_refs.push_back(VersionRef{"asset-r", "version-r", ""});
    request.input_volumes.push_back(
        VolumeView{owned->data(), {8, 8, 16}, {0, 0, 0}, owned});
    TaskHandle handle = runtime.submit(shared_algorithm, std::move(request), publisher);
    handle.wait();
    const TaskSnapshot snapshot = handle.snapshot();
    PWB_CHECK(snapshot.status == TaskStatus::succeeded);
    PWB_CHECK(publisher->success_count(handle.snapshot().request_id) == 1);
    PWB_CHECK(snapshot.progress.has_value());
    PWB_CHECK(snapshot.progress->fraction == 1.0);
}

// --- v3 publish/close semantics (v3-contracts.md §1) -----------------------
//
// All ordering below is enforced with latches/flags, never fixed sleeps.

namespace {

// Blocks inside publish_success until released; counts publish calls.
class BarrierPublisher final : public IResultPublisherV1 {
public:
    BarrierPublisher(std::latch& entered, std::latch& release)
        : entered_(&entered), release_(&release) {}

    void publish_success(const AlgorithmResultV1&) override {
        ++success_calls;
        entered_->count_down();
        release_->wait();
    }
    void publish_failure(const Failure&) override { ++failure_calls; }

    std::atomic<int> success_calls{0};
    std::atomic<int> failure_calls{0};

private:
    std::latch* entered_;
    std::latch* release_;
};

// publish_success throws; publish_failure records. For L3 "publish throws".
class ThrowingSuccessPublisher final : public IResultPublisherV1 {
public:
    void publish_success(const AlgorithmResultV1&) override {
        ++success_calls;
        throw std::runtime_error("database down");
    }
    void publish_failure(const Failure& failure) override {
        const std::lock_guard<std::mutex> lock(mutex_);
        failures_.push_back(failure);
    }
    [[nodiscard]] const Failure* find_failure(const std::string& request_id) const {
        const std::lock_guard<std::mutex> lock(mutex_);
        for (const Failure& failure : failures_) {
            if (failure.request_id == request_id) {
                return &failure;
            }
        }
        return nullptr;
    }

    std::atomic<int> success_calls{0};

private:
    mutable std::mutex mutex_;
    std::vector<Failure> failures_;
};

// publish_failure throws; publish_success must never be called.
class ThrowingFailurePublisher final : public IResultPublisherV1 {
public:
    void publish_success(const AlgorithmResultV1&) override { ++success_calls; }
    void publish_failure(const Failure&) override {
        ++failure_calls;
        throw std::runtime_error("failure sink unavailable");
    }

    std::atomic<int> success_calls{0};
    std::atomic<int> failure_calls{0};
};

bool has_diagnostic(const std::vector<Diagnostic>& diagnostics, const char* code) {
    for (const Diagnostic& diagnostic : diagnostics) {
        if (diagnostic.code == code) {
            return true;
        }
    }
    return false;
}

} // namespace

TEST(wait_returns_only_after_publish_completes) {
    // v3: publish BEFORE terminal. While the publisher is parked inside
    // publish_success, wait() must not return and the snapshot must expose
    // the publishing phase.
    std::latch publish_entered(1);
    std::latch release_publish(1);
    auto publisher = std::make_shared<BarrierPublisher>(publish_entered, release_publish);

    TaskRuntime runtime;
    TaskHandle handle = runtime.submit(
        std::make_shared<ScriptedAlgorithm>(ScriptedAlgorithm::Mode::succeed),
        scripted_request("slowpub-1"), publisher);

    std::atomic<bool> wait_done{false};
    std::thread waiter([&handle, &wait_done] {
        handle.wait();
        wait_done.store(true, std::memory_order_release);
    });

    publish_entered.wait(); // publisher is inside publish_success, parked
    PWB_CHECK(!wait_done.load(std::memory_order_acquire));
    PWB_CHECK(handle.snapshot().status == TaskStatus::publishing);
    PWB_CHECK(!handle.snapshot().published);

    release_publish.count_down();
    waiter.join();
    PWB_CHECK(wait_done.load(std::memory_order_acquire));
    const TaskSnapshot snapshot = handle.snapshot();
    PWB_CHECK(snapshot.status == TaskStatus::succeeded);
    PWB_CHECK(snapshot.published);
    PWB_CHECK(publisher->success_calls == 1);
}

TEST(publish_success_throwing_marks_task_failed_and_worker_continues) {
    TaskRuntime runtime;
    auto publisher = std::make_shared<ThrowingSuccessPublisher>();
    TaskHandle handle = runtime.submit(
        std::make_shared<ScriptedAlgorithm>(ScriptedAlgorithm::Mode::succeed),
        scripted_request("throw-1"), publisher);
    handle.wait();
    const TaskSnapshot snapshot = handle.snapshot();
    PWB_CHECK(snapshot.status == TaskStatus::failed); // publish failed => not success
    PWB_CHECK(snapshot.error_code == "publisher.publish_threw");
    PWB_CHECK(!snapshot.published);
    PWB_CHECK(has_diagnostic(snapshot.diagnostics, "publisher.publish_threw"));
    PWB_CHECK(publisher->success_calls == 1); // exactly one attempt
    PWB_CHECK(publisher->find_failure("throw-1") == nullptr); // no compensating failure

    // The worker survived: the next task runs and publishes normally.
    auto next_publisher = std::make_shared<RecordingPublisher>();
    TaskHandle next = runtime.submit(
        std::make_shared<ScriptedAlgorithm>(ScriptedAlgorithm::Mode::succeed),
        scripted_request("throw-2"), next_publisher);
    next.wait();
    PWB_CHECK(next.snapshot().status == TaskStatus::succeeded);
    PWB_CHECK(next.snapshot().published);
    PWB_CHECK(next_publisher->success_count("throw-2") == 1);
}

TEST(failure_publish_throwing_keeps_verdict_and_publishes_once) {
    TaskRuntime runtime;

    // Algorithm failure + throwing publish_failure: verdict stays "failed"
    // with the algorithm's own code; the publish exception is only a
    // diagnostic; exactly one publish attempt; never success.
    auto throwing = std::make_shared<ThrowingFailurePublisher>();
    TaskHandle failed_handle = runtime.submit(
        std::make_shared<ScriptedAlgorithm>(ScriptedAlgorithm::Mode::fail),
        scripted_request("fthrow-1"), throwing);
    failed_handle.wait();
    const TaskSnapshot failed_snapshot = failed_handle.snapshot();
    PWB_CHECK(failed_snapshot.status == TaskStatus::failed);
    PWB_CHECK(failed_snapshot.error_code == "scripted.failure");
    PWB_CHECK(!failed_snapshot.published);
    PWB_CHECK(has_diagnostic(failed_snapshot.diagnostics, "publisher.publish_failure_threw"));
    PWB_CHECK(throwing->failure_calls == 1);
    PWB_CHECK(throwing->success_calls == 0);

    // Queued cancellation + throwing publish_failure: stays cancelled, no
    // success result can exist, publish attempted exactly once.
    auto blocker =
        std::make_shared<ScriptedAlgorithm>(ScriptedAlgorithm::Mode::cancel_cooperative);
    TaskHandle blocking_handle = runtime.submit(blocker, scripted_request("fthrow-blk"), nullptr);
    while (blocker->runs() == 0) {
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    TaskHandle cancelled_handle = runtime.submit(
        std::make_shared<ScriptedAlgorithm>(ScriptedAlgorithm::Mode::succeed),
        scripted_request("fthrow-2"), throwing);
    cancelled_handle.cancel(); // still queued behind the blocker
    blocking_handle.cancel();
    blocking_handle.wait();
    cancelled_handle.wait();
    const TaskSnapshot cancelled_snapshot = cancelled_handle.snapshot();
    PWB_CHECK(cancelled_snapshot.status == TaskStatus::cancelled);
    PWB_CHECK(!cancelled_snapshot.published);
    PWB_CHECK(has_diagnostic(cancelled_snapshot.diagnostics,
                             "publisher.publish_failure_threw"));
    PWB_CHECK(throwing->failure_calls == 2); // fthrow-1 + fthrow-2, each once
    PWB_CHECK(throwing->success_calls == 0);
}

TEST(snapshot_is_reentrant_from_publish_callback) {
    // The publisher (worker thread) reads snapshot() and calls cancel()
    // while publish_success is in flight: no lock is held across publish, so
    // both must be safe and observe status==publishing.
    struct Hooks {
        std::mutex mutex;
        TaskHandle handle;
        bool observed_publishing{false};
        std::string observed_error;
    };
    auto hook_ptr = std::make_shared<Hooks>();

    class ReentrantPublisher final : public IResultPublisherV1 {
    public:
        explicit ReentrantPublisher(std::shared_ptr<Hooks> hooks) : hooks_(std::move(hooks)) {}
        void publish_success(const AlgorithmResultV1&) override {
            const std::lock_guard<std::mutex> lock(hooks_->mutex);
            const TaskSnapshot snapshot = hooks_->handle.snapshot();
            hooks_->observed_publishing = snapshot.status == TaskStatus::publishing;
            hooks_->handle.cancel(); // L3 no-op; must not throw or deadlock
            ++calls;
        }
        void publish_failure(const Failure&) override { ++failures; }
        std::atomic<int> calls{0};
        std::atomic<int> failures{0};

    private:
        std::shared_ptr<Hooks> hooks_;
    };

    std::latch run_entered(1);
    std::latch release_run(1);
    TaskRuntime runtime;
    auto publisher = std::make_shared<ReentrantPublisher>(hook_ptr);
    TaskHandle handle =
        runtime.submit(std::make_shared<ScriptedAlgorithm>(run_entered, release_run),
                       scripted_request("reent-1"), publisher);
    run_entered.wait(); // algorithm parked: wire the handle safely
    {
        const std::lock_guard<std::mutex> lock(hook_ptr->mutex);
        hook_ptr->handle = handle;
    }
    release_run.count_down();
    handle.wait();

    PWB_CHECK(publisher->calls == 1);
    PWB_CHECK(hook_ptr->observed_publishing);
    PWB_CHECK(handle.snapshot().status == TaskStatus::succeeded);
    PWB_CHECK(handle.snapshot().published);
}

TEST(self_wait_from_publisher_is_detected_and_throws) {
    // A publisher waiting on its own task could only be satisfied by itself;
    // v3 detects it instead of deadlocking. The publisher catches the
    // logic_error, so publication still completes and the task succeeds.
    struct SelfHooks {
        std::mutex mutex;
        TaskHandle handle;
        bool caught_self_wait{false};
        std::string message;
    };
    auto hook_ptr = std::make_shared<SelfHooks>();

    class SelfWaitingPublisher final : public IResultPublisherV1 {
    public:
        explicit SelfWaitingPublisher(std::shared_ptr<SelfHooks> hooks)
            : hooks_(std::move(hooks)) {}
        void publish_success(const AlgorithmResultV1&) override {
            const std::lock_guard<std::mutex> lock(hooks_->mutex);
            try {
                hooks_->handle.wait(); // prohibited self-wait
            } catch (const std::logic_error& error) {
                hooks_->caught_self_wait = true;
                hooks_->message = error.what();
            }
        }
        void publish_failure(const Failure&) override {}

    private:
        std::shared_ptr<SelfHooks> hooks_;
    };

    std::latch run_entered(1);
    std::latch release_run(1);
    TaskRuntime runtime;
    auto publisher = std::make_shared<SelfWaitingPublisher>(hook_ptr);
    TaskHandle handle =
        runtime.submit(std::make_shared<ScriptedAlgorithm>(run_entered, release_run),
                       scripted_request("selfwait-1"), publisher);
    run_entered.wait();
    {
        const std::lock_guard<std::mutex> lock(hook_ptr->mutex);
        hook_ptr->handle = handle;
    }
    release_run.count_down();
    handle.wait();

    PWB_CHECK(hook_ptr->caught_self_wait);
    PWB_CHECK(hook_ptr->message.find("self_wait_detected") != std::string::npos);
    PWB_CHECK(handle.snapshot().status == TaskStatus::succeeded);
    PWB_CHECK(handle.snapshot().published);
}

TEST(wait_idle_from_publisher_is_detected_and_throws) {
    struct IdleHooks {
        std::mutex mutex;
        TaskRuntime* runtime{nullptr};
        bool caught{false};
    };
    auto hook_ptr = std::make_shared<IdleHooks>();

    class IdleWaitingPublisher final : public IResultPublisherV1 {
    public:
        explicit IdleWaitingPublisher(std::shared_ptr<IdleHooks> hooks)
            : hooks_(std::move(hooks)) {}
        void publish_success(const AlgorithmResultV1&) override {
            const std::lock_guard<std::mutex> lock(hooks_->mutex);
            try {
                hooks_->runtime->wait_idle();
            } catch (const std::logic_error&) {
                hooks_->caught = true;
            }
        }
        void publish_failure(const Failure&) override {}

    private:
        std::shared_ptr<IdleHooks> hooks_;
    };

    std::latch run_entered(1);
    std::latch release_run(1);
    TaskRuntime runtime;
    hook_ptr->runtime = &runtime;
    TaskHandle handle = runtime.submit(
        std::make_shared<ScriptedAlgorithm>(run_entered, release_run),
        scripted_request("idlewait-1"),
        std::make_shared<IdleWaitingPublisher>(hook_ptr));
    run_entered.wait();
    release_run.count_down();
    handle.wait();

    PWB_CHECK(hook_ptr->caught);
    PWB_CHECK(handle.snapshot().status == TaskStatus::succeeded);
    runtime.wait_idle(); // from a non-worker thread: fine
}

TEST(cancel_during_irrevocable_publish_still_succeeds) {
    // L2/L3: once run() returned, the outcome is irrevocable. A cancel
    // arriving while publish_success is in flight is a no-op: the task
    // succeeds, the success is published exactly once, and no cancellation
    // failure appears (never "DB success + task cancelled").
    std::latch publish_entered(1);
    std::latch release_publish(1);
    auto publisher = std::make_shared<BarrierPublisher>(publish_entered, release_publish);

    TaskRuntime runtime;
    TaskHandle handle = runtime.submit(
        std::make_shared<ScriptedAlgorithm>(ScriptedAlgorithm::Mode::succeed),
        scripted_request("latecxl-1"), publisher);
    publish_entered.wait(); // inside publish; computation already finished
    handle.cancel();
    release_publish.count_down();
    handle.wait();

    PWB_CHECK(handle.snapshot().status == TaskStatus::succeeded);
    PWB_CHECK(handle.snapshot().published);
    PWB_CHECK(publisher->success_calls == 1);
    PWB_CHECK(publisher->failure_calls == 0);
}

TEST(explicit_shutdown_drains_queue_and_rejects_new_submits) {
    TaskRuntime runtime;
    auto publisher = std::make_shared<RecordingPublisher>();

    auto blocker =
        std::make_shared<ScriptedAlgorithm>(ScriptedAlgorithm::Mode::cancel_cooperative);
    TaskHandle blocking_handle = runtime.submit(blocker, scripted_request("sd-blk"), nullptr);
    while (blocker->runs() == 0) {
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    TaskHandle queued_a = runtime.submit(
        std::make_shared<ScriptedAlgorithm>(ScriptedAlgorithm::Mode::succeed),
        scripted_request("sd-1"), publisher);
    TaskHandle queued_b = runtime.submit(
        std::make_shared<ScriptedAlgorithm>(ScriptedAlgorithm::Mode::succeed),
        scripted_request("sd-2"), publisher);

    blocking_handle.cancel();
    runtime.shutdown(); // drains: blocker cancelled, sd-1/sd-2 run + publish

    PWB_CHECK(blocking_handle.snapshot().status == TaskStatus::cancelled);
    PWB_CHECK(queued_a.snapshot().status == TaskStatus::succeeded);
    PWB_CHECK(queued_a.snapshot().published);
    PWB_CHECK(queued_b.snapshot().status == TaskStatus::succeeded);
    PWB_CHECK(queued_b.snapshot().published);
    PWB_CHECK(publisher->success_count("sd-1") == 1);
    PWB_CHECK(publisher->success_count("sd-2") == 1);

    // Rejected submits never publish — the request was never accepted.
    TaskHandle rejected = runtime.submit(
        std::make_shared<ScriptedAlgorithm>(ScriptedAlgorithm::Mode::succeed),
        scripted_request("sd-3"), publisher);
    PWB_CHECK(rejected.snapshot().status == TaskStatus::failed);
    PWB_CHECK(rejected.snapshot().error_code == "runtime.shutdown");
    PWB_CHECK(!rejected.snapshot().published);
    PWB_CHECK(publisher->success_count("sd-3") == 0);
    PWB_CHECK(publisher->find_failure("sd-3") == nullptr);

    runtime.shutdown(); // idempotent
}

#include "pwb_test_main.inc"
