#pragma once

// CONV-30 — task category policy ladder, ported 1:1 from
// paleo_workbench/runtime/task_categories.py (frozen against
// job_policy_oracle.json; replayed in job_runtime.policy_oracle).
//
// Every heavy operation classifies into one category that fixes three
// governance defaults: base priority (interactive render > preview >
// user-triggered computation > export > background indexing >
// maintenance), interactivity (may the job claim GUI-reserved cores), and
// io_weight (how many process-wide IO slots the job occupies).

#include <cstddef>
#include <cstdint>
#include <string>

namespace pwb::job {

enum class JobCategory : std::uint8_t {
    interactive_render,
    interactive_query,
    preview,
    background_io,
    background_compute,
    transcode,
    attribute,
    inference,
    // "export" is a C++ keyword — member carries the same wire id via
    // category_id().
    export_job,
    indexing,
    maintenance,
};

// Python enum VALUES (the stable wire identity used by the oracle).
[[nodiscard]] const char* category_id(JobCategory category) noexcept;

struct CategoryPolicy {
    JobCategory category;
    int base_priority{0};
    bool interactive{false};
    double io_weight{1.0};
    double default_cpu_cores{1.0};
    [[nodiscard]] bool background() const noexcept { return !interactive; }
};

// Priority ladder — exact copy of CATEGORY_POLICIES (order preserved for
// review; lookup is by enum, not position).
[[nodiscard]] const CategoryPolicy* policy_for(JobCategory category);

// Classify a scheduler kind string; unknown/empty kinds are background IO
// (Python parity, longest prefixes first). ASCII case-insensitive.
[[nodiscard]] JobCategory category_for_kind(const std::string& kind);

}  // namespace pwb::job
