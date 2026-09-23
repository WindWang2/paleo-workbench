// CONV-30 — BoundedJobScheduler implementation. Port of
// paleo_workbench/runtime/task_scheduler.py with the frozen contracts (see
// job_scheduler.hpp). Caller-visible message strings keep the Python
// wording verbatim (including the #1224 supersede text).
//
// Lock discipline (never reversed): scheduler mutex_ -> cell->mutex. Job
// callbacks, admission hooks and interactive predicates run per the Python
// contracts; predicate evaluation happens under mutex_ exactly like
// Python's _task_is_interactive, admission hooks WITHOUT any lock.
// Cell state is read/written under cell->mutex except in paths that hold
// both locks (finish/claim).

#include "pwb/job_runtime/job_scheduler.hpp"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdio>
#include <exception>
#include <utility>

#include "pwb/job_runtime/job_categories.hpp"
#include "pwb/job_runtime/governance.hpp"

namespace pwb::job {

namespace {

double default_clock() {
    const auto now = std::chrono::steady_clock::now().time_since_epoch();
    return std::chrono::duration<double>(now).count();
}

std::string make_job_id() {
    static std::atomic<std::uint64_t> counter{0};
    // 12 hex chars, shaped like Python's uuid4().hex[:12].
    char buffer[16];
    std::snprintf(buffer, sizeof(buffer), "%012llx",
                  static_cast<unsigned long long>(counter.fetch_add(1) + 1));
    return buffer;
}

// Progress/cancel observers must never kill a task (Python logs; the core
// has no logger seam, swallowing is the documented contract).
void invoke_on_cancel(const JobSpec& spec) noexcept {
    if (!spec.on_cancel) return;
    try {
        spec.on_cancel();
    } catch (...) {
    }
}

[[nodiscard]] JobState cell_state(const std::shared_ptr<JobCell>& cell) {
    std::lock_guard<std::mutex> guard(cell->mutex);
    return cell->snapshot.state;
}

}  // namespace

// -------------------------------------------------------- JobScheduler --

JobScheduler::JobScheduler(Options options, Clock clock)
    : options_(options),
      clock_(clock ? std::move(clock) : default_clock),
      // Documented divergence from Python (task_scheduler.py uses
      // ~/.paleo_workbench/heavy-tasks): the C++ runtime defaults to a
      // temp-dir root so tests never touch the user profile; hosts set the
      // product root via set_work_root.
      work_root_(std::filesystem::temp_directory_path() / "pwb-job-runtime") {
    if (options_.max_workers < 1) {
        throw std::invalid_argument(
            "max_workers must be >= 1 (I/O-heavy default is 1)");
    }
    if (options_.interactive_workers < 0) {
        throw std::invalid_argument("interactive_workers must be >= 0");
    }
    last_rekey_ = clock_();
    // Bounded by construction: exactly worker_count() lanes exist for the
    // scheduler's lifetime; no other code path spawns threads.
    workers_.reserve(static_cast<std::size_t>(worker_count()));
    try {
        for (int lane = 0; lane < worker_count(); ++lane) {
            workers_.emplace_back([this, lane] { worker_loop(lane); });
        }
    } catch (...) {
        // Partial construction: stop and join the lanes already spawned so
        // the jthread members never outlive the loop logic they capture.
        shutdown(true, std::nullopt);
        throw;
    }
}

JobScheduler::~JobScheduler() {
    // Drain-and-join (TaskRuntime v3 precedent): Python used daemon
    // threads, C++ cannot abandon threads — destruction cancels queued
    // jobs, arms running tokens and joins. Hosts wanting a bounded close
    // call shutdown(wait, timeout) first.
    shutdown(true, std::nullopt);
}

std::shared_ptr<JobCell> JobScheduler::find_active_by_key_locked(
    const std::string& key) const {
    for (const auto& [id, cell] : cells_) {
        std::lock_guard<std::mutex> cell_guard(cell->mutex);
        const JobSnapshot& snap = cell->snapshot;
        if (snap.task_key == key &&
            (snap.state == JobState::queued || snap.state == JobState::running ||
             snap.state == JobState::cancelling)) {
            return cell;
        }
    }
    return nullptr;
}

JobHandle JobScheduler::submit(JobSpec spec) {
    const std::string job_id = make_job_id();
    auto cell = std::make_shared<JobCell>();
    cell->snapshot.job_id = job_id;
    cell->snapshot.kind = spec.kind;
    cell->snapshot.title = spec.title;
    cell->snapshot.task_key = spec.task_key.empty() ? job_id : spec.task_key;
    cell->snapshot.submitted_at = clock_();
    cell->clock = clock_;
    // The spec must be live before the cell becomes visible to workers.
    cell->spec = std::make_unique<JobSpec>(std::move(spec));

    std::function<void()> superseded_cancel;
    {
        std::lock_guard<std::mutex> guard(mutex_);
        if (shutdown_) {
            throw JobSubmitError("runtime.shutdown", "scheduler is shut down");
        }
        if (!cell->snapshot.task_key.empty()) {
            std::shared_ptr<JobCell> existing =
                find_active_by_key_locked(cell->snapshot.task_key);
            if (existing != nullptr) {
                if (cell_state(existing) == JobState::queued) {
                    // #1224 supersede: a resubmit against a still-QUEUED job
                    // replaces it instead of erroring — a cancelled request
                    // must never make the NEXT request appear to hang. The
                    // old job's on_cancel unwinds exactly like an explicit
                    // cancel (R2#6).
                    {
                        std::lock_guard<std::mutex> cell_guard(existing->mutex);
                        existing->snapshot.cancel_requested = true;
                        existing->snapshot.finished_at = clock_();
                        existing->snapshot.state = JobState::cancelled;
                    }
                    existing->terminal_cv.notify_all();
                    superseded_cancel = existing->spec->on_cancel;
                } else {
                    // Python wording verbatim, including the key prefix:
                    // running vs cancelling differ in the detail text
                    // (task_scheduler.py:326-334 — the Chinese variant is
                    // only for a RUNNING predecessor).
                    const bool running =
                        cell_state(existing) == JobState::running;
                    throw JobSubmitError(
                        "duplicate.task_key",
                        "task with key '" + cell->snapshot.task_key + "' " +
                            (running
                                 ? "正在运行且尚未退出（已请求取消的旧任务需先实际结束）"
                                 : "is already queued or running"));
                }
            }
        }
        cells_[job_id] = cell;
        heap_.push_back({cell->spec->priority, seq_++, job_id});
        std::push_heap(heap_.begin(), heap_.end(), queue_order);
    }
    wakeup_cv_.notify_all();
    if (superseded_cancel) {
        try {
            superseded_cancel();
        } catch (...) {
            // A superseded job's unwind failure must not break the submit.
        }
    }
    return JobHandle(cell);
}

bool JobScheduler::cancel(const std::string& job_id) {
    std::shared_ptr<JobCell> cell;
    {
        std::lock_guard<std::mutex> guard(mutex_);
        auto it = cells_.find(job_id);
        if (it == cells_.end()) return false;
        cell = it->second;
    }
    return JobHandle(cell).cancel();
}

bool JobScheduler::boost(const std::string& job_id,
                         std::optional<int> priority) {
    {
        std::lock_guard<std::mutex> guard(mutex_);
        auto it = cells_.find(job_id);
        if (it == cells_.end()) return false;
        if (cell_state(it->second) != JobState::queued) return false;
        const int target =
            priority.value_or(it->second->spec->priority + 10);
        for (QueueEntry& entry : heap_) {
            if (entry.job_id == job_id) {
                entry.priority = target;
                entry.seq = seq_++;  // newest-first inside its new level
            }
        }
        std::make_heap(heap_.begin(), heap_.end(), queue_order);
    }
    wakeup_cv_.notify_all();
    return true;
}

int JobScheduler::boost_matching(const std::string& kind,
                                 std::optional<int> priority) {
    std::vector<std::string> ids;
    {
        std::lock_guard<std::mutex> guard(mutex_);
        for (const auto& [id, cell] : cells_) {
            if (cell_state(cell) == JobState::queued &&
                cell->snapshot.kind == kind) {
                ids.push_back(id);
            }
        }
    }
    for (const std::string& id : ids) boost(id, priority);
    return static_cast<int>(ids.size());
}

std::optional<JobSnapshot> JobScheduler::snapshot(
    const std::string& job_id) const {
    std::lock_guard<std::mutex> guard(mutex_);
    auto it = cells_.find(job_id);
    if (it == cells_.end()) return std::nullopt;
    std::lock_guard<std::mutex> cell_guard(it->second->mutex);
    return it->second->snapshot;
}

JobHandle JobScheduler::handle(const std::string& job_id) const {
    std::lock_guard<std::mutex> guard(mutex_);
    auto it = cells_.find(job_id);
    if (it == cells_.end()) return {};
    return JobHandle(it->second);
}

std::vector<JobSnapshot> JobScheduler::statuses() const {
    std::vector<JobSnapshot> out;
    std::lock_guard<std::mutex> guard(mutex_);
    out.reserve(cells_.size());
    for (const auto& [id, cell] : cells_) {
        std::lock_guard<std::mutex> cell_guard(cell->mutex);
        out.push_back(cell->snapshot);
    }
    return out;
}

int JobScheduler::active_count() const {
    std::lock_guard<std::mutex> guard(mutex_);
    int count = 0;
    for (const auto& [id, cell] : cells_) {
        const JobState state = cell_state(cell);
        if (state == JobState::running || state == JobState::cancelling) ++count;
    }
    return count;
}

bool JobScheduler::idle() const {
    std::lock_guard<std::mutex> guard(mutex_);
    if (running_ != 0) return false;
    for (const auto& [id, cell] : cells_) {
        if (cell_state(cell) == JobState::queued) return false;
    }
    return true;
}

std::filesystem::path JobScheduler::work_dir(const std::string& job_id) {
    std::lock_guard<std::mutex> guard(mutex_);
    auto it = work_dirs_.find(job_id);
    if (it != work_dirs_.end()) return it->second;
    std::filesystem::path dir = work_root_ / job_id;
    std::error_code ec;
    std::filesystem::create_directories(dir, ec);
    work_dirs_[job_id] = dir;
    return dir;
}

void JobScheduler::release_work_dir(const std::string& job_id) {
    std::filesystem::path dir;
    {
        std::lock_guard<std::mutex> guard(mutex_);
        auto it = work_dirs_.find(job_id);
        if (it == work_dirs_.end()) return;
        dir = std::move(it->second);
        work_dirs_.erase(it);
    }
    std::error_code ec;
    std::filesystem::remove_all(dir, ec);
}

void JobScheduler::set_admission(AdmissionHook hook) {
    {
        std::lock_guard<std::mutex> guard(mutex_);
        admission_ = std::move(hook);
    }
    wakeup_cv_.notify_all();
}

void JobScheduler::set_interactive_predicate(InteractivePredicate predicate) {
    std::lock_guard<std::mutex> guard(mutex_);
    interactive_predicate_ = std::move(predicate);
}

void JobScheduler::set_work_root(std::filesystem::path root) {
    std::lock_guard<std::mutex> guard(mutex_);
    work_root_ = std::move(root);
}

int JobScheduler::aged_priority(int base_priority, double wait_s,
                                const Options& options) {
    const double wait = std::max(0.0, wait_s);
    const int aging =
        static_cast<int>(wait / options.aging_interval_s) * options.aging_step;
    return base_priority + std::min(aging, options.aging_max_boost);
}

int JobScheduler::effective_priority(const JobCell& cell) const {
    // Base priority plus bounded aging so background work is not starved
    // (Python _effective_priority parity — see aged_priority).
    return aged_priority(cell.spec->priority,
                         clock_() - cell.snapshot.submitted_at, options_);
}

void JobScheduler::rekey_heap_locked() {
    // Rebuild the heap with current effective priorities (seq preserved);
    // dead entries (finished/evicted) fall out here.
    std::vector<QueueEntry> live;
    live.reserve(heap_.size());
    for (QueueEntry& entry : heap_) {
        auto it = cells_.find(entry.job_id);
        if (it == cells_.end()) continue;
        if (cell_state(it->second) != JobState::queued) continue;
        entry.priority = effective_priority(*it->second);
        live.push_back(entry);
    }
    heap_ = std::move(live);
    std::make_heap(heap_.begin(), heap_.end(), queue_order);
    last_rekey_ = clock_();
}

bool JobScheduler::job_is_interactive(const JobSpec& spec) const {
    if (interactive_predicate_) {
        try {
            return interactive_predicate_(spec);
        } catch (...) {
            return false;  // predicate failure → background (Python parity)
        }
    }
    const CategoryPolicy* policy = policy_for(category_for_kind(spec.kind));
    return policy != nullptr && policy->interactive;
}

void JobScheduler::release_lease(const std::string& job_id) {
    std::shared_ptr<AdmissionLease> lease;
    {
        std::lock_guard<std::mutex> guard(mutex_);
        auto it = leases_.find(job_id);
        if (it == leases_.end()) return;
        lease = std::move(it->second);
        leases_.erase(it);
    }
    if (lease) {
        try {
            lease->release();
        } catch (...) {
        }
    }
}

void JobScheduler::finish_locked(const std::shared_ptr<JobCell>& cell,
                                 JobState state) {
    // Requires mutex_ AND cell->mutex held by the caller.
    cell->snapshot.state = state;
    cell->snapshot.finished_at = clock_();
    cell->terminal_cv.notify_all();
    idle_cv_.notify_all();
    evict_history_locked(cell.get());
}

void JobScheduler::evict_history_locked(const JobCell* held_cell) {
    // Bounded history: drop the oldest finished cells (live JobHandles keep
    // their own shared cell alive — Python has the same shape, where the
    // caller's TaskHandle outlives scheduler bookkeeping). `held_cell` is
    // the finishing cell whose mutex the caller already holds — it is read
    // directly instead of re-locking (a non-recursive mutex self-lock would
    // deadlock).
    std::size_t finished = 0;
    for (const auto& [id, cell] : cells_) {
        if (cell.get() == held_cell) {
            ++finished;  // just finished under the caller's lock
            continue;
        }
        if (is_terminal(cell_state(cell))) ++finished;
    }
    if (finished <= options_.history_limit) return;
    std::vector<std::pair<double, std::string>> by_finish;
    by_finish.reserve(finished);
    for (const auto& [id, cell] : cells_) {
        if (cell.get() == held_cell) {
            by_finish.push_back({cell->snapshot.finished_at.value_or(0.0), id});
            continue;
        }
        std::lock_guard<std::mutex> cell_guard(cell->mutex);
        if (cell->snapshot.finished_at.has_value()) {
            by_finish.push_back({*cell->snapshot.finished_at, id});
        }
    }
    std::sort(by_finish.begin(), by_finish.end());
    const std::size_t excess = finished - options_.history_limit;
    for (std::size_t i = 0; i < excess && i < by_finish.size(); ++i) {
        cells_.erase(by_finish[i].second);
        work_dirs_.erase(by_finish[i].second);
    }
}

void JobScheduler::worker_loop(int lane) {
    const bool interactive_lane = lane >= options_.max_workers;
    while (true) {
        std::vector<Candidate> candidates;  // priority order (pop order)
        AdmissionHook admission_snapshot;
        {
            std::lock_guard<std::mutex> guard(mutex_);
            bool any_queued = false;
            for (const auto& [id, cell] : cells_) {
                if (cell_state(cell) == JobState::queued) {
                    any_queued = true;
                    break;
                }
            }
            if (shutdown_ && !any_queued && running_ == 0) return;
            if (!heap_.empty() &&
                (clock_() - last_rekey_) >= options_.aging_interval_s / 2.0) {
                rekey_heap_locked();
            }
            // Pop everything: dead entries fall out, cross-lane entries are
            // re-pushed, own-lane candidates are tried in priority order.
            // (Python parity: entries are re-pushed; the state transition
            // at claim time is what removes a job from circulation.)
            std::vector<QueueEntry> skipped;
            while (!heap_.empty()) {
                std::pop_heap(heap_.begin(), heap_.end(), queue_order);
                QueueEntry entry = heap_.back();
                heap_.pop_back();
                auto it = cells_.find(entry.job_id);
                if (it == cells_.end() ||
                    cell_state(it->second) != JobState::queued) {
                    continue;  // dead entry — dropped
                }
                if (job_is_interactive(*it->second->spec) != interactive_lane) {
                    skipped.push_back(std::move(entry));
                    continue;
                }
                candidates.push_back({std::move(entry), it->second});
            }
            // Snapshot the admission hook under the lock: set_admission may
            // hot-swap the std::function mid-loop (Python contract allows
            // swapping hooks while workers run).
            admission_snapshot = admission_;
            for (QueueEntry& entry : skipped) {
                heap_.push_back(std::move(entry));
            }
            for (const Candidate& candidate : candidates) {
                heap_.push_back(candidate.entry);  // stays queued until claim
            }
            std::make_heap(heap_.begin(), heap_.end(), queue_order);
        }
        // Admission runs WITHOUT the scheduler lock (documented contract):
        // a slow hook must not serialize submissions or the other lane.
        bool claimed = false;
        for (const Candidate& candidate : candidates) {
            std::shared_ptr<AdmissionLease> lease;
            if (admission_snapshot) {
                try {
                    lease = admission_snapshot(*candidate.cell->spec,
                                               candidate.entry.job_id);
                } catch (...) {
                    lease = nullptr;  // hook failure defers (Python parity)
                }
                if (!lease) continue;
            }
            std::shared_ptr<JobCell> claimed_cell;
            {
                std::lock_guard<std::mutex> guard(mutex_);
                auto it = cells_.find(candidate.entry.job_id);
                if (it == cells_.end()) {
                    claimed_cell = nullptr;
                } else {
                    std::lock_guard<std::mutex> cell_guard(it->second->mutex);
                    if (it->second->snapshot.state == JobState::queued) {
                        // Atomic claim: RUNNING lands inside this critical
                        // section, so a second worker cannot double-claim
                        // and a cancel() arriving now cooperates via the
                        // token instead of racing the transition.
                        it->second->snapshot.state = JobState::running;
                        it->second->snapshot.started_at = clock_();
                        it->second->worker_id.store(std::this_thread::get_id());
                        ++running_;
                        claimed_cell = it->second;
                    }
                }
            }
            if (claimed_cell == nullptr) {
                // Cancelled/claimed while we asked for admission — release
                // the speculative lease.
                if (lease) {
                    try {
                        lease->release();
                    } catch (...) {
                    }
                }
                continue;
            }
            if (lease) {
                std::lock_guard<std::mutex> guard(mutex_);
                leases_[candidate.entry.job_id] = lease;
            }
            run_job(claimed_cell);
            claimed = true;
            break;
        }
        if (claimed) continue;
        // Deferred (unadmitted) candidates poll faster than fresh submits
        // wake us — a lease release may unblock them (Python parity
        // 0.05 / 0.2).
        {
            const double timeout = candidates.empty() ? 0.2 : 0.05;
            std::unique_lock<std::mutex> lock(mutex_);
            wakeup_cv_.wait_for(lock, std::chrono::duration<double>(timeout));
        }
    }
}

void JobScheduler::run_job(const std::shared_ptr<JobCell>& cell) {
    const JobSpec& spec = *cell->spec;
    JobContext ctx(cell->snapshot.job_id, cell->token);
    ctx.self_cell_ = cell;
    ctx.progress_sink_ = [&spec, raw = cell.get()](double ratio,
                                                   const std::string& message) {
        {
            std::lock_guard<std::mutex> guard(raw->mutex);
            if (is_terminal(raw->snapshot.state)) return;
            raw->snapshot.progress = ratio;
            raw->snapshot.message = message;
        }
        if (spec.on_progress) {
            try {
                spec.on_progress(ratio, message);
            } catch (...) {
                // progress must never kill a task (Python parity)
            }
        }
    };

    std::exception_ptr failure;
    std::any result;
    bool raised_cancelled = false;
    try {
        result = spec.run(ctx);
    } catch (const JobCancelled&) {
        raised_cancelled = true;
    } catch (...) {
        failure = std::current_exception();
    }

    // Token set while running ⇒ a normal return is a partial result, not a
    // completion (Python parity).
    const bool cancelled = raised_cancelled || cell->token.is_cancelled();

    if (cancelled) {
        invoke_on_cancel(spec);
        // Scratch cleanup BEFORE the terminal state lands: once wait()
        // unblocks, the work dir is already gone — release can never race
        // an observer (#1451 B-06).
        release_work_dir(cell->snapshot.job_id);
        std::lock_guard<std::mutex> guard(mutex_);
        std::lock_guard<std::mutex> cell_guard(cell->mutex);
        if (!raised_cancelled) cell->result = std::move(result);
        finish_locked(cell, JobState::cancelled);
    } else if (failure != nullptr) {
        std::string error = "unknown exception";
        try {
            std::rethrow_exception(failure);
        } catch (const std::exception& exc) {
            const std::string what = exc.what();
            error = what.empty() ? "unknown exception" : what;
        } catch (...) {
        }
        // on_fail runs BEFORE the terminal state lands (Python parity).
        if (spec.on_fail) {
            try {
                spec.on_fail(error);
            } catch (...) {
            }
        }
        release_work_dir(cell->snapshot.job_id);
        std::lock_guard<std::mutex> guard(mutex_);
        std::lock_guard<std::mutex> cell_guard(cell->mutex);
        cell->snapshot.error = error;
        finish_locked(cell, JobState::failed);
    } else {
        // on_done runs BEFORE the terminal state lands: observers that see
        // done/degraded can rely on the on_done side effects having
        // completed (Python parity).
        if (spec.on_done) {
            try {
                spec.on_done(result);
            } catch (...) {
            }
        }
        bool degraded = false;
        if (spec.degraded_when) {
            try {
                degraded = spec.degraded_when(result);
            } catch (...) {
                degraded = true;  // predicate failure is itself a caveat
            }
        }
        release_work_dir(cell->snapshot.job_id);
        std::lock_guard<std::mutex> guard(mutex_);
        std::lock_guard<std::mutex> cell_guard(cell->mutex);
        cell->result = std::move(result);
        cell->snapshot.progress = 1.0;
        finish_locked(cell, degraded ? JobState::degraded : JobState::done);
    }

    {
        std::lock_guard<std::mutex> guard(mutex_);
        --running_;
    }
    release_lease(cell->snapshot.job_id);
    cell->worker_id.store(std::thread::id{});
    idle_cv_.notify_all();
    wakeup_cv_.notify_all();
}

void JobScheduler::shutdown(bool wait, std::optional<double> timeout_s) {
    std::vector<std::function<void()>> queued_cancels;
    {
        std::lock_guard<std::mutex> guard(mutex_);
        if (!shutdown_) {
            shutdown_ = true;
            std::vector<std::shared_ptr<JobCell>> queued;
            for (auto& [id, cell] : cells_) {
                const JobState state = cell_state(cell);
                if (state == JobState::queued) queued.push_back(cell);
                if (state == JobState::running || state == JobState::cancelling) {
                    std::lock_guard<std::mutex> cell_guard(cell->mutex);
                    cell->snapshot.cancel_requested = true;
                    cell->token.cancel();
                }
            }
            for (const std::shared_ptr<JobCell>& cell : queued) {
                std::lock_guard<std::mutex> cell_guard(cell->mutex);
                cell->snapshot.cancel_requested = true;
                finish_locked(cell, JobState::cancelled);
                if (cell->spec && cell->spec->on_cancel) {
                    queued_cancels.push_back(cell->spec->on_cancel);
                }
            }
            heap_.clear();
        }
        wakeup_cv_.notify_all();
        idle_cv_.notify_all();
    }
    for (const auto& cb : queued_cancels) {
        try {
            cb();
        } catch (...) {
        }
    }
    if (!wait) return;
    // Wait for the workers to drain. With a timeout, the call returns as
    // soon as the deadline passes WITHOUT joining — the residue is joined
    // by a later shutdown() or the destructor (jthreads cannot be
    // abandoned, so SOME call eventually blocks for as long as the most
    // stubborn job needs; this is the documented C++ counterpart of
    // Python's daemon threads).
    if (timeout_s.has_value()) {
        const auto deadline = std::chrono::steady_clock::now() +
                              std::chrono::duration<double>(*timeout_s);
        std::unique_lock<std::mutex> lock(mutex_);
        idle_cv_.wait_until(lock, deadline, [&] { return running_ == 0; });
        if (running_ != 0) return;  // deadline passed; residue joined later
    }
    for (std::jthread& worker : workers_) {
        if (worker.joinable()) worker.join();
    }
}

void JobScheduler::wait_idle() {
    // Bounded-poll loop instead of a bare cv wait: a queued job cancelled
    // through a JobHandle lands terminal outside the scheduler lock and
    // notifies only the cell's terminal_cv, so an idle waiter could sleep
    // past it forever on a pure cv wait. 50 ms matches the Python wakeup
    // granularity.
    std::unique_lock<std::mutex> lock(mutex_);
    while (true) {
        bool queued_seen = false;
        if (running_ == 0) {
            for (const auto& [id, cell] : cells_) {
                if (cell_state(cell) == JobState::queued) {
                    queued_seen = true;
                    break;
                }
            }
            if (!queued_seen) return;
        }
        idle_cv_.wait_for(lock, std::chrono::milliseconds(50));
    }
}

// --------------------------------------------------------------- singleton --

namespace {

JobScheduler** global_slot() {
    static JobScheduler* instance = new JobScheduler(
        JobScheduler::Options{.max_workers = 1, .interactive_workers = 1});
    return &instance;
}

}  // namespace

JobScheduler& global_scheduler() {
    // Parity of get_scheduler(): background I/O concurrency 1 plus one
    // dedicated interactive lane. The instance is intentionally immortal —
    // reset_global_scheduler() is a test/teardown seam that shuts the old
    // instance down and re-points the global at a fresh one.
    return **global_slot();
}

void reset_global_scheduler() {
    static std::mutex guard;
    std::lock_guard<std::mutex> lock(guard);
    // Parity of reset_global_scheduler(): shut down and forget the
    // singleton. The old instance is leaked on purpose — outstanding
    // JobHandles may still reference its cells; joining from here would
    // race whoever still holds them (Python drops its reference the same
    // way).
    JobScheduler* stale = *global_slot();
    stale->shutdown(true, 5.0);
    *global_slot() = new JobScheduler(
        JobScheduler::Options{.max_workers = 1, .interactive_workers = 1});
}

// ------------------------------------------------- governance install --
// Moved from governance.cpp in the Wave D target split: this entry point
// binds the governor to a scheduler (global_scheduler() when none is
// passed), so it lives with the scheduler target. Declared in
// governance.hpp; pwb_job_governance stays scheduler-free.

ResourceGovernor& ensure_global_governance(const ResourceBudget* budget_or_null,
                                           JobScheduler* scheduler,
                                           const BudgetSinks& sinks) {
    if (budget_or_null != nullptr) {
        // Python order: engine caches pushed BEFORE the governor rebind so
        // a pressure sample sees the new caps already in effect.
        apply_all_budgets(*budget_or_null, sinks);
        configure_runtime_budget(*budget_or_null);
    }
    ResourceGovernor& governor = global_governor();
    JobScheduler& sched =
        scheduler != nullptr ? *scheduler : global_scheduler();
    sched.set_admission(scheduler_admission_hook(governor));
    return governor;
}

}  // namespace pwb::job
