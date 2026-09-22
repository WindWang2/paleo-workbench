// workflow_scheduler.cpp — see include/pwb/closure_workflow/workflow_scheduler.hpp.

#include <pwb/closure_workflow/workflow_scheduler.hpp>

#include <chrono>
#include <stdexcept>
#include <thread>
#include <utility>

namespace pwb::closure_workflow {

pwb::job::JobHandle WorkflowScheduler::submit(
    const std::string& run_id, const pwb::workflow_engine::RunContext* context,
    const Options& options) {
    // Task title from the stored spec (engine.py L376: `workflow:<name>
    // (<run_id>)`); a missing run raises StoreError here, before any job
    // is queued.
    const pwb::workflow_spec::WorkflowRun stored = store_.load(run_id);
    std::string title =
        "workflow:" + stored.workflow.workflow_id + " (" + run_id + ")";

    auto engine_token = std::make_shared<pwb::workflow_engine::CancelToken>();

    pwb::job::JobSpec spec;
    spec.kind = "background.compute";
    spec.title = std::move(title);
    spec.task_key = options.task_key;
    spec.priority = options.priority;
    const bool reverify = options.reverify_cache;
    const bool use_cache = options.use_cache;
    const bool resume = options.resume;
    std::weak_ptr<pwb::workflow_engine::CancelToken> weak_token = engine_token;
    // Registration epoch (#1449): a fast run can reach its terminal
    // erase BEFORE submit() registers the side channel — the stale
    // entry then survived forever and cancel() reported success for an
    // already-terminal run. The done latch (set under the mutex in the
    // body's deregister) closes that window both ways.
    auto done = std::make_shared<std::atomic<bool>>(false);
    const auto deregister = [this, run_id, engine_token, done]() {
        std::lock_guard<std::mutex> lock(mutex_);
        auto it = pending_.find(run_id);
        if (it != pending_.end() && it->second == engine_token) {
            pending_.erase(it);
        }
        done->store(true, std::memory_order_release);
    };
    // A job cancelled while QUEUED reaches its terminal state without
    // ever running spec.run — deregister the side channel there too.
    spec.on_cancel = [this, run_id, done, engine_token]() {
        std::lock_guard<std::mutex> lock(mutex_);
        // R2-20: same epoch guard as deregister — a queued cancel of an
        // OLD submission racing a fresh submit() of the same run_id must
        // not erase the NEW registration (cancel then reports false for a
        // live run whose token becomes unreachable).
        const auto it = pending_.find(run_id);
        if (it != pending_.end() && it->second == engine_token) {
            pending_.erase(it);
        }
        done->store(true, std::memory_order_release);
    };
    spec.run = [this, run_id, context, reverify, use_cache, resume,
                weak_token, done, deregister](pwb::job::JobContext& ctx)
        -> std::any {
        // Scheduler-side cooperative cancellation propagates into the
        // engine token: the watcher flips the engine flag when the job
        // token cancels (the _SyncedToken parity; 20 ms poll granularity —
        // Python duck-types the check into every token poll).
        auto token = weak_token.lock();
        if (token == nullptr) {
            throw std::runtime_error("workflow scheduler token lost");
        }
        std::atomic<bool> finished{false};
        std::thread watcher([&ctx, token, &finished] {
            while (!finished.load(std::memory_order_acquire)) {
                if (ctx.token().is_cancelled()) {
                    token->cancel();
                    return;
                }
                std::this_thread::sleep_for(std::chrono::milliseconds(20));
            }
        });
        try {
            pwb::workflow_engine::RunOptions run_options;
            run_options.external_cancel = token.get();
            run_options.reverify_cache = reverify;
            run_options.use_cache = use_cache;
            const pwb::workflow_spec::WorkflowRun result =
                resume ? engine_.resume(run_id, context, run_options)
                       : engine_.run(run_id, context, run_options);
            finished.store(true, std::memory_order_release);
            watcher.join();
            // Deregister the side channel: the run is terminal
            // in-process (epoch-matched; see the done latch above).
            deregister();
            WorkflowRunOutcome outcome;
            outcome.run_id = result.run_id;
            outcome.state = pwb::workflow_spec::to_string(result.state);
            outcome.failed = result.state ==
                             pwb::workflow_spec::RunState::failed;
            // WorkflowRun carries no top-level error; surface the first
            // failed node's error (Python's on_fail receives exceptions,
            // the run itself stays the authority).
            if (outcome.failed) {
                for (const auto& [node_id, node_run] : result.node_runs) {
                    if (node_run.error.has_value()) {
                        outcome.error = *node_run.error;
                        break;
                    }
                }
            }
            return std::any(outcome);
        } catch (...) {
            finished.store(true, std::memory_order_release);
            watcher.join();
            deregister();
            throw;
        }
    };
    pwb::job::JobHandle handle = scheduler_.submit(std::move(spec));
    {
        // Register only after submit succeeded — a throwing submit
        // (duplicate.task_key / shutdown) leaves no stale entry, and a
        // cancel() racing the claim window hits on_cancel's erase. A run
        // that already reached terminal state (done) is NOT registered
        // (#1449).
        std::lock_guard<std::mutex> lock(mutex_);
        if (!done->load(std::memory_order_acquire)) {
            pending_[run_id] = engine_token;
        }
    }
    return handle;
}

bool WorkflowScheduler::cancel(const std::string& run_id) {
    std::shared_ptr<pwb::workflow_engine::CancelToken> token;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        const auto it = pending_.find(run_id);
        if (it == pending_.end()) return false;
        token = it->second;
    }
    if (token != nullptr) token->cancel();
    return true;
}

}  // namespace pwb::closure_workflow
