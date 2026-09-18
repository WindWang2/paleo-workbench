#include <pwb/workflow_contracts/report.hpp>

#include <fstream>
#include <map>
#include <set>
#include <sstream>

namespace pwb::workflow_contracts {
namespace {

const std::vector<std::pair<std::string, std::string>>& section_order() {
    static const std::vector<std::pair<std::string, std::string>> order = {
        {"data", "数据"},           {"well_log", "测井模块"},
        {"seismic", "地震模块"},    {"interpretation", "地层解释"},
        {"factor", "单因素图"},     {"prediction", "预测"},
        {"mapping", "古地理编图"},  {"qc", "QC"},
        {"export", "导出"},         {"joint", "井震联合"},
        {"modeling", "三维建模"},
    };
    return order;
}

// _cell: (text or "") with "|"→"\|", "\n"→" ", stripped.
std::string cell(const std::string& text) {
    std::string out;
    out.reserve(text.size());
    for (char ch : text) {
        if (ch == '|')
            out += "\\|";
        else if (ch == '\n')
            out += ' ';
        else
            out += ch;
    }
    const auto b = out.find_first_not_of(" \t\n\v\f\r");
    if (b == std::string::npos) return "";
    const auto e = out.find_last_not_of(" \t\n\v\f\r");
    return out.substr(b, e - b + 1);
}

std::string join_ids(const std::vector<std::string>& v) {
    std::string out;
    for (const auto& s : v) out += (out.empty() ? "" : ", ") + s;
    return out;
}

std::string join_lines(const std::vector<std::string>& lines) {
    std::string out;
    for (const auto& l : lines) out += (out.empty() ? "" : "\n") + l;
    return out;
}

std::size_t open_count(const DomainWorkflowContract& c) {
    std::size_t n = 0;
    for (const auto& q : c.expert_questions)
        if (q.status == ExpertQuestionStatus::OPEN) ++n;
    return n;
}

void module_section(const DomainWorkflowContract& c,
                    std::vector<std::string>& lines) {
    lines.push_back("### " +
                    (c.name_zh.empty() ? c.name : c.name_zh) + " (`" +
                    c.id + "`)");
    lines.push_back("");
    lines.push_back("**当前软件功能：** " +
                    (c.description_zh.empty() ? c.description
                                              : c.description_zh));
    lines.push_back("**实现状态：** " +
                    to_string(c.implementation_status));
    lines.push_back("");
    lines.push_back("#### 输入");
    if (c.inputs.empty())
        lines.push_back("- （无结构化输入声明）");
    for (const auto& inp : c.inputs)
        lines.push_back("- " + inp.name + "（" +
                        (inp.required ? "必需" : "可选") + "，" +
                        to_string(inp.cardinality) + "）— " +
                        inp.description);
    lines.push_back("");
    lines.push_back("#### 主要操作");
    int i = 0;
    for (const auto& op : c.operations) {
        ++i;
        lines.push_back(std::to_string(i) + ". **用户：** " +
                        (op.user_action.empty() ? op.name
                                                : op.user_action));
        if (!op.software_action.empty())
            lines.push_back("   **软件：** " + op.software_action);
    }
    lines.push_back("");
    lines.push_back("#### 输出");
    for (const auto& out : c.outputs)
        lines.push_back("- " + out.name + " [" + out.output_class +
                        "] stage=" +
                        (out.data_stage.empty() ? "—" : out.data_stage) +
                        " versioned=" +
                        (out.versioned ? "True" : "False"));
    lines.push_back("");
    lines.push_back("#### 上下游连接");
    lines.push_back("- 上游（合同）：" +
                    (c.upstream_contract_ids.empty()
                         ? "—"
                         : join_ids(c.upstream_contract_ids)));
    lines.push_back("- 下游（合同）：" +
                    (c.downstream_contract_ids.empty()
                         ? "—"
                         : join_ids(c.downstream_contract_ids)));
    if (!c.datarun_operations.empty())
        lines.push_back("- DataRun.operation：" +
                        join_ids(c.datarun_operations));
    lines.push_back("");
    lines.push_back("#### 当前软件规则 / QC");
    for (const auto& qc : c.qc_rules)
        lines.push_back("- [" + to_string(qc.severity) + "] " + qc.name +
                        "（" +
                        (qc.implemented ? "已实现" : "未实现") + "）");
    lines.push_back("");
    lines.push_back("#### 待专家确认");
    bool any_open = false;
    for (const auto& q : c.expert_questions) {
        if (q.status != ExpertQuestionStatus::OPEN) continue;
        any_open = true;
        lines.push_back("- **[" + to_string(q.priority) + "]** " +
                        q.question);
        lines.push_back("  - 现状：" + q.current_software_behavior);
    }
    if (!any_open) lines.push_back("- （无开放问题）");
    lines.push_back("");
}

}  // namespace

std::string generate_consultation_report(
    const WorkflowContractRegistry* registry, const ProjectView* project) {
    const WorkflowContractRegistry& reg =
        registry ? *registry : get_default_registry();
    std::vector<std::string> lines = {
        "# 古地理工作台 — 专业地质工作流咨询报告",
        "",
        "本报告由软件合同（Workflow Contract）自动生成。",
        "标注为 **待专家确认** 的问题不得由软件擅自裁定。",
        "",
        "---",
        "",
        "## 1. 模块总览",
        "",
        "| ID | 名称 | 实现状态 | 开放专家问题数 |",
        "|----|------|----------|----------------|",
    };
    for (const auto& c : reg.list_contracts())
        lines.push_back("| `" + c.id + "` | " +
                        (c.name_zh.empty() ? c.name : c.name_zh) + " | " +
                        to_string(c.implementation_status) + " | " +
                        std::to_string(open_count(c)) + " |");

    lines.push_back("");
    lines.push_back("## 2. 模块关系（合同级潜在依赖）");
    lines.push_back("");
    for (const auto& c : reg.list_contracts()) {
        const std::string up = c.upstream_contract_ids.empty()
                                   ? "—"
                                   : join_ids(c.upstream_contract_ids);
        const std::string down = c.downstream_contract_ids.empty()
                                     ? "—"
                                     : join_ids(c.downstream_contract_ids);
        lines.push_back("- **" +
                        (c.name_zh.empty() ? c.name : c.name_zh) +
                        "** (`" + c.id + "`): 上游 " + up + " → 下游 " +
                        down);
    }

    std::map<std::string, std::vector<const DomainWorkflowContract*>>
        by_cat;
    for (const auto& c : reg.list_contracts()) by_cat[c.category].push_back(&c);

    int sec_i = 3;
    for (const auto& [cat, title] : section_order()) {
        const auto it = by_cat.find(cat);
        if (it == by_cat.end() || it->second.empty()) continue;
        lines.push_back("");
        lines.push_back("## " + std::to_string(sec_i) + ". " + title);
        lines.push_back("");
        ++sec_i;
        for (const auto* c : it->second) module_section(*c, lines);
    }

    lines.push_back("");
    lines.push_back("## " + std::to_string(sec_i) + ". 专家确认问题矩阵");
    lines.push_back("");
    lines.push_back("| 编号 | 模块 | 类别 | 当前软件实现 | 需要确认的问题 | 影"
                    "响范围 | 优先级 | 状态 |");
    lines.push_back("|------|------|------|--------------|----------------|----"
                    "------|--------|------|");
    for (const auto* q : reg.all_expert_questions())
        lines.push_back("| `" + q->id + "` | `" + q->module_id + "` | " +
                        to_string(q->category) + " | " +
                        cell(q->current_software_behavior) + " | " +
                        cell(q->question) + " | " +
                        cell(q->impact_if_unresolved) + " | " +
                        to_string(q->priority) + " | " +
                        to_string(q->status) + " |");

    if (project != nullptr) {
        lines.push_back("");
        lines.push_back("## " + std::to_string(sec_i + 1) +
                        ". 当前工程就绪状态（元数据）");
        lines.push_back("");
        const WorkflowReadinessEvaluator ev(&reg);
        for (const auto& r : ev.evaluate_all(*project)) {
            std::string msgs;
            for (const auto& x : r.reasons)
                msgs += (msgs.empty() ? "" : "; ") + x.message_zh;
            if (msgs.empty()) msgs = "—";
            lines.push_back("- `" + r.contract_id + "`: **" +
                            to_string(r.status) + "** (" +
                            to_string(r.implementation_status) + ") — " +
                            msgs);
        }
    }

    lines.push_back("");
    lines.push_back("---");
    lines.push_back("");
    lines.push_back("*生成器: paleo_workbench.workflow.contracts.report*");
    lines.push_back("");
    return join_lines(lines);
}

std::string generate_gap_report(const WorkflowContractRegistry* registry) {
    const WorkflowContractRegistry& reg =
        registry ? *registry : get_default_registry();
    std::vector<std::string> lines = {
        "# 工作流合同 — 开发缺口报告",
        "",
        "| 模块 | 实现状态 | 缺失校验 | 缺失持久化/版本 | 缺失 lineage op | "
        "Demo-only | 开放专家问题 |",
        "|------|----------|----------|-----------------|---------------"
        "--|-----------|--------------|",
    };
    for (const auto& c : reg.list_contracts()) {
        std::vector<std::string> missing_val;
        bool any_impl = false;
        for (const auto& q : c.qc_rules)
            if (q.implemented) any_impl = true;
        if (!any_impl && c.category != "well_log" &&
            c.category != "seismic" && c.qc_rules.empty())
            missing_val.push_back("no_qc");
        std::vector<std::string> missing_persist;
        for (const auto& o : c.outputs)
            if (o.output_class == "scientific" && !o.versioned)
                missing_persist.push_back(o.id);
        std::vector<std::string> missing_lineage;
        static const std::set<std::string> lineage_ids = {
            "factor_interpolation", "facies_prediction", "export",
            "horizon_interpretation", "paleomap_compile", "quality_control",
        };
        if (lineage_ids.count(c.id) && c.datarun_operations.empty())
            missing_lineage.push_back("no_datarun_op");
        const std::string istat = to_string(c.implementation_status);
        const char* demo =
            (istat == "DEMO" || istat == "PLACEHOLDER") ? "yes" : "no";
        const auto join_csv = [](const std::vector<std::string>& v) {
            std::string out;
            for (const auto& s : v)
                out += (out.empty() ? "" : ",") + s;
            return out.empty() ? std::string("—") : out;
        };
        lines.push_back("| `" + c.id + "` | " + istat + " | " +
                        join_csv(missing_val) + " | " +
                        join_csv(missing_persist) + " | " +
                        join_csv(missing_lineage) + " | " + demo + " | " +
                        std::to_string(open_count(c)) + " |");
    }
    lines.push_back("");
    lines.push_back("## 建议的下一工程优先级（严格来自缺口）");
    lines.push_back("");
    lines.push_back("1. 将 mock 预测与正式交付硬隔离（facies_prediction DEMO）。");
    lines.push_back("2. 为 map_compile/qc 补齐生产路径上的 DataRun 登记调用。");
    lines.push_back("3. 断层完整版本生命周期（当前 PARTIAL 约束折线）。");
    lines.push_back("4. 关闭 P0 专家问题前不要把软件默认值写成地质标准。");
    lines.push_back("");
    return join_lines(lines);
}

std::pair<std::filesystem::path, std::filesystem::path> write_reports(
    const std::filesystem::path& out_dir, const ProjectView* project,
    const WorkflowContractRegistry* registry) {
    std::filesystem::create_directories(out_dir);
    const auto consult = out_dir / "geological_workflow_consultation.md";
    const auto gap = out_dir / "workflow_gap_report.md";
    {
        std::ofstream f(consult, std::ios::binary);
        f << generate_consultation_report(registry, project);
    }
    {
        std::ofstream f(gap, std::ios::binary);
        f << generate_gap_report(registry);
    }
    return {consult, gap};
}

}  // namespace pwb::workflow_contracts
