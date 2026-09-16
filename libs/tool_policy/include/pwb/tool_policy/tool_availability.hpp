#pragma once

// Port of paleo_workbench/mapping/tool_availability.py (V8 canonical, V10-V12
// additions). THE tool state machine: pure functions over
// ToolContextSnapshot; no Qt, no QGIS, no I/O. Every disable carries a
// human-readable reason. QAction surfaces only consume the result.

#include <map>
#include <optional>
#include <string>
#include <vector>

#include <pwb/tool_policy/tool_context.hpp>

namespace pwb::tool_policy {

struct ToolAvailability {
    std::string tool_id;
    bool visible = true;
    bool enabled = false;
    bool checked = false;
    std::string disabled_reason;
    bool preferred = false;
    std::vector<std::string> conflicts;
    std::optional<std::string> severity;      // info|warning|critical|unset
    std::optional<std::string> remediation;

    // Python __post_init__ invariants, checked on construction of results via
    // make_ok/make_no in the port; validate() is public for tests.
    void validate() const;
};

// Tool group IA (group -> ordered tool ids).
const std::map<std::string, std::vector<std::string>>& tool_groups();
// Flat ordered namespace of every tool id.
const std::vector<std::string>& tool_ids();
std::string group_of(const std::string& tool_id);
// Chinese presentation of a geometry kind ("" -> 未知).
std::string layer_caption(const std::string& kind);

// Shared gate wording (single source of truth).
std::string raw_layer_gate_reason(const std::string& layer_label = "");
std::string frozen_layer_gate_reason(const std::string& layer_label = "");
std::string stage_lock_reason(const std::string& reason = "");
std::string stage_whitelist_reason(const std::vector<std::string>& stages);

// Group visibility for a stage value (all groups present; unknown stage
// fails closed to the basic groups).
std::map<std::string, bool> stage_group_visibility(const std::string& stage_value);
// Overload mirroring the Python None sentinel: no stage semantics at all.
std::map<std::string, bool> stage_group_visibility_no_stage();

// THE evaluator. Unknown ids: invisible + disabled with an honest reason.
ToolAvailability evaluate_tool(const std::string& tool_id,
                               const ToolContextSnapshot& ctx);
std::map<std::string, ToolAvailability> evaluate_all(const ToolContextSnapshot& ctx);

}  // namespace pwb::tool_policy
