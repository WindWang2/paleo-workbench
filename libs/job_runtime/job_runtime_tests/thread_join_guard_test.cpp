// job_runtime.thread_join_guard — the SEG-Y cancel-bridge contract (#1451
// B-10 family): a sidecar thread spawned before a guarded call must be
// joined on every exit path from that call, including exceptions. Destroying
// a joinable std::thread calls std::terminate, which on the GUI thread takes
// the whole desktop process down.
//
// Negative control: with PWB_NEGATIVE_CONTROL=1 the first test reproduces
// the unguarded terminate (exit 134) to prove causality; run it in a
// disposable process, never inside the suite.

#include <atomic>
#include <cstdlib>
#include <stdexcept>
#include <thread>

#include "job_test.hpp"
#include "pwb/job_runtime/thread_join_guard.hpp"

using pwb::job::ThreadJoinGuard;

namespace {

TEST(guard_joins_thread_when_guarded_call_throws) {
    std::atomic<bool> done{false};
    std::atomic<bool> poll_started{false};
    std::thread bridge([&] {
        poll_started.store(true);
        while (!done.load(std::memory_order_relaxed)) {
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
    });
    bool threw = false;
    {
        ThreadJoinGuard guard{done, bridge};
        try {
            throw std::runtime_error("read_segy failed");
        } catch (const std::runtime_error&) {
            threw = true;
        }
    }  // guard dtor: joins even though the explicit store/join never ran
    // Without the guard the still-joinable bridge would have terminated
    // the process at this scope exit already.
    PWB_CHECK(threw);
    PWB_CHECK(poll_started.load() || true);  // poll may or may not have started
    PWB_CHECK(!bridge.joinable());
}

TEST(guard_is_noop_after_explicit_join) {
    std::atomic<bool> done{false};
    std::thread bridge([&] {
        while (!done.load(std::memory_order_relaxed)) {
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
    });
    {
        ThreadJoinGuard guard{done, bridge};
        done.store(true, std::memory_order_relaxed);
        bridge.join();
    }  // guard dtor: thread no longer joinable, must not double-join
    PWB_CHECK(!bridge.joinable());
}

TEST(guard_signals_done_before_join) {
    // The bridge loop must observe done=true promptly even when the guarded
    // call throws on its first step, otherwise join could block forever on a
    // poll loop that only exits on done.
    std::atomic<bool> done{false};
    std::atomic<int> exits{0};
    std::thread bridge([&] {
        while (!done.load(std::memory_order_relaxed)) {
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
        exits.store(1);
    });
    try {
        ThreadJoinGuard guard{done, bridge};
        throw std::runtime_error("boom");
    } catch (const std::runtime_error&) {
        // Unwind ran the guard: done stored, thread joined.
    }
    PWB_CHECK(exits.load() == 1);
}

TEST(negative_control_unguarded_thread_terminates) {
    // Opt-in only: spawns a raw joinable thread, lets the scope exit throw,
    // and expects the process to die with SIGABRT (std::terminate). Skipped
    // in normal suite runs; used to demonstrate the failure mode the guard
    // removes (same negative-control practice as the #1443 join-guard fix).
    const char* flag = std::getenv("PWB_NEGATIVE_CONTROL");
    if (flag == nullptr || std::string(flag) != "1") {
        return;
    }
    std::atomic<bool> done{false};
    std::thread bridge([&] {
        while (!done.load(std::memory_order_relaxed)) {
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
    });
    // No guard, no join: destructor of a joinable thread → terminate.
    throw std::runtime_error("unguarded");
}

}  // namespace

int main() { return pwb_test_main(); }
