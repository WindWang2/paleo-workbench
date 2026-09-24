// workflow_scheduler.cpp — see include/pwb/closure_workflow/workflow_scheduler.hpp.

#include <pwb/closure_workflow/workflow_scheduler.hpp>

#include <stdexcept>
#include <utility>

namespace pwb::closure_workflow {

std::future<WorkflowRunOutcome> WorkflowScheduler::submit(
    const std::string& run_id, const pwb::workflow_engine::RunContext* context,
    const Options& options) {
    // A missing run raises StoreError here, before any body is submitted
    // (engine.py L376 parity: the title lookup used to do the same).
    (void)store_.load(run_id);

    auto engine_token = std::make_shared<pwb::workflow_engine::CancelToken>();

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
    // The observable wait surface the retired JobHandle provided. The
    // promise is boxed in a shared_ptr: the submitter's std::function
    // body must stay copyable.
    auto promise = std::make_shared<std::promise<WorkflowRunOutcome>>();
    std::future<WorkflowRunOutcome> future = promise->get_future();

    auto body = [this, run_id, context, reverify, use_cache, resume,
                 weak_token, deregister, promise,
                 done]() mutable {
        // Runs on the submitter's background thread; every exit path
        // settles the promise exactly once and deregisters the side
        // channel (epoch-matched).
        try {
            auto token = weak_token.lock();
            if (token == nullptr) {
                throw std::runtime_error("workflow scheduler token lost");
            }
            pwb::workflow_engine::RunOptions run_options;
            run_options.external_cancel = token.get();
            run_options.reverify_cache = reverify;
            run_options.use_cache = use_cache;
            const pwb::workflow_spec::WorkflowRun result =
                resume ? engine_.resume(run_id, context, run_options)
                       : engine_.run(run_id, context, run_options);
            deregister();
            WorkflowRunOutcome outcome;
            outcome.run_id = result.run_id;
            outcome.state = pwb::workflow_spec::to_string(result.state);
            outcome.failed =
                result.state == pwb::workflow_spec::RunState::failed;
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
            promise->set_value(std::move(outcome));
        } catch (...) {
            deregister();
            promise->set_exception(std::current_exception());
        }
    };
    submitter_(std::move(body));
    {
        // Register only after the submitter accepted the body — a
        // throwing submitter leaves no stale entry, and a cancel()
        // racing the claim window hits deregister's erase. A run that
        // already reached terminal state (done) is NOT registered
        // (#1449).
        std::lock_guard<std::mutex> lock(mutex_);
        if (!done->load(std::memory_order_acquire)) {
            pending_[run_id] = engine_token;
        }
    }
    return future;
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
