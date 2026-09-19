#pragma once

// Port of paleo_workbench/ui/workstation/agent_panel.py's risk layer
// (UI-12). Read / compute / write are distinct risks; WRITE actions are
// opt-in only (PALEO_AGENT_ALLOW_WRITE env, or the per-plan WRITE grant
// dialog); the action registry is the risk AUTHORITY — the static table
// is only the fallback, and an unassessable action must fail closed
// (treated as WRITE, never silently run).
//
// Qt-free; the panel supplies the registry resolver + the confirm-write
// hook.

#include <functional>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <utility>
#include <vector>

namespace pwb::ui_workstation {

// PALEO_AGENT_ALLOW_WRITE env var name (Python _ENV_ALLOW_WRITE).
extern const char* kAgentAllowWriteEnv;

// Python _env_allows_write_actions: "1"/"true"/"yes" (case-insensitive)
// opt in; anything else keeps READ+COMPUTE.
bool env_allows_write_actions();

enum class AgentRisk { Read, Compute, Write };

// Python _RISK_LABELS.
const std::map<AgentRisk, std::string>& agent_risk_labels();

// Python _ACTION_RISKS static fallback (frozensets → std::set).
const std::map<std::string, std::set<AgentRisk>>&
agent_static_action_risks();

// The plan submitted from the panel (AgentPlan parity).
struct AgentPlanSpec {
    std::string action_id;
    std::map<std::string, std::string> parameters;
    std::optional<
        std::pair<std::string, std::map<std::string, std::string>>>
        followup_action;
    std::string kind;
    std::string summary;
};

// Registry resolver: returns the action's risk set when the harness
// registry is reachable, empty optional when the action is absent or
// the registry itself is unreachable (the caller distinguishes:
// resolved-empty → static fallback; unresolved → also static fallback;
// a plan action missing from BOTH is conservatively {"read"} per the
// Python .get(action_id, {"read"})).
using AgentRiskResolver =
    std::function<std::optional<AgentRisk>(const std::string& action_id)>;

// _plan_risks: union of the primary + followup action risks (registry
// first, static table fallback, {"read"} floor).
std::set<AgentRisk> agent_plan_risks(
    const AgentPlanSpec& plan, const AgentRiskResolver& resolver = {});

// _risk_label: the highest risk in write>compute>read order → its
// label (写入/计算/只读).
std::string agent_plan_risk_label(
    const AgentPlanSpec& plan, const AgentRiskResolver& resolver = {});

// _write_actions_in_plan (#1186): action ids whose REGISTRY risk is
// WRITE. The harness registry is the only authority here — the static
// table is NOT consulted; an unreachable registry (empty resolver) or
// an unresolvable action fails closed (treated as WRITE).
std::vector<std::string> agent_plan_write_actions(
    const AgentPlanSpec& plan, const AgentRiskResolver& resolver = {});

// The permission set for a run: READ+COMPUTE always; WRITE when the
// plan's write actions were granted (dialog) or env opted in.
std::set<AgentRisk> agent_allowed_risks(bool write_ok);

// The consent-line text (Python _consent_text): base sentence plus the
// elevated-grant warning when WRITE is enabled.
std::string agent_consent_text(bool allow_write_actions);

// Session write grants: exact-set membership (Python
// _write_granted_for — the whole plan's write set must be covered).
bool agent_write_granted_for(const std::set<std::string>& grants,
                             const std::vector<std::string>& action_ids);

}  // namespace pwb::ui_workstation
