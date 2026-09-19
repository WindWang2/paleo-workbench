// UI-06 — activity_card.update_state.
#include <pwb/ui_pages_data/activity.hpp>
#include <pwb/ui_pages_data/vocab.hpp>

namespace pwb::ui_pages_data {
namespace {

using pwb::domain::Json;

// int(raw or 0) with Python's try/except → 0.
// int(True) == 1 in Python; JSON bools must therefore convert.
long long to_int(const Json& v) {
    if (v.is_boolean()) return v.get<bool>() ? 1 : 0;
    if (v.is_number_integer() || v.is_number_unsigned())
        return v.get<long long>();
    if (v.is_number_float()) return static_cast<long long>(v.get<double>());
    if (v.is_string()) {
        // int("3") works in Python; int("x") → 0 via except.
        try {
            return std::stoll(v.get<std::string>());
        } catch (...) {
            return 0;
        }
    }
    return 0;
}

int step_index(const std::string& step_type) {
    // STEP_TYPES.index(step.step_type) if in STEP_TYPES else 0.
    for (std::size_t i = 0; i < kStepOrder.size(); ++i) {
        if (kStepOrder[i] == step_type) return static_cast<int>(i);
    }
    return 0;
}

}  // namespace

std::vector<ActivityEntry>
compute_activity_entries(const Json& state,
                         const std::vector<ActivityStep>& steps) {
    std::vector<ActivityEntry> entries;
    for (const auto& step : steps) {
        if (step.status == "pending") continue;
        const int idx = step_index(step.step_type);
        const std::string label = std::string(kStepLabels[idx]);
        const std::string st = std::string(status_text(step.status));
        entries.push_back({"刚刚", label + ": " + st});
    }
    if (!entries.empty()) return entries;

    // Evidence-based fallback — fixed (label, key) scan order.
    static const std::pair<const char*, const char*> kFallback[] = {
        {"数据资源", "resource_counts"},
        {"单因素图", "factor_map_count"},
        {"预测任务", "prediction_count"},
        {"古地理图", "map_document_count"},
        {"质检问题", "qc_issue_count"},
        {"导出成果", "export_count"},
    };
    for (const auto& [label, key] : kFallback) {
        const Json raw =
            (state.is_object() && state.contains(key)) ? state.at(key)
                                                     : Json();
        if (std::string(key) == "resource_counts" && raw.is_object()) {
            long long total = 0;
            for (const auto& [k, v] : raw.items()) total += to_int(v);
            if (total > 0) {
                entries.push_back(
                    {"工程", std::string(label) + ": " +
                                 std::to_string(total) + " 项"});
            }
            continue;
        }
        const long long n = to_int(raw);
        if (n > 0) {
            entries.push_back(
                {"工程", std::string(label) + ": " + std::to_string(n)});
        }
    }
    return entries;
}

}  // namespace pwb::ui_pages_data
