#pragma once

// Minimal task runtime for pwb::science algorithms: a single worker thread
// (resource budget: max 2 jobs per build/test gate), the frozen task state
// machine queued/running/publishing/{succeeded|failed|cancelled},
// cancellation through std::stop_token, and result publication via
// IResultPublisherV1.
//
// v3 invariants (docs/development/cpp-science/v3-contracts.md; tested in
// tests/cpp/science/task_runtime_test.cpp):
//  - legal transitions only: queued->running->publishing->terminal and
//    queued->publishing->terminal (cancel observed while queued);
//  - PUBLISH BEFORE TERMINAL: with a publisher attached, the publish_* call
//    happens before the terminal state is set. snapshot()==succeeded implies
//    publish_success returned; a publish that throws ends failed with the
//    stable code "publisher.publish_threw" (success publish) or appends the
//    diagnostic "publisher.publish_failure_threw" (failure publish, the
//    algorithm outcome stands). At most one publish_* attempt — never a
//    retry, never a duplicate;
//  - wait() returns only after publication completed or its failure is
//    recorded. Calling wait() from the worker thread on a not-yet-terminal
//    task (e.g. from inside a publisher) is detected and throws
//    std::logic_error instead of deadlocking;
//  - publishers run without the task lock held: snapshot() is safely
//    reentrant from publish callbacks (they observe status==publishing);
//  - a null publisher is the pure-compute mode: no publishing phase,
//    terminal success means the computation succeeded. Production mode
//    (publisher attached) terminal success means computation AND publication
//    succeeded — see TaskSnapshot::published;
//  - cancellation linearization (L0..L4, v3-contracts.md §1): cancel while
//    queued never runs the algorithm; cancel during run is honoured through
//    the stop token only; once run() returns, the outcome is irrevocable and
//    late cancels are no-ops; a task that published success is never
//    reported cancelled and a cancelled task never leaves a success result;
//  - destroying the runtime drains the queue (pending tasks still run to
//    completion, publications included) and joins the worker — no detached
//    publishes. Hosts that want an explicit close call shutdown() first;
//    submits after shutdown began are rejected with a failed handle
//    (error_code "runtime.shutdown", never published — the request was
//    never accepted). shutdown() and the destructor must be serialized
//    (same thread); concurrent shutdown() from multiple threads is not
//    supported.

#include <atomic>
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

enum class TaskStatus : std::uint8_t {
    queued,
    running,
    publishing, // publish_* in flight (publisher mode only)
    succeeded,
    failed,
    cancelled
};

[[nodiscard]] inline const char* to_string(TaskStatus status) noexcept {
    switch (status) {
    case TaskStatus::queued:
        return "queued";
    case TaskStatus::running:
        return "running";
    case TaskStatus::publishing:
        return "publishing";
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
    bool published{false}; // publish_* completed without throwing
                           // (always false in pure-compute mode)
};

class TaskRuntime;

class TaskHandle {
public:
    TaskHandle() = default;
    // Requests cancellation; no-op once terminal (idempotent). Effective
    // only while queued or inside run() — once run() returns, the outcome is
    // irrevocable (v3-contracts.md L2/L3).
    void cancel();
    // Blocks until the task reaches a terminal state; with a publisher
    // attached that means publication completed or its failure was recorded.
    // Throws std::logic_error when called from the worker thread on a task
    // that is not terminal yet (self-wait / cross-task wait from a
    // publisher) — such a wait could only be satisfied by the caller itself.
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
    // generated id. A null publisher is allowed (pure-compute mode: no
    // publication happens). Submits after shutdown begin are rejected with a
    // failed handle (error_code "runtime.shutdown", nothing published).
    [[nodiscard]] TaskHandle submit(std::shared_ptr<science::IAlgorithm> algorithm,
                                    science::AlgorithmRequestV1 request,
                                    std::shared_ptr<science::IResultPublisherV1> publisher);

    // Blocks until the queue is empty and no task is running. Throws
    // std::logic_error when called from the worker thread (e.g. from inside
    // a publisher) — the idle condition can only be reached after that
    // caller returns.
    void wait_idle();

    // Explicit close: stop accepting submits, drain queued tasks (each one
    // still runs to a published terminal state) and join the worker.
    // Idempotent; safe to call again from the destructor's thread. Hosts
    // close windows/widgets only after shutdown() returned.
    void shutdown();

private:
    // TaskHandle (and its nested State, which shares TaskHandle's access
    // rights) reads WorkerIdentity to detect worker-thread waits.
    friend class TaskHandle;

    struct Submission {
        std::shared_ptr<TaskHandle::State> state;
        std::shared_ptr<science::IAlgorithm> algorithm;
        science::AlgorithmRequestV1 request;
        std::shared_ptr<science::IResultPublisherV1> publisher;
    };

    // Shared with every TaskHandle::State so waits can detect the worker
    // thread without dereferencing the runtime (handles may outlive it).
    struct WorkerIdentity {
        std::atomic<std::thread::id> id{std::thread::id{}};
    };

    void worker_loop();
    void execute(Submission& submission);
    static bool begin_publishing(TaskHandle::State& state);

    std::mutex mutex_;
    std::condition_variable work_cv_;
    std::condition_variable idle_cv_;
    std::queue<Submission> queue_;
    std::size_t active_{0};
    bool shutdown_{false};
    bool joined_{false};
    std::shared_ptr<WorkerIdentity> worker_identity_ =
        std::make_shared<WorkerIdentity>();
    std::jthread worker_;
};

} // namespace pwb::workflow
