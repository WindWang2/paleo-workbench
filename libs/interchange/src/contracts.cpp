#include "pwb/interchange/contracts.hpp"

namespace pwb::interchange {

void CancelToken::cancel(std::string reason) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!cancelled_) {
        cancelled_ = true;
        reason_ = std::move(reason);
    }
}

bool CancelToken::cancelled() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return cancelled_;
}

std::string CancelToken::reason() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return reason_;
}

void CancelToken::checkpoint() const {
    std::lock_guard<std::mutex> lock(mutex_);
    if (cancelled_) throw CancelledError(reason_.empty() ? "cancelled" : reason_);
}

CancelToken& null_cancel() {
    static CancelToken token;
    return token;
}

Json FormatCapability::to_dict() const {
    Json out = Json::object();
    out["read"] = read;
    out["inspect"] = inspect;
    out["import_data"] = import_data;
    out["export"] = can_export;
    out["roundtrip_verify"] = roundtrip_verify;
    out["notes"] = notes;
    return out;
}

std::string_view to_string(VerificationState state) {
    switch (state) {
        case VerificationState::VERIFIED: return "VERIFIED";
        case VerificationState::VERIFIED_WITH_WARNINGS: return "VERIFIED_WITH_WARNINGS";
        case VerificationState::FAILED: return "FAILED";
        case VerificationState::UNVERIFIED: return "UNVERIFIED";
    }
    return "UNVERIFIED";
}

Json VerificationCheck::to_dict() const {
    Json out = Json::object();
    out["name"] = name;
    out["passed"] = passed;
    out["detail"] = detail;
    return out;
}

bool ExportVerification::ok() const {
    return state == VerificationState::VERIFIED ||
           state == VerificationState::VERIFIED_WITH_WARNINGS;
}

Json ExportVerification::summary() const {
    Json checks_json = Json::array();
    for (const auto& check : checks) checks_json.push_back(check.to_dict());
    Json out = Json::object();
    out["state"] = std::string(to_string(state));
    out["detail"] = detail;
    out["warnings"] = warnings;
    out["checks"] = std::move(checks_json);
    return out;
}

ExportVerification ExportVerification::unverified(std::string detail) {
    ExportVerification out;
    out.state = VerificationState::UNVERIFIED;
    out.detail = std::move(detail);
    return out;
}

ExportVerification ExportVerification::failed(std::vector<VerificationCheck> checks,
                                              std::string detail) {
    ExportVerification out;
    out.state = VerificationState::FAILED;
    out.checks = std::move(checks);
    out.detail = std::move(detail);
    return out;
}

Json ExportPlan::to_dict() const {
    Json out = Json::object();
    out["format_id"] = format_id;
    out["source_path"] = source_path;
    out["target_path"] = target_path;
    out["estimated_bytes"] = estimated_bytes;
    out["options"] = options;
    out["warnings"] = warnings;
    out["source_version_ids"] = source_version_ids;
    out["linked_id"] = linked_id;
    return out;
}

}  // namespace pwb::interchange
