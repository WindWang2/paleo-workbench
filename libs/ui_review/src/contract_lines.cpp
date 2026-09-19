#include "pwb/ui_review/contract_lines.hpp"

namespace pwb::ui_review {

namespace {

namespace wc = pwb::workflow_contracts;

std::string status_zh(wc::ReadinessStatus status) {
    switch (status) {
        case wc::ReadinessStatus::READY: return "可执行";
        case wc::ReadinessStatus::PARTIAL: return "部分就绪";
        case wc::ReadinessStatus::BLOCKED: return "阻塞";
        case wc::ReadinessStatus::UNKNOWN: return "未知";
    }
    return "未知";
}

std::string impl_zh(const std::string& value) {
    static const std::vector<std::pair<std::string, std::string>> map = {
        {"PRODUCTION", "生产"},       {"PARTIAL", "部分实现"},
        {"DEMO", "演示"},             {"PLACEHOLDER", "占位"},
    };
    for (const auto& [k, v] : map) {
        if (k == value) {
            return v;
        }
    }
    return value;
}

std::string join(const std::vector<std::string>& items,
                 const std::string& sep) {
    std::string out;
    for (const auto& item : items) {
        if (!out.empty()) {
            out += sep;
        }
        out += item;
    }
    return out;
}

// Python str.rstrip(".") — strip trailing DOT characters only (used for
// "evidence: path.symbol" when symbol is empty → drops the dangling dot).
std::string rstrip_dots(std::string value) {
    while (!value.empty() && value.back() == '.') {
        value.pop_back();
    }
    return value;
}

}  // namespace

std::string contract_title_text(const wc::DomainWorkflowContract* c) {
    if (c == nullptr) {
        return {};
    }
    return c->name_zh.empty() ? c->name : c->name_zh;
}

std::vector<ContractLine>
contract_panel_lines(const wc::DomainWorkflowContract* c,
                     const wc::ReadinessReport* report, bool dev_mode,
                     const std::string& contract_id) {
    std::vector<ContractLine> lines;
    auto add = [&](std::string text, bool primary = false,
                   bool warn = false) {
        lines.push_back({std::move(text), primary, warn});
    };

    if (c == nullptr) {
        // Python: self._add(f"未知模块：{self._contract_id}", warn=True)
        add("未知模块：" + contract_id, false, true);
        return lines;
    }

    add("功能：" + (c->description_zh.empty() ? c->description
                                             : c->description_zh),
        true);
    add("实现状态：" + impl_zh(wc::to_string(c->implementation_status)));

    if (report != nullptr) {
        add("当前状态：" + status_zh(report->status), true,
            report->status == wc::ReadinessStatus::BLOCKED);
        for (const auto& r : report->reasons) {
            add("· " + r.message_zh, false, r.severity == "block");
        }
    } else {
        add("当前状态：未绑定工程");
    }

    add("输入", true);
    for (const auto& inp : c->inputs) {
        add("· " + inp.name + "（" + (inp.required ? "必需" : "可选") + "）");
    }

    add("主要操作", true);
    int index = 0;
    for (const auto& op : c->operations) {
        ++index;
        add(std::to_string(index) + ". " +
            (op.user_action.empty() ? op.name : op.user_action));
        if (!op.software_action.empty()) {
            add("   软件：" + op.software_action);
        }
    }

    if (!c->parameters.empty()) {
        add("参数", true);
        for (const auto& p : c->parameters) {
            add("· " + p.name + " [" + wc::to_string(p.category) + "]");
        }
    }

    add("输出", true);
    for (const auto& out : c->outputs) {
        add("· " + out.name + "（" + out.output_class + "）");
    }

    add("上游", true);
    const std::string upstream = join(c->upstream_contract_ids, "、");
    add("· " + (upstream.empty() ? std::string("无") : upstream));
    add("下游", true);
    const std::string downstream = join(c->downstream_contract_ids, "、");
    add("· " + (downstream.empty() ? std::string("无") : downstream));

    add("QC", true);
    if (c->qc_rules.empty()) {
        add("· （未声明）");
    }
    for (const auto& qc : c->qc_rules) {
        add("· " + qc.name + " [" + wc::to_string(qc.severity) + "]");
    }

    add("待专家确认", true);
    std::vector<const wc::ExpertConsultationQuestion*> open_q;
    for (const auto& q : c->expert_questions) {
        if (q.status == wc::ExpertQuestionStatus::OPEN) {
            open_q.push_back(&q);
        }
    }
    if (open_q.empty()) {
        add("· 无开放问题");
    }
    for (const auto* q : open_q) {
        add("· [" + wc::to_string(q->priority) + "] " + q->question, false,
            true);
    }

    if (dev_mode) {
        add("开发/咨询详情", true);
        add("contract id: " + c->id);
        const std::string ops = join(c->datarun_operations, ", ");
        add("DataRun ops: " + (ops.empty() ? std::string("—") : ops));
        for (std::size_t i = 0;
             i < c->source_evidence.size() && i < 8; ++i) {
            const auto& e = c->source_evidence[i];
            add(rstrip_dots("evidence: " + e.path + "." + e.symbol));
        }
        for (const auto& q : c->expert_questions) {
            add("Q " + q.id + ": certainty=" + wc::to_string(q.certainty));
        }
    }
    return lines;
}

}  // namespace pwb::ui_review
