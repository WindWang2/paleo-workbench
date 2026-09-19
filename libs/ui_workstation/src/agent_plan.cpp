#include "pwb/ui_workstation/agent_plan.hpp"

#include <algorithm>
#include <cctype>
#include <cstdlib>

namespace pwb::ui_workstation {

const char* kAgentAllowWriteEnv = "PALEO_AGENT_ALLOW_WRITE";

bool env_allows_write_actions() {
    const char* raw = std::getenv(kAgentAllowWriteEnv);
    if (raw == nullptr) return false;
    std::string v(raw);
    std::transform(v.begin(), v.end(), v.begin(),
                   [](unsigned char c) { return std::tolower(c); });
    return v == "1" || v == "true" || v == "yes";
}

const std::map<AgentRisk, std::string>& agent_risk_labels() {
    static const std::map<AgentRisk, std::string> labels = {
        {AgentRisk::Read, "只读"},
        {AgentRisk::Compute, "计算"},
        {AgentRisk::Write, "写入"},
    };
    return labels;
}

const std::map<std::string, std::set<AgentRisk>>&
agent_static_action_risks() {
    using R = AgentRisk;
    static const std::map<std::string, std::set<R>> risks = {
        {"well.list", {R::Read}},
        {"well.open", {R::Read, R::Compute}},
        {"well.create_display", {R::Read, R::Compute}},
        {"workflow.status", {R::Read}},
        {"workspace.describe_context", {R::Read}},
        // Harness 2.0 workflow/recipe surface.
        {"workflow.run", {R::Compute}},
        {"workflow.resume", {R::Compute}},
        {"workflow.cancel", {R::Compute}},
        {"workflow.describe", {R::Read}},
        {"workflow.describe_reproduction", {R::Read}},
        {"workflow.validate", {R::Read}},
        {"recipe.save", {R::Write}},
        {"recipe.load", {R::Read}},
        {"recipe.clone", {R::Compute}},
    };
    return risks;
}

namespace {

// One action's risk set: registry first, static table fallback,
// {"read"} floor (Python _risk_of parity).
std::set<AgentRisk> risk_of(const std::string& action_id,
                            const AgentRiskResolver& resolver) {
    if (resolver) {
        if (auto r = resolver(action_id)) {
            return {*r};
        }
    }
    const auto& table = agent_static_action_risks();
    const auto it = table.find(action_id);
    if (it != table.end()) {
        return it->second;
    }
    return {AgentRisk::Read};
}

}  // namespace

std::set<AgentRisk> agent_plan_risks(const AgentPlanSpec& plan,
                                     const AgentRiskResolver& resolver) {
    std::set<AgentRisk> risks = risk_of(plan.action_id, resolver);
    if (plan.followup_action.has_value()) {
        const auto followup = risk_of(plan.followup_action->first,
                                      resolver);
        risks.insert(followup.begin(), followup.end());
    }
    return risks;
}

std::string agent_plan_risk_label(const AgentPlanSpec& plan,
                                  const AgentRiskResolver& resolver) {
    const auto risks = agent_plan_risks(plan, resolver);
    static const AgentRisk order[] = {AgentRisk::Write, AgentRisk::Compute,
                                      AgentRisk::Read};
    for (const AgentRisk r : order) {
        if (risks.count(r)) {
            return agent_risk_labels().at(r);
        }
    }
    return agent_risk_labels().at(AgentRisk::Read);
}

std::vector<std::string> agent_plan_write_actions(
    const AgentPlanSpec& plan, const AgentRiskResolver& resolver) {
    std::vector<std::string> ids = {plan.action_id};
    if (plan.followup_action.has_value()) {
        ids.push_back(plan.followup_action->first);
    }
    // #1186: the harness registry is the ONLY authority here — the
    // static table is NOT consulted; an unreachable registry makes every
    // action a write action (fail closed).
    if (!resolver) return ids;
    std::vector<std::string> write;
    for (const auto& id : ids) {
        const auto risk = resolver(id);
        if (!risk.has_value() || *risk == AgentRisk::Write) {
            write.push_back(id);
        }
    }
    return write;
}

std::set<AgentRisk> agent_allowed_risks(bool write_ok) {
    std::set<AgentRisk> allowed = {AgentRisk::Read, AgentRisk::Compute};
    if (write_ok) allowed.insert(AgentRisk::Write);
    return allowed;
}

std::string agent_consent_text(bool allow_write_actions) {
    const std::string base =
        "当前工程、活动文档、选择与参数会作为本次受控动作的上下文。";
    if (allow_write_actions) {
        return base +
               "已显式开启 WRITE 权限（PALEO_AGENT_ALLOW_WRITE）——"
               "写入/导出类动作将可执行。";
    }
    return base;
}

bool agent_write_granted_for(const std::set<std::string>& grants,
                             const std::vector<std::string>& action_ids) {
    for (const auto& id : action_ids) {
        if (!grants.count(id)) return false;
    }
    return true;
}

}  // namespace pwb::ui_workstation
