#include <pwb/workflow/task_runtime.hpp>

#include <atomic>
#include <random>
#include <sstream>
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
    // never publish success even when cancel() races with completion.
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
    state_->done_cv.wait(lock, [this] { return state_->done; });
}

TaskRuntime::TaskRuntime() : worker_([this](std::stop_token token) {
    (void)token;
    worker_loop();
}) {}

TaskRuntime::~TaskRuntime() {
    {
        std::lock_guard<std::mutex> lock(mutex_);
        shutdown_ = true;
    }
    work_cv_.notify_all();
    worker_.join();
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
    state->snapshot.task_id = state->task_id;
    state->snapshot.request_id = request.request_id;
    state->algorithm_id = request.algorithm_id;
    state->snapshot.algorithm_id = request.algorithm_id;

    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (shutdown_) {
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
        // A throwing publisher (host code) must not kill the worker.
        try {
            execute(submission);
        } catch (...) {
            // execute() records the terminal state before publishers run;
            // the exception escapes only from the publisher itself.
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

void TaskRuntime::execute(Submission& submission) {
    const auto& state = submission.state;

    // Cancellation observed while queued: the algorithm never runs.
    if (state->stop_source.stop_requested()) {
        bool needs_publish = false;
        {
            std::lock_guard<std::mutex> lock(state->mutex);
            if (!state->done) {
                needs_publish = true;
                state->finish_locked(TaskStatus::cancelled, "task.cancelled", {});
            }
        }
        if (needs_publish && submission.publisher != nullptr) {
            science::IResultPublisherV1::Failure failure;
            failure.request_id = state->request.request_id;
            failure.code = "task.cancelled";
            failure.message = "cancelled while queued";
            failure.cancelled = true;
            submission.publisher->publish_failure(failure);
        }
        return;
    }

    {
        std::lock_guard<std::mutex> lock(state->mutex);
        if (state->done) {
            return; // cancelled-before-run raced with an explicit terminal state
        }
        state->snapshot.status = TaskStatus::running;
    }

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

    science::Result<science::AlgorithmResultV1> outcome = science::AlgorithmError{
        {science::Diagnostic{"algorithm.exception", "run threw an exception", "error"}}};
    try {
        outcome = submission.algorithm->run(state->request, std::move(progress),
                                            state->stop_source.get_token());
    } catch (const std::exception& error) {
        outcome = science::AlgorithmError{
            {science::Diagnostic{"algorithm.exception", error.what(), "error"}}};
    } catch (...) {
        outcome = science::AlgorithmError{
            {science::Diagnostic{"algorithm.exception", "unknown exception", "error"}}};
    }

    // Decide the terminal state under the lock, then publish WITHOUT holding
    // it: publisher implementations are host code and may call back into
    // snapshot()/wait() on the same thread.
    enum class Terminal { success, failure, cancelled } terminal;
    science::AlgorithmResultV1 success_result;
    science::IResultPublisherV1::Failure failure;
    {
        std::lock_guard<std::mutex> lock(state->mutex);
        if (state->done) {
            return; // already terminal (defensive; nothing transitions out of terminal)
        }
        if (outcome.has_value()) {
            state->snapshot.diagnostics = outcome.value().diagnostics;
            state->finish_locked(TaskStatus::succeeded, {}, {});
            terminal = Terminal::success;
            success_result = std::move(outcome.value());
        } else if (outcome.is_cancelled()) {
            state->finish_locked(TaskStatus::cancelled, "task.cancelled", {});
            terminal = Terminal::cancelled;
            failure.request_id = state->request.request_id;
            failure.code = "task.cancelled";
            failure.message = outcome.cancelled().stage;
            failure.cancelled = true;
        } else {
            std::string error_code = "algorithm.error";
            if (!outcome.error().diagnostics.empty()) {
                error_code = outcome.error().diagnostics.front().code;
            }
            state->snapshot.diagnostics = outcome.error().diagnostics;
            state->finish_locked(TaskStatus::failed, error_code, {});
            terminal = Terminal::failure;
            failure.request_id = state->request.request_id;
            failure.code = error_code;
            failure.message = "algorithm failed";
            failure.cancelled = false;
        }
    }
    if (submission.publisher == nullptr) {
        return;
    }
    if (terminal == Terminal::success) {
        submission.publisher->publish_success(success_result);
    } else {
        submission.publisher->publish_failure(failure);
    }
}

} // namespace pwb::workflow
