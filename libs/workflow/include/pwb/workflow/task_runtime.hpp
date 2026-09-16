#pragma once

// Minimal task runtime for pwb::science algorithms: a single worker thread
// (resource budget: max 2 jobs per build/test gate), the frozen task state
// machine queued/running/succeeded/failed/cancelled, cancellation through
// std::stop_token, and result publication via IResultPublisherV1.
//
// Invariants (tested in tests/cpp/science/task_runtime_test.cpp):
//  - legal transitions only: queued->running->{succeeded|failed|cancelled}
//    and queued->cancelled;
//  - a cancelled or failed task NEVER publishes success;
//  - exactly one publish_* per request (failure on cancel/error);
//  - destroying the runtime drains the queue (pending tasks still run to
//    completion) and joins the worker — no detached publishes. Callers that
//    do not want a queued task executed must cancel() it first.

#include <condition_variable>
#include <memory>
#include <mutex>
#include <optional>
#include <queue>
#include <stop_token>
#include <string>
#include <thread>
#include <vector>

#include <pwb/science/algorithm.hpp>
#include <pwb/science/publisher.hpp>

namespace pwb::workflow {

enum class TaskStatus : std::uint8_t { queued, running, succeeded, failed, cancelled };

[[nodiscard]] inline const char* to_string(TaskStatus status) noexcept {
    switch (status) {
    case TaskStatus::queued:
        return "queued";
    case TaskStatus::running:
        return "running";
    case TaskStatus::succeeded:
        return "succeeded";
    case TaskStatus::failed:
        return "failed";
    case TaskStatus::cancelled:
        return "cancelled";
    }
    return "?";
}

[[nodiscard]] inline bool is_terminal(TaskStatus status) noexcept {
    return status == TaskStatus::succeeded || status == TaskStatus::failed ||
           status == TaskStatus::cancelled;
}

struct TaskSnapshot {
    std::string task_id;
    std::string request_id;
    std::string algorithm_id;
    TaskStatus status{TaskStatus::queued};
    std::string error_code; // terminal failures only
    std::optional<science::ProgressReport> progress;
    std::vector<science::Diagnostic> diagnostics;
};

class TaskRuntime;

class TaskHandle {
public:
    TaskHandle() = default;
    // Requests cancellation; no-op once terminal (idempotent).
    void cancel();
    // Blocks until the task reaches a terminal state.
    void wait();
    [[nodiscard]] TaskSnapshot snapshot() const;
    [[nodiscard]] bool valid() const noexcept { return state_ != nullptr; }

private:
    friend class TaskRuntime;
    struct State;
    explicit TaskHandle(std::shared_ptr<State> state) : state_(std::move(state)) {}
    std::shared_ptr<State> state_;
};

class TaskRuntime {
public:
    TaskRuntime();
    ~TaskRuntime();

    TaskRuntime(const TaskRuntime&) = delete;
    TaskRuntime& operator=(const TaskRuntime&) = delete;

    // Queues one algorithm execution. An empty request.request_id gets a
    // generated id. A null publisher is allowed (no publication happens).
    // Submits after shutdown begin are rejected with a failed handle
    // (error_code "runtime.shutdown").
    [[nodiscard]] TaskHandle submit(std::shared_ptr<science::IAlgorithm> algorithm,
                                    science::AlgorithmRequestV1 request,
                                    std::shared_ptr<science::IResultPublisherV1> publisher);

    // Blocks until the queue is empty and no task is running.
    void wait_idle();

private:
    struct Submission {
        std::shared_ptr<TaskHandle::State> state;
        std::shared_ptr<science::IAlgorithm> algorithm;
        science::AlgorithmRequestV1 request;
        std::shared_ptr<science::IResultPublisherV1> publisher;
    };

    void worker_loop();
    void execute(Submission& submission);

    std::mutex mutex_;
    std::condition_variable work_cv_;
    std::condition_variable idle_cv_;
    std::queue<Submission> queue_;
    std::size_t active_{0};
    bool shutdown_{false};
    std::jthread worker_;
};

} // namespace pwb::workflow
