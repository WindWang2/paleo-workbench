#include <pwb/workflow/task_runtime.hpp>

#include <atomic>
#include <random>
#include <sstream>
#include <stdexcept>
#include <utility>

namespace pwb::workflow {

namespace {

std::string generate_id(const char* prefix) {
    static std::atomic<std::uint64_t> counter{0};
    std::random_device device;
    std::ostringstream out;
    out << prefix << "-" << std::hex << (device() & 0xffffffffu) << "-"
        << counter.fetch_add(1);
    return out.str();
}

} // namespace

struct TaskHandle::State {
    std::mutex mutex;
    std::condition_variable done_cv;
    std::string task_id;
    std::string algorithm_id;
    science::AlgorithmRequestV1 request;
    std::stop_source stop_source;
    // Set at submit; never null for a submitted task. Shared so a handle can
    // detect worker-thread waits without owning the runtime: a not-yet-done
    // state always belongs to a runtime that is still draining (the runtime
    // destructor joins only after every queued task reached a terminal
    // state), so the pointer is safe to read whenever !done.
    std::shared_ptr<TaskRuntime::WorkerIdentity> worker;
    TaskSnapshot snapshot; // task_id/request_id/algorithm_id/status + runtime state
    bool done{false};

    void finish_locked(TaskStatus status, std::string error_code,
                       std::vector<science::Diagnostic> diagnostics) {
        snapshot.status = status;
        snapshot.error_code = std::move(error_code);
        snapshot.diagnostics = std::move(diagnostics);
        done = true;
        done_cv.notify_all();
    }
};

void TaskHandle::cancel() {
    if (!state_) {
        return;
    }
    // Only the stop request: the terminal state is decided exclusively by
    // TaskRuntime::execute from the run outcome, so a cancelled task can
    // never publish success even when cancel() races with completion. Once
    // run() returned (v3-contracts.md L2/L3) the stop request is recorded
    // but changes nothing about the outcome anymore.
    state_->stop_source.request_stop();
}

TaskSnapshot TaskHandle::snapshot() const {
    if (!state_) {
        return {};
    }
    std::lock_guard<std::mutex> lock(state_->mutex);
    return state_->snapshot;
}

void TaskHandle::wait() {
    if (!state_) {
        return;
    }
    std::unique_lock<std::mutex> lock(state_->mutex);
    // A wait from the worker thread on a not-yet-terminal task can only be
    // satisfied by the waiter itself (publishers run on the worker; the only
    // task it could finish while blocked is its own). Detect instead of
    // deadlocking — never bypass by marking success early.
    if (!state_->done && state_->worker != nullptr &&
        std::this_thread::get_id() == state_->worker->id.load(std::memory_order_acquire)) {
        throw std::logic_error(
            "task.self_wait_detected: wait() called from the runtime worker "
            "thread on a task that is not terminal (publisher self-wait)");
    }
    state_->done_cv.wait(lock, [this] { return state_->done; });
}

TaskRuntime::TaskRuntime() : worker_([this](std::stop_token token) {
    (void)token;
    worker_identity_->id.store(std::this_thread::get_id(), std::memory_order_release);
    worker_loop();
}) {}

TaskRuntime::~TaskRuntime() { shutdown(); }

void TaskRuntime::shutdown() {
    {
        std::lock_guard<std::mutex> lock(mutex_);
        shutdown_ = true;
    }
    work_cv_.notify_all();
    if (!joined_) {
        worker_.join();
        joined_ = true;
    }
}

TaskHandle TaskRuntime::submit(std::shared_ptr<science::IAlgorithm> algorithm,
                               science::AlgorithmRequestV1 request,
                               std::shared_ptr<science::IResultPublisherV1> publisher) {
    auto state = std::make_shared<TaskHandle::State>();
    if (request.request_id.empty()) {
        request.request_id = generate_id("req");
    }
    state->task_id = generate_id("task");
    state->request = request;
    state->worker = worker_identity_;
    state->snapshot.task_id = state->task_id;
    state->snapshot.request_id = request.request_id;
    state->algorithm_id = request.algorithm_id;
    state->snapshot.algorithm_id = request.algorithm_id;

    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (shutdown_) {
            // Rejected before acceptance: terminal, never published.
            state->finish_locked(TaskStatus::failed, "runtime.shutdown", {});
            return TaskHandle(std::move(state));
        }
        queue_.push(Submission{state, std::move(algorithm), std::move(request),
                               std::move(publisher)});
    }
    work_cv_.notify_one();
    return TaskHandle(std::move(state));
}

void TaskRuntime::wait_idle() {
    if (std::this_thread::get_id() ==
        worker_identity_->id.load(std::memory_order_acquire)) {
        throw std::logic_error(
            "task.self_wait_detected: wait_idle() called from the runtime "
            "worker thread (idle can only be reached after this caller "
            "returns)");
    }
    std::unique_lock<std::mutex> lock(mutex_);
    idle_cv_.wait(lock, [this] { return queue_.empty() && active_ == 0; });
}

void TaskRuntime::worker_loop() {
    for (;;) {
        Submission submission;
        {
            std::unique_lock<std::mutex> lock(mutex_);
            work_cv_.wait(lock, [this] { return shutdown_ || !queue_.empty(); });
            if (queue_.empty()) {
                if (shutdown_) {
                    return;
                }
                continue;
            }
            submission = std::move(queue_.front());
            queue_.pop();
            ++active_;
        }
        // A throwing publisher (host code) must not kill the worker, and
        // execute() already converts publish exceptions into task outcomes;
        // this guard is defense in depth for anything unexpected.
        try {
            execute(submission);
        } catch (...) {
        }
        {
            std::lock_guard<std::mutex> lock(mutex_);
            --active_;
            if (queue_.empty() && active_ == 0) {
                idle_cv_.notify_all();
            }
        }
    }
}

namespace {

} // namespace

// Enters the publishing phase: marks status==publishing under the task lock
// (publish itself runs WITHOUT the lock so snapshot()/wait() stay reentrant).
// Returns false when the task is already terminal (defensive; only the
// worker finishes tasks). The phase ends with the terminal transition.
bool TaskRuntime::begin_publishing(TaskHandle::State& state) {
    std::lock_guard<std::mutex> lock(state.mutex);
    if (state.done) {
        return false;
    }
    state.snapshot.status = TaskStatus::publishing;
    return true;
}

void TaskRuntime::execute(Submission& submission) {
    const auto& state = submission.state;
    const bool has_publisher = submission.publisher != nullptr;

    science::ProgressSink progress = [weak = std::weak_ptr<TaskHandle::State>(state)](
                                         const science::ProgressReport& report) {
        if (const auto locked = weak.lock()) {
            std::lock_guard<std::mutex> lock(locked->mutex);
            const double previous =
                locked->snapshot.progress ? locked->snapshot.progress->fraction : 0.0;
            if (report.fraction >= previous) { // weakly monotonic
                locked->snapshot.progress = report;
            }
        }
    };

    // Decided terminal outcome of the algorithm phase and, when reached
    // without an early return, the publication to perform for it.
    enum class Outcome { success, failure, cancelled_queued };
    Outcome outcome_kind = Outcome::success;
    science::AlgorithmResultV1 success_result;
    science::IResultPublisherV1::Failure failure;
    std::vector<science::Diagnostic> outcome_diagnostics; // attached at finish

    // L0: cancellation observed while queued — the algorithm never runs.
    if (state->stop_source.stop_requested()) {
        outcome_kind = Outcome::cancelled_queued;
        failure.request_id = state->request.request_id;
        failure.code = "task.cancelled";
        failure.message = "cancelled while queued";
        failure.cancelled = true;
    } else {
        {
            std::lock_guard<std::mutex> lock(state->mutex);
            if (state->done) {
                return; // defensive; nothing but the worker finishes tasks
            }
            state->snapshot.status = TaskStatus::running;
        }

        science::Result<science::AlgorithmResultV1> run_outcome =
            science::AlgorithmError{
                {science::Diagnostic{"algorithm.exception", "run threw an exception",
                                     "error"}}};
        try {
            run_outcome = submission.algorithm->run(state->request, std::move(progress),
                                                    state->stop_source.get_token());
        } catch (const std::exception& error) {
            run_outcome = science::AlgorithmError{
                {science::Diagnostic{"algorithm.exception", error.what(), "error"}}};
        } catch (...) {
            run_outcome = science::AlgorithmError{
                {science::Diagnostic{"algorithm.exception", "unknown exception", "error"}}};
        }

        // L2: run() returned — the outcome is irrevocable from here on.
        if (run_outcome.has_value()) {
            outcome_kind = Outcome::success;
            success_result = std::move(run_outcome.value());
            outcome_diagnostics = success_result.diagnostics;
        } else if (run_outcome.is_cancelled()) {
            outcome_kind = Outcome::cancelled_queued; // cancelled during run (L1)
            failure.request_id = state->request.request_id;
            failure.code = "task.cancelled";
            failure.message = run_outcome.cancelled().stage;
            failure.cancelled = true;
        } else {
            outcome_kind = Outcome::failure;
            std::string error_code = "algorithm.error";
            if (!run_outcome.error().diagnostics.empty()) {
                error_code = run_outcome.error().diagnostics.front().code;
            }
            outcome_diagnostics = run_outcome.error().diagnostics;
            failure.request_id = state->request.request_id;
            failure.code = error_code;
            failure.message = "algorithm failed";
            failure.cancelled = false;
        }
    }

    // Publication phase: the publish_* call happens BEFORE the terminal
    // state is set, outside every lock. Exactly one attempt — a throwing
    // publisher never triggers a second call.
    bool publish_threw = false;
    if (has_publisher) {
        if (!begin_publishing(*state)) {
            return;
        }
        try {
            if (outcome_kind == Outcome::success) {
                submission.publisher->publish_success(success_result);
            } else {
                submission.publisher->publish_failure(failure);
            }
        } catch (const std::exception& error) {
            publish_threw = true;
            outcome_diagnostics.push_back(science::Diagnostic{
                outcome_kind == Outcome::success ? "publisher.publish_threw"
                                                 : "publisher.publish_failure_threw",
                error.what(), "error"});
        } catch (...) {
            publish_threw = true;
            outcome_diagnostics.push_back(science::Diagnostic{
                outcome_kind == Outcome::success ? "publisher.publish_threw"
                                                 : "publisher.publish_failure_threw",
                "unknown exception", "error"});
        }
    }

    // Terminal transition. Success requires a publication that returned:
    // a throwing publish_success downgrades to failed with a stable code.
    // For failure/cancelled outcomes the algorithm verdict stands and the
    // publish exception is only recorded as a diagnostic (never retried).
    {
        std::lock_guard<std::mutex> lock(state->mutex);
        if (state->done) {
            return; // defensive
        }
        state->snapshot.published = has_publisher && !publish_threw;
        switch (outcome_kind) {
        case Outcome::success:
            if (publish_threw) {
                state->finish_locked(TaskStatus::failed, "publisher.publish_threw",
                                     std::move(outcome_diagnostics));
            } else {
                state->finish_locked(TaskStatus::succeeded, {},
                                     std::move(outcome_diagnostics));
            }
            break;
        case Outcome::failure:
            state->finish_locked(TaskStatus::failed, failure.code,
                                 std::move(outcome_diagnostics));
            break;
        case Outcome::cancelled_queued:
            state->finish_locked(TaskStatus::cancelled, "task.cancelled",
                                 std::move(outcome_diagnostics));
            break;
        }
    }
}

} // namespace pwb::workflow
