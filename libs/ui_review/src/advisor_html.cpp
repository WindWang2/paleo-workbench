#include "pwb/ui_review/advisor_html.hpp"

#include "pwb/ui_review/tokens.hpp"

#include <sstream>
#include <string>
#include <vector>

namespace pwb::ui_review {

namespace {

using tokens::kBgSearch;
using tokens::kBorder;
using tokens::kError;
using tokens::kPrimary;
using tokens::kSuccess;
using tokens::kTextPrimary;
using tokens::kTextSecondary;
using tokens::kWarning;

// report.get("issues", []) as a vector of Json objects (non-object members
// never occur in practice; Python iterates whatever the list holds and
// subscripts it — a non-dict would raise, which the dialog never sees).
std::vector<domain::Json> issues_of(const domain::Json& report) {
    std::vector<domain::Json> out;
    const auto it = report.find("issues");
    if (it != report.end() && it->is_array()) {
        for (const auto& item : *it) {
            out.push_back(item);
        }
    }
    return out;
}

std::string get_str(const domain::Json& obj, const char* key) {
    const auto it = obj.find(key);
    if (it != obj.end() && it->is_string()) {
        return it->get<std::string>();
    }
    return {};
}

long long get_int(const domain::Json& obj, const char* key) {
    const auto it = obj.find(key);
    if (it != obj.end() && it->is_number_integer()) {
        return it->get<long long>();
    }
    return 0;
}

std::string badge(const char* text, std::string_view color) {
    std::string out = "<span style='background: ";
    out += color;
    out += "; color: #ffffff; padding: 2px 6px; border-radius: 4px;"
           " font-weight: bold;'>";
    out += text;
    out += "</span>";
    return out;
}

std::string join_faults(const domain::Json& faults) {
    std::string out;
    if (faults.is_array()) {
        bool first = true;
        for (const auto& f : faults) {
            if (!first) {
                out += " & ";
            }
            first = false;
            if (f.is_string()) {
                out += f.get<std::string>();
            }
        }
    }
    return out;
}

}  // namespace

std::string build_advisor_html(const domain::Json& bh_report,
                               const domain::Json& fault_report) {
    const auto bh_issues = issues_of(bh_report);
    const auto fault_issues = issues_of(fault_report);

    bool has_errors = false;
    for (const auto& x : bh_issues) {
        if (get_str(x, "type") == "error") {
            has_errors = true;
            break;
        }
    }
    const std::string bh_badge =
        has_errors ? badge("不通过 (FAIL)", kError)
                   : badge("警告 (WARNING)", kWarning);
    const std::string fault_badge =
        !fault_issues.empty() ? badge("有冲突 (WARNING)", kWarning)
                              : badge("通过 (PASS)", kSuccess);

    std::ostringstream html;
    html << "\n        <h3 style='color: " << kPrimary
         << "; border-bottom: 1px solid " << kBorder
         << "; padding-bottom: 4px;'>▤ 核对概要 (Summary)</h3>\n"
         << "        <table style='width: 100%; border-collapse: collapse;"
            " margin-top: 8px; margin-bottom: 16px;'>\n"
         << "            <tr style='background: " << kBgSearch
         << "; color: " << kTextPrimary << ";'>\n"
         << "                <th style='padding: 8px; text-align: left;'>"
            "复核模块</th>\n"
         << "                <th style='padding: 8px; text-align: center;'>"
            "已检项</th>\n"
         << "                <th style='padding: 8px; text-align: center;'>"
            "诊断状态</th>\n"
         << "            </tr>\n"
         << "            <tr>\n"
         << "                <td style='padding: 8px; border-bottom: 1px solid "
         << kBorder << ";'>钻孔分层一致性</td>\n"
         << "                <td style='padding: 8px; text-align: center; "
            "border-bottom: 1px solid "
         << kBorder << ";'>" << get_int(bh_report, "checked_boreholes")
         << " 个钻孔</td>\n"
         << "                <td style='padding: 8px; text-align: center; "
            "border-bottom: 1px solid "
         << kBorder << ";'>" << bh_badge << "</td>\n"
         << "            </tr>\n"
         << "            <tr>\n"
         << "                <td style='padding: 8px; border-bottom: 1px solid "
         << kBorder << ";'>平行/共面断层核实</td>\n"
         << "                <td style='padding: 8px; text-align: center; "
            "border-bottom: 1px solid "
         << kBorder << ";'>" << get_int(fault_report, "checked_faults")
         << " 条断层</td>\n"
         << "                <td style='padding: 8px; text-align: center; "
            "border-bottom: 1px solid "
         << kBorder << ";'>" << fault_badge << "</td>\n"
         << "            </tr>\n"
         << "        </table>\n\n"
         << "        <h3 style='color: " << kPrimary
         << "; border-bottom: 1px solid " << kBorder
         << "; padding-bottom: 4px;'>⚠ 诊断问题明细 (Issues)</h3>\n"
         << "        ";

    // Borehole details.
    html << "<h4 style='color: " << kError
         << "; margin-bottom: 4px;'>◆ 钻孔层位异常：</h4>"
            "<ul style='margin-top: 0; padding-left: 20px; color: "
         << kTextSecondary << ";'>";
    for (const auto& iss : bh_issues) {
        const bool is_error = get_str(iss, "type") == "error";
        html << "<li><b>" << get_str(iss, "borehole")
             << "</b>: <span style='color: " << (is_error ? kError : kWarning)
             << ";'>" << (is_error ? "✕ 错误" : "⚠️ 警告") << "</span> - "
             << get_str(iss, "message") << "</li>";
    }
    if (bh_issues.empty()) {
        html << "<li>✅ 钻孔间距及分层深度完全一致，无冲突。</li>";
    }
    html << "</ul>";

    // Fault details.
    html << "<h4 style='color: " << kWarning
         << "; margin-bottom: 4px;'>▣ 共面断层预警：</h4>"
            "<ul style='margin-top: 0; padding-left: 20px; color: "
         << kTextSecondary << ";'>";
    for (const auto& iss : fault_issues) {
        const auto fit = iss.find("faults");
        html << "<li>§ <b>"
             << join_faults(fit != iss.end() ? *fit : domain::Json())
             << "</b>: " << get_str(iss, "message") << "</li>";
    }
    if (fault_issues.empty()) {
        html << "<li>✅ 未检测到重叠或共面冲突的断层面。</li>";
    }
    html << "</ul>";

    // Suggestions — derived from the actual issues (never hardcoded names).
    std::vector<std::string> suggestion_items;
    for (const auto& iss : bh_issues) {
        suggestion_items.push_back("<li><b>钻孔 " + get_str(iss, "borehole") +
                                   "</b>: " + get_str(iss, "message") + "</li>");
    }
    for (const auto& iss : fault_issues) {
        const auto fit = iss.find("faults");
        suggestion_items.push_back(
            "<li><b>断层 " +
            join_faults(fit != iss.end() ? *fit : domain::Json()) +
            "</b>: " + get_str(iss, "message") + "</li>");
    }
    if (suggestion_items.empty()) {
        suggestion_items.push_back(
            "<li>规则检查未发现需要修正的层位重叠、终孔超限或共面断层。</li>");
    }
    html << "\n        <h3 style='color: " << kPrimary
         << "; border-bottom: 1px solid " << kBorder
         << "; padding-bottom: 4px;'>✦ 基于规则检查的优化建议 "
            "(Suggestions)</h3>\n"
         << "        <div style='background: " << kBgSearch
         << "; border-left: 4px solid " << kPrimary
         << "; padding: 12px; border-radius: 6px; margin-top: 8px;'>\n"
         << "            <p style='color: " << kTextPrimary
         << "; font-weight: bold; margin: 0 0 8px 0;'>✦ 建模优化建议：</p>\n"
         << "            <ol style='margin: 0; padding-left: 20px; color: "
         << kTextSecondary << "; line-height: 1.6;'>\n";
    for (const auto& item : suggestion_items) {
        html << "                " << item << "\n";
    }
    html << "            </ol>\n        </div>\n        ";
    return html.str();
}

}  // namespace pwb::ui_review
