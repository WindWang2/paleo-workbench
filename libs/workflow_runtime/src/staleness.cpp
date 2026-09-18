// staleness.cpp — unified staleness vocabulary (CONV-26). See
// include/pwb/workflow_runtime/staleness.hpp.

#include <pwb/workflow_runtime/staleness.hpp>

namespace pwb::workflow_runtime {

const char* staleness_verdict_value(StalenessVerdict verdict) {
    switch (verdict) {
    case StalenessVerdict::Current: return "current";
    case StalenessVerdict::StaleContent: return "stale_content";
    case StalenessVerdict::StaleVersion: return "stale_version";
    case StalenessVerdict::MissingInput: return "missing_input";
    case StalenessVerdict::Superseded: return "superseded";
    case StalenessVerdict::Unknown: return "unknown";
    }
    return "?";
}

std::optional<StalenessVerdict> staleness_verdict_from_value(
    const std::string& value) {
    if (value == "current") return StalenessVerdict::Current;
    if (value == "stale_content") return StalenessVerdict::StaleContent;
    if (value == "stale_version") return StalenessVerdict::StaleVersion;
    if (value == "missing_input") return StalenessVerdict::MissingInput;
    if (value == "superseded") return StalenessVerdict::Superseded;
    if (value == "unknown") return StalenessVerdict::Unknown;
    return std::nullopt;
}

bool verdict_is_problem(StalenessVerdict verdict) {
    // 未知也是问题（不可签发）— unknown is a problem for the publish gate.
    return verdict != StalenessVerdict::Current;
}

std::string verdict_label_zh(StalenessVerdict verdict) {
    switch (verdict) {
    case StalenessVerdict::Current: return "最新";
    case StalenessVerdict::StaleContent: return "内容过期";
    case StalenessVerdict::StaleVersion: return "版本过期";
    case StalenessVerdict::MissingInput: return "输入缺失";
    case StalenessVerdict::Superseded: return "已被取代";
    case StalenessVerdict::Unknown: return "状态未知";
    }
    return "?";
}

StalenessVerdict from_constraint_pin(const std::string& state) {
    // 未钉 = 无比较基准 = 未知。
    if (state == "current") return StalenessVerdict::Current;
    if (state == "unpinned") return StalenessVerdict::Unknown;
    if (state == "unknown") return StalenessVerdict::Unknown;
    if (state == "missing") return StalenessVerdict::MissingInput;
    if (state == "stale_version") return StalenessVerdict::StaleVersion;
    if (state == "stale_content") return StalenessVerdict::StaleContent;
    if (state == "uncommitted") return StalenessVerdict::Unknown;
    return StalenessVerdict::Unknown;
}

StalenessVerdict from_workspace_status(const std::string& status) {
    // 工作区 stale = 上游已有新版本。
    if (status == "current") return StalenessVerdict::Current;
    if (status == "stale") return StalenessVerdict::StaleVersion;
    if (status == "missing_input") return StalenessVerdict::MissingInput;
    if (status == "superseded") return StalenessVerdict::Superseded;
    if (status == "unknown") return StalenessVerdict::Unknown;
    return StalenessVerdict::Unknown;
}

StalenessVerdict from_run_freshness(const std::string& state_value) {
    // run 失败/运行中 → 无法判定产物新鲜度 → UNKNOWN.
    if (state_value == "fresh") return StalenessVerdict::Current;
    if (state_value == "stale") return StalenessVerdict::StaleVersion;
    if (state_value == "unknown") return StalenessVerdict::Unknown;
    if (state_value == "missing") return StalenessVerdict::MissingInput;
    if (state_value == "failed") return StalenessVerdict::Unknown;
    if (state_value == "running") return StalenessVerdict::Unknown;
    return StalenessVerdict::Unknown;
}

StalenessVerdict from_run_freshness(FreshnessState state) {
    return from_run_freshness(freshness_state_value(state));
}

Json ArtifactVerdict::to_dict() const {
    Json culprits = Json::array();
    for (const auto& c : upstream_culprits) culprits.push_back(c);
    Json out = Json::object();
    out["artifact_key"] = artifact_key;
    out["verdict"] = staleness_verdict_value(verdict);
    out["label"] = label();
    out["is_problem"] = is_problem();
    out["detail"] = detail;
    out["upstream_culprits"] = std::move(culprits);
    return out;
}

}  // namespace pwb::workflow_runtime
