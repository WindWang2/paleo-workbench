#pragma once

// Port of paleo_workbench/ui/workstation/action_help.py (UI-12).
// Contextual help / explainability (M4): the help system derived from the
// canonical contract.
//
// Constraints (Goal V8 M4):
//  * ALL dynamic facts come from the evaluator: availability / disabled
//    reason / checked are produced by tool_policy::evaluate_tool — this
//    module keeps no second state table and never rewrites the verdict;
//  * static facts live in tool_help.hpp (labels / requirements / impact /
//    modifies-data / creates-version / background-task / shortcuts /
//    stage + layer-kind scope);
//  * consumers: toolbar tooltip / statusTip / palette details /
//    inspector hint / empty-state guidance / agent action discovery —
//    all go through explain() + the format_* functions.
//
// Qt-free.

#include <optional>
#include <string>

#include <pwb/tool_policy/tool_availability.hpp>
#include <pwb/tool_policy/tool_context.hpp>
#include <pwb/ui_workstation/tool_help.hpp>

namespace pwb::ui_workstation {

// The complete explainability record for one action under one context
// (every field is renderable).
struct ActionExplanation {
    std::string tool_id;
    std::string label;
    tool_policy::ToolAvailability availability;
    std::string requirements;
    // Currently missing precondition (= evaluator verdict; empty when
    // available).
    std::string missing;
    std::string impact;
    bool modifies_data = false;
    bool creates_version = false;
    bool background_task = false;
    std::string shortcut;
    std::string stages;
    std::string layer_kinds;
    std::string current_layer;  // active layer name (presentation)
    std::string current_stage;  // current stage (presentation)

    bool available() const { return availability.enabled; }
};

// Assemble one action's contextual help (all dynamic verdicts come from
// the canonical evaluator; unknown tool ids get an honest generic help
// record instead of crashing).
ActionExplanation explain(
    const std::string& tool_id,
    const tool_policy::ToolContextSnapshot& ctx,
    const std::string& layer_name = "");

// Stage caption used by ActionExplanation.current_stage: nullopt ->
// "无阶段语义（legacy 表面）"; known stage -> its label; unknown value ->
// "未知阶段（'<value>'）".
std::string stage_caption(const std::optional<std::string>& stage_value);

// Toolbar tooltip: name + status + reason (+ shortcut).
std::string format_tooltip(const ActionExplanation& explanation);

// Status bar / statusTip single line.
std::string format_status(const ActionExplanation& explanation);

// Palette details / inspector hint — the multi-line full explanation.
std::string format_details(const ActionExplanation& explanation);

}  // namespace pwb::ui_workstation
