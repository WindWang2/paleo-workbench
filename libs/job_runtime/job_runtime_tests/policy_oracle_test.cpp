// job_runtime.policy_oracle — the C++ category ladder / kind mapping /
// aging formula / supersede decisions replayed against the frozen Python
// oracle (job_policy_oracle.json, generated from the REAL implementation
// by tools/oracle/generate_job_policy_oracle.py), plus a negative
// self-check: every deliberate perturbation of the oracle must be
// detected.

#include <cmath>
#include <condition_variable>
#include <cstdio>
#include <fstream>
#include <mutex>
#include <sstream>
#include <string>

#include <pwb/domain/json.hpp>
#include <pwb/job_runtime/job_categories.hpp>
#include <pwb/job_runtime/job_scheduler.hpp>

#include "job_test.hpp"

using pwb::domain::Json;
using pwb::job::category_for_kind;
using pwb::job::category_id;
using pwb::job::JobCategory;
using pwb::job::JobContext;
using pwb::job::JobHandle;
using pwb::job::JobScheduler;
using pwb::job::JobSpec;
using pwb::job::JobState;
using pwb::job::policy_for;

#ifndef PWB_JOB_POLICY_ORACLE
#error "PWB_JOB_POLICY_ORACLE must point at job_policy_oracle.json"
#endif

namespace {

class Gate {
public:
    void wait() {
        std::unique_lock<std::mutex> lock(mutex_);
        cv_.wait(lock, [this] { return open_; });
    }
    void open() {
        std::lock_guard<std::mutex> guard(mutex_);
        open_ = true;
        cv_.notify_all();
    }

private:
    std::mutex mutex_;
    std::condition_variable cv_;
    bool open_ = false;
};

Json load_oracle() {
    std::ifstream in(PWB_JOB_POLICY_ORACLE);
    if (!in) {
        std::fprintf(stderr, "cannot open oracle: %s\n", PWB_JOB_POLICY_ORACLE);
        std::exit(2);
    }
    std::stringstream buffer;
    buffer << in.rdbuf();
    return Json::parse(buffer.str());
}

[[nodiscard]] JobCategory category_from_id(const std::string& id) {
    for (int i = 0; i <= static_cast<int>(JobCategory::maintenance); ++i) {
        const auto category = static_cast<JobCategory>(i);
        if (id == category_id(category)) return category;
    }
    // Unreachable for oracle rows; surfaces a failure via the caller check.
    return JobCategory::background_io;
}

[[nodiscard]] bool policies_match(const Json& oracle) {
    for (const auto& row : oracle["policies"]) {
        const JobCategory category =
            category_from_id(row["category"].get<std::string>());
        const auto* policy = policy_for(category);
        if (policy == nullptr) return false;
        if (category_id(policy->category) != row["category"]) return false;
        if (policy->base_priority != row["base_priority"].get<int>()) return false;
        if (policy->interactive != row["interactive"].get<bool>()) return false;
        if (std::abs(policy->io_weight - row["io_weight"].get<double>()) > 1e-9) {
            return false;
        }
        if (std::abs(policy->default_cpu_cores -
                     row["default_cpu_cores"].get<double>()) > 1e-9) {
            return false;
        }
    }
    return true;
}

[[nodiscard]] bool kind_mappings_match(const Json& oracle) {
    for (const auto& row : oracle["kind_mappings"]) {
        const JobCategory mapped = category_for_kind(row["kind"].get<std::string>());
        if (category_id(mapped) != row["category"].get<std::string>()) return false;
    }
    return true;
}

[[nodiscard]] bool aging_matches(const Json& oracle) {
    JobScheduler::Options options;
    options.aging_interval_s = oracle["aging_interval_s"].get<double>();
    options.aging_step = oracle["aging_step"].get<int>();
    options.aging_max_boost = oracle["aging_max_boost"].get<int>();
    for (const auto& row : oracle["aging"]) {
        const int effective = JobScheduler::aged_priority(
            row["base_priority"].get<int>(), row["wait_s"].get<double>(),
            options);
        if (effective != row["effective"].get<int>()) return false;
    }
    return true;
}

// Negative self-check: the comparator must reject deliberate tampering.
void negative_selfcheck(const Json& oracle) {
    int detected = 0;
    {
        Json tampered = oracle;
        tampered["policies"][0]["base_priority"] =
            tampered["policies"][0]["base_priority"].get<int>() + 1;
        if (!policies_match(tampered)) ++detected;
    }
    {
        Json tampered = oracle;
        tampered["policies"][3]["interactive"] =
            !tampered["policies"][3]["interactive"].get<bool>();
        if (!policies_match(tampered)) ++detected;
    }
    {
        Json tampered = oracle;
        tampered["kind_mappings"][0]["category"] = "background.io";
        if (!kind_mappings_match(tampered)) ++detected;
    }
    {
        Json tampered = oracle;
        tampered["aging"][4]["effective"] =
            tampered["aging"][4]["effective"].get<int>() + 1;
        if (!aging_matches(tampered)) ++detected;
    }
    {
        Json tampered = oracle;
        tampered["aging_max_boost"] =
            tampered["aging_max_boost"].get<int>() + 1;
        if (!aging_matches(tampered)) ++detected;
    }
    PWB_CHECK(detected == 5);
}

}  // namespace

TEST(policy_oracle_replay) {
    const Json oracle = load_oracle();
    PWB_CHECK(oracle["schema"] == "pwb.job_policy_oracle/1");
    PWB_CHECK(policies_match(oracle));
    PWB_CHECK(kind_mappings_match(oracle));
    PWB_CHECK(aging_matches(oracle));
    // Negative self-check (tampering must be detected, never silently pass).
    negative_selfcheck(oracle);
}

TEST(supersede_decision_table) {
    // Frozen #1224 semantics replayed behaviorally against a live
    // scheduler: queued → supersede, running AND cancelling → reject with
    // the exact Python message (key prefix included).
    const Json oracle = load_oracle();
    for (const auto& row : oracle["supersede"]) {
        const std::string state = row["active_state"].get<std::string>();
        JobScheduler scheduler({.max_workers = 1});
        if (state == "queued") {
            // Stage: block the lane, queue key A, resubmit A.
            Gate g;
            JobSpec blocker;
            blocker.run = [&g](JobContext&) -> std::any { g.wait(); return {}; };
            (void)scheduler.submit(std::move(blocker));
            std::atomic<bool> unwound{false};
            JobSpec old_job;
            old_job.task_key = "k";
            old_job.on_cancel = [&unwound]() { unwound = true; };
            JobHandle old_handle = scheduler.submit(std::move(old_job));
            JobSpec new_job;
            new_job.task_key = "k";
            JobHandle new_handle = scheduler.submit(std::move(new_job));
            PWB_CHECK(old_handle.snapshot().state == JobState::cancelled);
            PWB_CHECK(unwound.load());
            PWB_CHECK(new_handle.snapshot().state == JobState::queued);
            g.open();
            scheduler.wait_idle();
        } else {
            // Both running and cancelling park on a gate so the state is
            // stable while the resubmit is attempted (a token-parked job
            // would jump straight to cancelled, skipping the window).
            Gate started;
            Gate release;
            JobSpec active_job;
            active_job.task_key = "k";
            active_job.run = [&started, &release](JobContext&) -> std::any {
                started.open();
                release.wait();
                return {};
            };
            JobHandle active_handle = scheduler.submit(std::move(active_job));
            started.wait();
            if (state == "cancelling") {
                PWB_CHECK(active_handle.cancel());
                PWB_CHECK(active_handle.snapshot().state ==
                          JobState::cancelling);
            }
            bool rejected = false;
            try {
                JobSpec dup;
                dup.task_key = "k";
                (void)scheduler.submit(std::move(dup));
            } catch (const pwb::job::JobSubmitError& err) {
                rejected = true;
                const std::string message = err.what();
                PWB_CHECK(message == row["message"].get<std::string>());
            }
            PWB_CHECK(rejected);
            release.open();
            PWB_CHECK(active_handle.wait_for(5.0));
            PWB_CHECK(active_handle.snapshot().is_terminal());
        }
    }
}

int main() { return pwb_test_main(); }
