// UI-06 — qc_helpers.derive_rule_result + result_summary + action_header.
#include <pwb/ui_pages_data/qc_summary.hpp>
#include <pwb/ui_pages_data/vocab.hpp>

namespace pwb::ui_pages_data {
namespace {

using pwb::domain::Json;

std::string jstr(const Json& v) {
    return v.is_string() ? v.get<std::string>() : std::string();
}

// Python ``value or "—"`` + f-string str(): truthy values stringify,
// falsy/missing → "". (0/0.0/False/"" are all falsy in Python.)
std::string jstr_loose(const Json& v) {
    if (v.is_string()) return v.get<std::string>();
    if (v.is_number_integer() || v.is_number_unsigned()) {
        const long long n = v.get<long long>();
        return n == 0 ? "" : std::to_string(n);
    }
    if (v.is_number_float()) {
        const double d = v.get<double>();
        return d == 0.0 ? "" : v.dump();
    }
    if (v.is_boolean()) return v.get<bool>() ? "True" : "";
    return "";
}

// Python str.rstrip() — strips the same trailing whitespace set.
std::string rstrip(std::string s) {
    while (!s.empty()) {
        const char c = s.back();
        if (c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\v' ||
            c == '\f')
            s.pop_back();
        else
            break;
    }
    return s;
}

// QC_RESULT_LABELS keys are pass/warning/error.
std::string_view qc_label(std::string_view severity) {
    if (severity == "pass") return "✓通过";
    if (severity == "warning") return "!警告";
    return "!待处理";
}

// QC_RESULT_COLORS token keys (hex lives in the theme palette).
std::string_view qc_color_token(std::string_view severity) {
    if (severity == "pass") return "SUCCESS";
    if (severity == "warning") return "WARNING";
    return "ERROR_RED";
}

}  // namespace

RuleResult derive_rule_result(const std::string& rule, const Json& issues) {
    // matching = [i for i in issues if i.get("rule") == rule]
    std::vector<const Json*> matching;
    if (issues.is_array()) {
        for (const auto& issue : issues) {
            if (issue.is_object() &&
                jstr(issue.value("rule", Json())) == rule)
                matching.push_back(&issue);
        }
    }
    if (matching.empty()) {
        return {"pass", std::string(qc_label("pass")), "SUCCESS"};
    }
    std::string severity = "warning";
    for (const Json* issue : matching) {
        const std::string s =
            jstr(issue->value("severity", Json("warning")));
        if (s == "error") {
            severity = "error";
            break;
        }
    }
    const std::string message =
        jstr(matching.front()->value("message", Json()));
    return {severity,
            rstrip(std::string(qc_label(severity)) + " " + message),
            std::string(qc_color_token(severity))};
}

QcSummary summarize_qc(const Json& reports, const Json& artifacts) {
    QcSummary summary;
    // `if reports:` — Python truthiness (non-empty list).
    if (reports.is_array() && !reports.empty()) {
        const Json& report = reports[0];
        const Json rules = report.value("rules", Json::array());
        const Json issues = report.value("issues", Json::array());
        if (rules.is_array()) {
            for (const auto& rule : rules) {
                const RuleResult result =
                    derive_rule_result(jstr(rule), issues);
                if (result.severity == "error")
                    ++summary.error_count;
                else if (result.severity == "warning")
                    ++summary.warning_count;
                else
                    ++summary.pass_count;
            }
        }
    }
    if (summary.error_count > 0) {
        summary.advisory = "建议先处理待处理项后再输出成果";
        summary.advisory_token = "ERROR_RED";
    } else {
        summary.advisory = "全部通过，可输出成果";
        summary.advisory_token = "SUCCESS";
    }
    if (artifacts.is_array()) {
        for (const auto& artifact : artifacts) {
            summary.export_rows.push_back(
                "• " + jstr(artifact.value("format", Json())) + " — " +
                jstr(artifact.value("output_path", Json())));
        }
    }
    return summary;
}

ActionHeaderState resolve_action_header(const Json& reports,
                                        const Json& docs) {
    ActionHeaderState state;
    std::string horizon = "—";
    const bool has_reports = reports.is_array() && !reports.empty();
    const bool has_docs = docs.is_array() && !docs.empty();
    if (has_reports) {
        const std::string linked_id =
            jstr(reports[0].value("linked_map_document_id", Json()));
        for (const auto& doc : docs.is_array() ? docs : Json::array()) {
            if (jstr(doc.value("id", Json())) == linked_id) {
                const Json h = doc.value("linked_target_horizon", Json());
                const std::string hs = jstr_loose(h);
                horizon = hs.empty() ? "—" : hs;
                break;
            }
        }
    } else if (has_docs) {
        const Json h = docs.back().value("linked_target_horizon", Json());
        const std::string hs = jstr_loose(h);
        horizon = hs.empty() ? "—" : hs;
    }
    state.title =
        "成图与审核 · " + horizon + " 古地理图（自动质检 + 人工审核）";
    state.finalize_enabled = has_docs;

    // Rules chips: first report's rules, else DEFAULT_QC_RULES.
    std::string chips;
    bool used_report_rules = false;
    if (has_reports) {
        const Json rules = reports[0].value("rules", Json::array());
        if (rules.is_array() && !rules.empty()) {
            used_report_rules = true;
            bool first = true;
            for (const auto& rule : rules) {
                if (!first) chips += " · ";
                first = false;
                chips += jstr(rule);
            }
        }
    }
    if (!used_report_rules) {
        bool first = true;
        for (const auto& rule : kDefaultQcRules) {
            if (!first) chips += " · ";
            first = false;
            chips += std::string(rule);
        }
    }
    state.rules_line = "检查规则: " + chips;
    state.run_enabled = has_docs;
    state.export_enabled = has_reports;
    return state;
}

}  // namespace pwb::ui_pages_data
