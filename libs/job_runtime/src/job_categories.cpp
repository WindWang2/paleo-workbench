// CONV-30 — category policy table + kind→category mapping, ported from
// paleo_workbench/runtime/task_categories.py (CATEGORY_POLICIES /
// _KIND_PREFIX_MAP / category_for_kind). Frozen against
// job_policy_oracle.json.

#include "pwb/job_runtime/job_categories.hpp"

#include <array>
#include <string_view>

namespace pwb::job {

const char* category_id(JobCategory category) noexcept {
    switch (category) {
    case JobCategory::interactive_render:
        return "interactive.render";
    case JobCategory::interactive_query:
        return "interactive.query";
    case JobCategory::preview:
        return "preview";
    case JobCategory::background_io:
        return "background.io";
    case JobCategory::background_compute:
        return "background.compute";
    case JobCategory::transcode:
        return "seismic.transcode";
    case JobCategory::attribute:
        return "seismic.attribute";
    case JobCategory::inference:
        return "prediction.inference";
    case JobCategory::export_job:
        return "export";
    case JobCategory::indexing:
        return "indexing";
    case JobCategory::maintenance:
        return "maintenance";
    }
    return "background.io";
}

const CategoryPolicy* policy_for(JobCategory category) {
    static constexpr std::array<CategoryPolicy, 11> kPolicies = {{
        {JobCategory::interactive_render, 100, true, 1.0, 1.0},
        {JobCategory::interactive_query, 90, true, 1.0, 0.5},
        {JobCategory::preview, 70, true, 1.0, 0.5},
        {JobCategory::attribute, 50, false, 1.0, 1.0},
        {JobCategory::inference, 50, false, 1.0, 1.0},
        {JobCategory::transcode, 45, false, 4.0, 1.0},
        {JobCategory::export_job, 40, false, 2.0, 1.0},
        {JobCategory::background_compute, 30, false, 1.0, 1.0},
        {JobCategory::background_io, 30, false, 2.0, 1.0},
        {JobCategory::indexing, 20, false, 2.0, 1.0},
        {JobCategory::maintenance, 10, false, 1.0, 1.0},
    }};
    for (const auto& policy : kPolicies) {
        if (policy.category == category) return &policy;
    }
    return nullptr;
}

namespace {

struct KindPrefix {
    std::string_view prefix;
    JobCategory category;
};

// Longest prefixes first — "interactive.render" must win over "render"
// (Python parity; order is load-bearing and oracle-checked).
constexpr std::array<KindPrefix, 14> kKindPrefixMap = {{
    {"interactive.render", JobCategory::interactive_render},
    {"interactive.query", JobCategory::interactive_query},
    {"seismic.transcode", JobCategory::transcode},
    {"seismic.attribute", JobCategory::attribute},
    {"prediction.inference", JobCategory::inference},
    {"inference", JobCategory::inference},
    {"export", JobCategory::export_job},
    {"verify", JobCategory::indexing},
    {"scan", JobCategory::indexing},
    {"index", JobCategory::indexing},
    {"maintenance", JobCategory::maintenance},
    {"preview", JobCategory::preview},
    {"render", JobCategory::interactive_render},
    {"query", JobCategory::interactive_query},
}};

[[nodiscard]] char ascii_lower(char c) noexcept {
    return (c >= 'A' && c <= 'Z') ? static_cast<char>(c + 32) : c;
}

[[nodiscard]] bool starts_with_lowered(const std::string& kind,
                                       std::string_view prefix) {
    if (kind.size() < prefix.size()) return false;
    for (std::size_t i = 0; i < prefix.size(); ++i) {
        if (ascii_lower(kind[i]) != prefix[i]) return false;
    }
    return true;
}

}  // namespace

JobCategory category_for_kind(const std::string& kind) {
    if (kind.empty()) return JobCategory::background_io;
    for (const auto& entry : kKindPrefixMap) {
        if (starts_with_lowered(kind, entry.prefix)) return entry.category;
    }
    return JobCategory::background_io;
}

}  // namespace pwb::job
