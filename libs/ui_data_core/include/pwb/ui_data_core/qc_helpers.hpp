// qc_helpers.py port — derive (severity, result_text, color_hex) for one
// QC rule from the issue list.
#pragma once

#include "pwb/ui_data_core/json_util.hpp"
#include "pwb/ui_data_core/tokens.hpp"

#include <string>
#include <vector>

namespace pwb::ui_data_core {

// One issue entry as the QC scanner reads it: {"rule", "severity", "message"}.
struct QcIssue {
    std::string rule;
    std::string severity = "warning";
    std::string message;
};

struct QcRuleResult {
    std::string severity;    // "pass" | "warning" | "error"
    std::string text;        // "<label> <message>".rstrip() / "✓通过"
    std::string color_hex;   // tokens color for the severity
};

// Python rstrip() on the label+message join (whitespace incl. \t\n\r etc.).
inline std::string rstrip_copy(std::string value) {
    const auto pos = value.find_last_not_of(" \t\n\r\v\f");
    if (pos == std::string::npos) {
        return {};
    }
    value.erase(pos + 1);
    return value;
}

// derive_rule_result(rule, issues):
//   no match            → ("pass", "✓通过", SUCCESS)
//   matches, any "error"→ severity "error" else "warning"
//   text = f"{label} {first_matching_message}".rstrip()
inline QcRuleResult derive_rule_result(std::string_view rule,
                                       const std::vector<QcIssue>& issues) {
    const auto& labels = tokens::qc_result_labels();
    const auto& colors = tokens::qc_result_colors();

    const QcIssue* first = nullptr;
    std::string severity = "warning";
    for (const auto& issue : issues) {
        if (issue.rule != rule) {
            continue;
        }
        if (first == nullptr) {
            first = &issue;
        }
        if (issue.severity == "error") {
            severity = "error";
            break;
        }
    }
    if (first == nullptr) {
        return {"pass", labels.at("pass"), colors.at("pass")};
    }
    const std::string text = rstrip_copy(labels.at(severity) + " " + first->message);
    return {severity, text, colors.at(severity)};
}

// Json-shaped input convenience (issue dicts from preflight/parsers).
// Faithful ``i.get("rule") == rule`` semantics: only a *string* member can
// equal a str rule (Python ``5 == "5"`` is False); missing/null never match.
// ``i.get("message", "")`` stringifies non-string values like f-string does.
inline QcRuleResult derive_rule_result(std::string_view rule,
                                       const domain::Json& issues) {
    std::vector<QcIssue> parsed;
    if (issues.is_array()) {
        parsed.reserve(issues.size());
        for (const auto& raw : issues) {
            if (!raw.is_object()) {
                continue;
            }
            const auto rit = raw.find("rule");
            const bool matches =
                rit != raw.end() && rit->is_string() &&
                rit->get<std::string>() == rule;
            if (!matches) {
                continue;
            }
            std::string severity = "warning";
            const auto sit = raw.find("severity");
            if (sit != raw.end() && sit->is_string()) {
                severity = sit->get<std::string>();
            }
            std::string message;
            const auto mit = raw.find("message");
            if (mit != raw.end()) {
                message = json_str(*mit);
            }
            parsed.push_back(
                {std::string(rule), std::move(severity), std::move(message)});
        }
    }
    return derive_rule_result(rule, parsed);
}

}  // namespace pwb::ui_data_core
