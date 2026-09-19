// UI-06 — QC result summary model (result_summary.py + action_header.py)
// and the shared rule-result derivation (qc_helpers.derive_rule_result —
// the only out-of-list dependency, replicated here and oracle-verified).
#pragma once

#include <string>
#include <utility>
#include <vector>

#include <pwb/domain/json.hpp>

namespace pwb::ui_pages_data {

// qc_helpers.derive_rule_result: scan issues where issue["rule"] == rule;
// error beats warning; first matching issue's message in the text.
// Returns {severity("pass"|"warning"|"error"), text, token_key}.
struct RuleResult {
    std::string severity;
    std::string text;        // "{label} {message}".rstrip() — label only when no message
    std::string color_token; // tokens.QC_RESULT_COLORS key — keep as token name
};
RuleResult derive_rule_result(const std::string& rule,
                              const pwb::domain::Json& issues);

// --- result_summary.py :: update_state -------------------------------------
struct QcSummary {
    int pass_count = 0;
    int warning_count = 0;
    int error_count = 0;
    std::string advisory;        // "全部通过，可输出成果" | "建议先处理待处理项后再输出成果"
    std::string advisory_token;  // "SUCCESS" | "ERROR_RED"
    // "• {format} — {output_path}" rows; empty → "暂无导出图件" placeholder.
    std::vector<std::string> export_rows;
};

// reports: [{rules: [str], issues: [..]}] — only reports[0] counts rules.
// artifacts: [{format, output_path}].
QcSummary summarize_qc(const pwb::domain::Json& reports,
                     const pwb::domain::Json& artifacts);

// --- action_header.py :: update_state ---------------------------------------
struct ActionHeaderState {
    std::string title;          // "成图与审核 · {horizon} 古地理图（自动质检 + 人工审核）"
    std::string rules_line;     // "检查规则: {a · b · c}"
    bool run_enabled = false;   // has map_documents
    bool export_enabled = false;// has reports
    bool finalize_enabled = false;
};

// reports: [{linked_map_document_id, rules[]}];
// docs: [{id, linked_target_horizon}].
ActionHeaderState resolve_action_header(const pwb::domain::Json& reports,
                                        const pwb::domain::Json& docs);

}  // namespace pwb::ui_pages_data
