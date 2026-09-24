#pragma once

// CONV-34 — global resource governance glue, ported from
// paleo_workbench/runtime/governance.py (see governor_oracle.json).
//
// Single installation point: pushes the active budget into host caches,
// binds the pressure monitor, and installs the governor's admission hook
// on the JobScheduler. Idempotent.
//
// Deliberate carve-outs (host concerns, documented not faked):
// - Python's _apply_gil_latency_policy is CPython-only (no GIL here);
// - apply_vram/l1/compute_budget pushed Python engine singletons — in C++
//   the equivalent caches are host objects, so ensure_global_governance
//   accepts budget sinks the caller supplies;
// - TaskScheduler.set_background_nice has no portable C++ counterpart
//   (per-thread nice is Linux pthread-only) — JobScheduler deliberately
//   carries no such field; hosts that need it set it on their worker
//   start hook.

#include <functional>
#include <map>
#include <memory>
#include <string>
#include <string_view>

#include "pwb/job_runtime/job_contract.hpp"
#include "pwb/job_runtime/resource_governor.hpp"

namespace pwb::job {

class JobScheduler;  // bound only by ensure_global_governance (defined in
                     // the pwb_job_runtime target — Wave D split); this
                     // header stays scheduler-free.

// Build the governor's claim from a JobSpec (Python _request_for_spec):
// estimates ride in spec.resources; categories derive from kind; missing
// estimates fall back to the category policy defaults.
[[nodiscard]] TaskRequest request_for_spec(const JobSpec& spec,
                                           const std::string& job_id);

// Admission hook adapting the governor to the scheduler lease protocol.
// Same std::function type as JobScheduler::AdmissionHook (job_scheduler.hpp)
// — spelled out here so governance links without the scheduler target.
[[nodiscard]] std::function<std::shared_ptr<AdmissionLease>(
    const JobSpec&, const std::string&)>
scheduler_admission_hook(ResourceGovernor& governor);

// One question for every parallelism knob: how many workers fit the
// budget? The governor may shrink the requested default (background
// ceiling, pressure scale) but never below 1; any failure falls back to
// the requested count (Python try/except parity).
[[nodiscard]] int clamp_workers(std::string_view category_id, int requested);

// Named budget sinks — the C++ counterpart of Python's apply_all_budgets
// pushing into engine caches (vram/l1/compute). Each sink receives the
// budget and reports whether it applied. Missing engines simply aren't
// registered — no fake success map.
using BudgetSinks =
    std::map<std::string, std::function<bool(const ResourceBudget&)>>;
std::map<std::string, bool> apply_all_budgets(const ResourceBudget& budget,
                                              const BudgetSinks& sinks);

// Idempotent: apply budgets (via sinks), bind monitor, install scheduler
// admission. Returns the process governor. Defined in the scheduler target
// (job_scheduler.cpp) because it binds a JobScheduler — link
// Pwb::JobRuntime (or Pwb::JobQt) to call it.
[[nodiscard]] ResourceGovernor& ensure_global_governance(
    const ResourceBudget* budget_or_null = nullptr,
    JobScheduler* scheduler = nullptr,
    const BudgetSinks& sinks = {});

}  // namespace pwb::job
