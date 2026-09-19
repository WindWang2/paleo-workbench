// UI-06 — new_project_wizard._validate_step1 + _on_analysis_finished.
#include <pwb/ui_pages_data/onboarding_report.hpp>  // format_import_summary
#include <pwb/ui_pages_data/wizard_model.hpp>

#include "detail/py_repr.hpp"

#include <algorithm>

namespace pwb::ui_pages_data {
namespace {

using pwb::domain::Json;
using detail::py_str;

int jint_or(const Json& j, const char* key, int fallback) {
    if (!j.is_object() || !j.contains(key)) return fallback;
    const Json& v = j.at(key);
    if (v.is_number_integer() || v.is_number_unsigned())
        return v.get<int>();
    if (v.is_number_float()) return static_cast<int>(v.get<double>());
    if (v.is_boolean()) return v.get<bool>() ? 1 : 0;
    return fallback;
}

}  // namespace

std::string validate_step1(const WizardStep1Input& in) {
    if (in.name.empty()) return "请输入工程名称";
    if (in.data_dir_text.empty()) return "请选择原始数据文件夹";
    if (!in.data_dir_exists) return "数据目录不存在";
    if (!in.same_dir) {
        if (in.intermediate_text.empty()) return "请选择中间文件目录";
        if (!in.intermediate_exists) return "中间目录不存在";
    }
    if (in.target_exists) return "工程文件已存在";
    return "";
}

WizardReportView format_wizard_report(const Json& raw_report,
                                      int imported_fallback) {
    // `report = result.report if isinstance(result.report, dict) else {}`.
    const Json report =
        raw_report.is_object() ? raw_report : Json::object();

    WizardReportView view;
    view.summary = format_import_summary(
        jint_or(report, "imported_count", imported_fallback),
        jint_or(report, "wells_total", 0),
        jint_or(report, "wells_with_coords", 0),
        jint_or(report, "surveys", 0),
        jint_or(report, "entities", 0));

    // by_type.items() in DICT ORDER (no sort — the wizard differs from the
    // onboarding card here). ordered_json preserves fixture order.
    const Json by_type = report.value("by_type", Json::object());
    if (by_type.is_object()) {
        for (const auto& [k, v] : by_type.items()) {
            // str(v) semantics — numbers bare, bools True/False, null None.
            std::string text;
            int numeric = 0;
            if (v.is_number_integer() || v.is_number_unsigned()) {
                numeric = v.get<int>();
                text = std::to_string(v.get<long long>());
            } else if (v.is_number_float()) {
                text = v.dump();
            } else if (v.is_string()) {
                text = v.get<std::string>();
            } else if (v.is_boolean()) {
                text = v.get<bool>() ? "True" : "False";
            } else if (v.is_null()) {
                text = "None";
            } else {
                text = v.dump();
            }
            view.inventory.emplace_back(k, numeric);
            view.inventory_text.push_back(std::move(text));
        }
    }

    // issues + warnings combined, first 20, str(x) each, joined by "\n".
    auto collect = [&](const char* key) {
        const Json list = report.value(key, Json::array());
        if (!list.is_array()) return;
        for (const auto& item : list) {
            view.issue_lines.push_back(py_str(item));
        }
    };
    collect("issues");
    collect("warnings");
    if (view.issue_lines.size() > 20) view.issue_lines.resize(20);
    view.issues_visible = !view.issue_lines.empty();
    return view;
}

}  // namespace pwb::ui_pages_data
