#include <pwb/ui_visualqa/qa_check.hpp>

namespace pwb::ui_visualqa {

CheckResult make_check(std::string name, bool ok, std::string detail) {
    return CheckResult{std::move(name), static_cast<bool>(ok),
                       std::move(detail)};
}

pwb::domain::Json checks_payload(const std::vector<CheckResult>& results) {
    using pwb::domain::Json;
    Json entries = Json::array();
    for (const CheckResult& r : results) {
        entries.push_back(Json{
            {"name", r.name},
            {"ok", r.ok},
            {"detail", r.detail},
        });
    }
    Json payload;
    if (results.empty()) {
        payload["state_ok"] = nullptr;
    } else {
        payload["state_ok"] = all_ok(results);
    }
    payload["checks"] = std::move(entries);
    return payload;
}

bool all_ok(const std::vector<CheckResult>& results) {
    if (results.empty()) {
        return false;
    }
    for (const CheckResult& r : results) {
        if (!r.ok) {
            return false;
        }
    }
    return true;
}

std::vector<std::string> failed_names(
    const std::vector<CheckResult>& results) {
    std::vector<std::string> out;
    for (const CheckResult& r : results) {
        if (!r.ok) {
            out.push_back(r.name);
        }
    }
    return out;
}

}  // namespace pwb::ui_visualqa
