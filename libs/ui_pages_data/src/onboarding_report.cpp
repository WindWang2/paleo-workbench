// UI-06 — onboarding_report_card.set_report / wizard analysis summary.
#include <pwb/ui_pages_data/onboarding_report.hpp>

#include "detail/py_repr.hpp"

#include <algorithm>
#include <cstdio>
#include <string>
#include <utility>
#include <vector>

namespace pwb::ui_pages_data {
namespace {

using pwb::domain::Json;
using detail::py_str;

std::string jstr(const Json& v) {
    return v.is_string() ? v.get<std::string>() : std::string();
}

int jint(const Json& j, const char* key, int fallback = 0) {
    if (!j.is_object() || !j.contains(key)) return fallback;
    const Json& v = j.at(key);
    if (v.is_number_integer() || v.is_number_unsigned())
        return v.get<int>();
    if (v.is_number_float()) return static_cast<int>(v.get<double>());
    // Python report.get(k, 0) returns the raw value; callers format it.
    // Non-numeric → behave like int() failing upstream: the card would
    // crash — we choose fallback 0 (defensive, matches "or 0" idioms).
    return fallback;
}

// Python "{v:.1f}" formatting — always one decimal.
std::string f1(double v) {
    char buf[64];
    std::snprintf(buf, sizeof(buf), "%.1f", v);
    return buf;
}

}  // namespace

std::string format_import_summary(int imported, int wells_total,
                                  int wells_with_coords, int surveys,
                                  int entities) {
    // Shared f-string:
    // f"导入 {imported} 项 · 井 {wells} 口（{with} 有坐标） · 地震 {s} 个 · 地质实体 {e} 个"
    return "导入 " + std::to_string(imported) + " 项 · 井 " +
           std::to_string(wells_total) + " 口（" +
           std::to_string(wells_with_coords) + " 有坐标） · 地震 " +
           std::to_string(surveys) + " 个 · 地质实体 " +
           std::to_string(entities) + " 个";
}

OnboardingReportView format_onboarding_report(const Json& report) {
    OnboardingReportView view;
    // `if not report: hide` — null/false/empty dict are all falsy.
    if (report.is_null() || (report.is_boolean() && !report.get<bool>()) ||
        (report.is_object() && report.empty()) ||
        (report.is_array() && report.empty()) ||
        (report.is_string() && report.get<std::string>().empty())) {
        return view;  // card stays hidden
    }
    if (!report.is_object()) return view;
    view.card_visible = true;

    // source = source_folder or intermediate_folder or "".
    const std::string source =
        jstr(report.value("source_folder", Json())).empty()
            ? jstr(report.value("intermediate_folder", Json()))
            : jstr(report.value("source_folder", Json()));
    if (!source.empty()) {
        view.source = {"来源目录：" + source, true};
    }

    view.summary = {format_import_summary(
                        jint(report, "imported_count"), jint(report, "wells_total"),
                        jint(report, "wells_with_coords"), jint(report, "surveys"),
                        jint(report, "entities")),
                    true};

    // by_type sorted by count desc — Python sorts dict items by value.
    if (report.contains("by_type") && report.at("by_type").is_object()) {
        std::vector<std::pair<std::string, long long>> items;
        for (const auto& [k, v] : report.at("by_type").items()) {
            long long n = 0;
            if (v.is_number()) n = v.get<long long>();
            items.emplace_back(k, n);
        }
        std::stable_sort(items.begin(), items.end(),
                         [](const auto& a, const auto& b) {
                             return a.second > b.second;
                         });
        std::string line;
        for (std::size_t i = 0; i < items.size(); ++i) {
            if (i) line += " · ";
            line += items[i].first + " " + std::to_string(items[i].second);
        }
        if (!items.empty()) view.by_type = {line, true};
    }

    // extent gate: `extent and isinstance(extent, (list, tuple)) and
    // len(extent) == 4 and all(v is not None)` then [float(v) for v].
    // float() accepts numbers, bools and numeric strings; anything else
    // raises → the "无坐标井位范围" fallback.
    view.extent = {"无坐标井位范围", true};
    if (report.contains("extent") && report.at("extent").is_array() &&
        !report.at("extent").empty() && report.at("extent").size() == 4) {
        const Json& ext = report.at("extent");
        bool ok = true;
        double vals[4] = {0, 0, 0, 0};
        for (int i = 0; i < 4 && ok; ++i) {
            const Json& v = ext[i];
            if (v.is_null()) {
                ok = false;
            } else if (v.is_number()) {
                vals[i] = v.get<double>();
            } else if (v.is_boolean()) {
                vals[i] = v.get<bool>() ? 1.0 : 0.0;
            } else if (v.is_string()) {
                try {
                    const std::string& s = v.get_ref<const std::string&>();
                    std::size_t used = 0;
                    vals[i] = std::stod(s, &used);
                    // float() allows surrounding whitespace only.
                    while (used < s.size() &&
                           (s[used] == ' ' || s[used] == '\t' ||
                            s[used] == '\n' || s[used] == '\r'))
                        ++used;
                    if (used != s.size()) ok = false;
                } catch (...) {
                    ok = false;
                }
            } else {
                ok = false;
            }
        }
        if (ok) {
            view.extent = {"范围：[" + f1(vals[0]) + ", " + f1(vals[1]) +
                               "] · [" + f1(vals[2]) + ", " + f1(vals[3]) + "]",
                           true};
        }
    }

    // issues + warnings combined, first 5, joined by newlines.
    // Python `str(item)`: strings render bare; other values use repr()
    // (True/False/None, numbers, {'k': 'v'} single-quote dict repr).
    std::vector<std::string> combined;
    auto collect = [&](const char* key) {
        if (!report.contains(key) || !report.at(key).is_array()) return;
        for (const auto& item : report.at(key)) {
            combined.push_back(py_str(item));
        }
    };
    collect("issues");
    collect("warnings");
    if (!combined.empty()) {
        std::string text;
        const std::size_t n = std::min<std::size_t>(combined.size(), 5);
        for (std::size_t i = 0; i < n; ++i) {
            if (i) text += "\n";
            text += combined[i];
        }
        view.issues = {text, true};
    }
    return view;
}

}  // namespace pwb::ui_pages_data
