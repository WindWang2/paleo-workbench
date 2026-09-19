#pragma once

// UI-11 — workflow_contract_panel.py Qt-free semantics: the ordered
// (text, primary, warn) line spec the panel renders for one contract.
// STATUS_ZH / IMPL_ZH vocabularies are verbatim; the readiness report is
// optional (project unbound → "未绑定工程" line, Python parity).

#include "pwb/workflow_contracts/models.hpp"
#include "pwb/workflow_contracts/readiness.hpp"

#include <optional>
#include <string>
#include <vector>

namespace pwb::ui_review {

struct ContractLine {
    std::string text;
    bool primary = false;  // TEXT_PRIMARY + weight 600
    bool warn = false;     // WARNING token (wins over primary in Python)
};

// refresh() parity: null contract → the single warn "未知模块：<id>" line
// (Python: f"未知模块：{self._contract_id}"); readiness_report nullopt →
// "当前状态：未绑定工程". dev_mode appends the 开发/咨询详情 block.
// title_text returns what the panel header shows (name_zh or name —
// "" when the contract is unknown).
std::vector<ContractLine>
contract_panel_lines(const workflow_contracts::DomainWorkflowContract* c,
                     const workflow_contracts::ReadinessReport* report,
                     bool dev_mode, const std::string& contract_id = "");

std::string contract_title_text(
    const workflow_contracts::DomainWorkflowContract* c);

}  // namespace pwb::ui_review
