#include "pwb/ui_review/qc_issue_rows.hpp"

#include "pwb/ui_data_core/qc_helpers.hpp"
#include "pwb/ui_review/tokens.hpp"

namespace pwb::ui_review {

namespace {

bool truthy_member(const domain::Json& obj, const char* key) {
    const auto it = obj.find(key);
    if (it == obj.end() || it->is_null()) {
        return false;
    }
    if (it->is_boolean()) {
        return it->get<bool>();
    }
    if (it->is_number()) {
        return it->get<double>() != 0.0;
    }
    if (it->is_string()) {
        return !it->get<std::string>().empty();
    }
    if (it->is_array() || it->is_object()) {
        return !it->empty();  // Python truthiness: empty containers are falsy
    }
    return true;
}

std::string str_member(const domain::Json& obj, const char* key) {
    const auto it = obj.find(key);
    if (it != obj.end() && it->is_string()) {
        return it->get<std::string>();
    }
    return {};
}

// ``obj.get(key) or fallback`` — first TRUTHY value wins, then str():
// strings verbatim, bools → True/False (Python repr), numbers → repr-ish.
std::string truthy_str_member(const domain::Json& obj, const char* key) {
    const auto it = obj.find(key);
    if (it == obj.end() || it->is_null() || !truthy_member(obj, key)) {
        return {};
    }
    if (it->is_string()) {
        return it->get<std::string>();
    }
    if (it->is_boolean()) {
        return it->get<bool>() ? "True" : "False";
    }
    if (it->is_number_integer() || it->is_number_unsigned()) {
        return std::to_string(it->get<long long>());
    }
    if (it->is_number()) {
        return it->dump();
    }
    // Truthy container — Python str(dict/list) is a repr we can't
    // reproduce meaningfully; the callers only ever see scalar refs.
    return {};
}

}  // namespace

std::vector<domain::Json>
spatial_issues_of(const domain::Json& issues) {
    std::vector<domain::Json> out;
    if (!issues.is_array()) {
        return out;
    }
    for (const auto& issue : issues) {
        if (!issue.is_object()) {
            continue;  // Python skips non-dict entries verbatim
        }
        if (truthy_member(issue, "geometry") ||
            truthy_member(issue, "centroid")) {
            out.push_back(issue);
        }
    }
    return out;
}

std::map<std::string, std::vector<domain::Json>>
spatial_issues_by_rule(const domain::Json& issues) {
    std::map<std::string, std::vector<domain::Json>> by_rule;
    for (const auto& issue : spatial_issues_of(issues)) {
        by_rule[str_member(issue, "rule")].push_back(issue);
    }
    return by_rule;
}

std::vector<QcIssueRow> qc_issue_rows(const domain::Json& rules,
                                      const domain::Json& issues) {
    const auto by_rule = spatial_issues_by_rule(issues);
    const auto& descriptions = tokens::rule_descriptions();
    std::vector<QcIssueRow> rows;
    if (!rules.is_array()) {
        return rows;
    }
    for (const auto& rule_json : rules) {
        if (!rule_json.is_string()) {
            continue;
        }
        const std::string rule = rule_json.get<std::string>();
        QcIssueRow row;
        row.rule = rule;
        const auto dit = descriptions.find(rule);
        row.description = dit != descriptions.end() ? dit->second : rule;
        const auto result =
            ui_data_core::derive_rule_result(rule, issues);
        row.severity = result.severity;
        row.result_text = result.text;
        row.result_color = result.color_hex;
        const auto sit = by_rule.find(rule);
        if (sit != by_rule.end() && !sit->second.empty()) {
            const domain::Json& first = sit->second.front();
            std::string loc = truthy_str_member(first, "feature_id");
            if (loc.empty()) {
                loc = truthy_str_member(first, "ref");
            }
            if (loc.empty()) {
                loc = "可定位";
            }
            if (sit->second.size() > 1) {
                loc += " (+" + std::to_string(sit->second.size() - 1) + ")";
            }
            row.location = loc;
        } else {
            row.location = "—";
        }
        rows.push_back(std::move(row));
    }
    return rows;
}

}  // namespace pwb::ui_review
