// science.workflow.task_runtime — success/failure/cancel branches, publish
// invariants, state machine legality, shutdown join (test-plan G3).

#include "pwb_test.hpp"

#include <atomic>
#include <chrono>
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
// slow phase so cancellation races the worker.
class ScriptedAlgorithm final : public IAlgorithm {
public:
    enum class Mode { succeed, fail, cancel_cooperative };

    explicit ScriptedAlgorithm(Mode mode) : mode_(mode) {}

    [[nodiscard]] const AlgorithmDescriptor& descriptor() const override {
        return descriptor_;
    }

    Result<AlgorithmResultV1> run(const AlgorithmRequestV1& request, ProgressSink progress,
                                  std::stop_token stop) override {
        runs_++;
        if (mode_ == Mode::fail) {
            return AlgorithmError{{Diagnostic{"scripted.failure", "planned failure", "error"}}};
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

#include "pwb_test_main.inc"
