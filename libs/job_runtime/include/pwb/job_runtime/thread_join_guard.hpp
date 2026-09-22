#pragma once

// RAII join for sidecar poll threads (cancel bridges, progress watchers).
//
// A std::thread that is still joinable when destroyed calls
// std::terminate(). Callers that spawn a sidecar thread and join it after a
// guarded call (typically: poll-cancel bridge around a long read) terminate
// the process when that call throws, because the join is skipped during stack
// unwinding. ThreadJoinGuard closes that gap: it stores the done-flag and
// joins on destruction, so both the normal path and every unwind path end
// with a joined thread. The explicit store+join sequence used by callers
// stays valid — the guard's destructor is a no-op once the thread is no
// longer joinable.

#include <atomic>
#include <thread>

namespace pwb::job {

class ThreadJoinGuard {
public:
    ThreadJoinGuard(std::atomic<bool>& done, std::thread& thread)
        : done_(done), thread_(thread) {}

    ~ThreadJoinGuard() {
        done_.store(true, std::memory_order_relaxed);
        if (thread_.joinable()) {
            thread_.join();
        }
    }

    ThreadJoinGuard(const ThreadJoinGuard&) = delete;
    ThreadJoinGuard& operator=(const ThreadJoinGuard&) = delete;

private:
    std::atomic<bool>& done_;
    std::thread& thread_;
};

}  // namespace pwb::job
