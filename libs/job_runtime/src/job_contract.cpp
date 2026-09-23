// CONV-30 — job contract implementations (Wave D target split): the
// cancellation token, the JobContext progress plumbing and the JobHandle
// query/cancel/wait surface, moved out of job_scheduler.cpp so the
// vocabulary layer (pwb_job_contracts) links without the scheduler.
// Behaviour is unchanged verbatim; see job_contract.hpp for the frozen
// contracts.

#include "pwb/job_runtime/job_contract.hpp"

#include <algorithm>
#include <chrono>
#include <condition_variable>
#include <mutex>
#include <utility>

namespace pwb::job {

namespace {

// Progress/cancel observers must never kill a task (Python logs; the core
// has no logger seam, swallowing is the documented contract).
void invoke_on_cancel(const JobSpec& spec) noexcept {
    if (!spec.on_cancel) return;
    try {
        spec.on_cancel();
    } catch (...) {
    }
}

}  // namespace

// ------------------------------------------------------- cancellation --

bool CancellationToken::sleep_interruptible(double seconds) const {
    if (seconds <= 0.0) return source_->stop_requested();
    std::mutex m;
    std::condition_variable cv;
    std::stop_callback<std::function<void()>> callback(
        source_->get_token(), [&] {
            std::lock_guard<std::mutex> guard(m);
            cv.notify_all();
        });
    const auto deadline = std::chrono::steady_clock::now() +
                          std::chrono::duration<double>(seconds);
    std::unique_lock<std::mutex> lock(m);
    while (!source_->stop_requested()) {
        const double remaining =
            std::chrono::duration<double>(deadline -
                                          std::chrono::steady_clock::now())
                .count();
        if (remaining <= 0.0) return false;
        // 50 ms poll-granularity ceiling (Python parity) so a missed wakeup
        // can never hang the caller longer than one tick.
        cv.wait_for(lock, std::chrono::duration<double>(std::min(0.05, remaining)));
    }
    return true;
}

void CancellationToken::check_cancelled() const {
    if (source_->stop_requested()) throw JobCancelled("");
}

void JobContext::report_progress(double done, std::optional<double> total,
                                 std::string message) {
    double ratio = done;
    if (total.has_value() && *total != 0.0) ratio = done / *total;
    if (ratio < 0.0) ratio = 0.0;
    if (ratio > 1.0) ratio = 1.0;
    if (progress_sink_) {
        try {
            progress_sink_(ratio, message);
        } catch (...) {
            // progress must never kill a task (Python parity)
        }
    }
}

// ----------------------------------------------------------- JobHandle --

JobHandle JobContext::self_handle() const {
    // Definition deferred here because JobHandle's constructor is private
    // with JobScheduler as friend.
    return JobHandle(self_cell_);
}

std::string JobHandle::job_id() const {
    if (cell_ == nullptr) return {};
    std::lock_guard<std::mutex> guard(cell_->mutex);
    return cell_->snapshot.job_id;
}

JobState JobHandle::raw_state() const {
    std::lock_guard<std::mutex> guard(cell_->mutex);
    return cell_->snapshot.state;
}

bool JobHandle::cancel() const {
    if (cell_ == nullptr) return false;
    bool queued_cancel = false;
    {
        std::lock_guard<std::mutex> guard(cell_->mutex);
        JobSnapshot& snap = cell_->snapshot;
        if (is_terminal(snap.state)) return false;
        if (snap.state == JobState::queued) {
            // Queued drop: terminal immediately (Python parity). The heap
            // entry is dropped lazily by the workers — cell state is
            // authoritative.
            snap.cancel_requested = true;
            snap.finished_at = cell_->clock ? cell_->clock() : 0.0;
            snap.state = JobState::cancelled;
            queued_cancel = true;
        } else {
            if (snap.state == JobState::running) snap.state = JobState::cancelling;
            // Armed-job cancel also records cancel_requested — the
            // "cancelling" presentation depends on it (V7 §12 parity).
            snap.cancel_requested = true;
            cell_->token.cancel();
            return true;
        }
    }
    cell_->terminal_cv.notify_all();
    if (queued_cancel) {
        // Queued cancels unwind on_cancel synchronously on the caller
        // thread, outside the cell lock (Python parity).
        if (cell_->spec) invoke_on_cancel(*cell_->spec);
    }
    return true;
}

void JobHandle::wait() const {
    if (cell_ == nullptr) return;
    std::unique_lock<std::mutex> lock(cell_->mutex);
    if (!is_terminal(cell_->snapshot.state) &&
        cell_->worker_id.load() == std::this_thread::get_id()) {
        throw std::logic_error(
            "JobHandle::wait() from the job's own worker thread would "
            "deadlock");
    }
    cell_->terminal_cv.wait(lock, [&] {
        return is_terminal(cell_->snapshot.state);
    });
}

bool JobHandle::wait_for(double timeout_seconds) const {
    if (cell_ == nullptr) return true;
    const auto deadline = std::chrono::steady_clock::now() +
                          std::chrono::duration<double>(timeout_seconds);
    std::unique_lock<std::mutex> lock(cell_->mutex);
    return cell_->terminal_cv.wait_until(lock, deadline, [&] {
        return is_terminal(cell_->snapshot.state);
    });
}

JobSnapshot JobHandle::snapshot() const {
    if (cell_ == nullptr) return {};
    std::lock_guard<std::mutex> guard(cell_->mutex);
    return cell_->snapshot;
}

}  // namespace pwb::job
