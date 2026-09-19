#pragma once

// Port of paleo_workbench/ui/workstation/tool_surface.py (UI-12).
// Context-driven tool surface (V8): presentation adapter over the
// CANONICAL evaluator — pwb::tool_policy holds every gate rule; this
// module must never grow a second enabled/visible/reason judgment
// (Goal V8 M1). Presentation differences (toolbar hide vs palette
// disable) are chosen by consumers from `visible`/`disabled_reason`;
// reason strings pass through verbatim.
//
// Contents:
//  * re-export of the canonical symbols (ToolAvailability /
//    ToolContextSnapshot / evaluate_tool / evaluate_all / tool_groups /
//    stage_group_visibility / layer_caption);
//  * QgisCapabilitySnapshot: runtime canvas-backend tri-state
//    presentation (native/degraded/unavailable/unknown) — distinct from
//    the compile-time bridge manifest authority;
//  * LayerCapabilitySnapshot: active-layer presentation facts for the
//    status bar / provider / inspector, flattenable into a canonical
//    ToolContextSnapshot via layer_facts();
//  * tool_context_from_ui_snapshot: UIContextSnapshot -> canonical
//    ToolContextSnapshot adaptation (palette context).
//
// Qt-free.

#include <map>
#include <optional>
#include <string>
#include <vector>

#include <pwb/tool_policy/tool_availability.hpp>
#include <pwb/tool_policy/tool_context.hpp>
#include <pwb/ui_workstation/ui_context.hpp>

namespace pwb::ui_workstation {

// Full-surface availability (toolbar/menu single refresh; consumers
// diff). Direct pass-through to the canonical evaluator.
inline std::map<std::string, tool_policy::ToolAvailability>
availability_for_context(const tool_policy::ToolContextSnapshot& ctx) {
    return tool_policy::evaluate_all(ctx);
}

// Runtime canvas-backend tri-state. None is not allowed — unknown must
// be explicit mode="unknown" (fail-closed).
struct QgisCapabilitySnapshot {
    std::string mode = "unknown";  // native|degraded|unavailable|unknown
    std::string reason;

    bool native_ready() const { return mode == "native"; }
    bool operator==(const QgisCapabilitySnapshot&) const = default;
};

// Presentation facts of the active layer (conclusion fields come from
// domain authorities — editable/block_reason are the role-gate verdict;
// kind is a GEOMETRY_KINDS value; maturity is an ArtifactMaturity value).
// Evaluation input enters the canonical ToolContextSnapshot through
// layer_facts().
struct LayerCapabilitySnapshot {
    std::optional<std::string> layer_id;
    std::optional<std::string> name;
    std::optional<std::string> role;
    std::optional<std::string> role_label;
    std::optional<std::string> kind;
    std::optional<std::string> maturity;
    std::optional<bool> editable;
    std::optional<std::string> block_reason;
    bool frozen = false;
    bool missing = false;
    bool degraded = false;

    bool operator==(const LayerCapabilitySnapshot&) const = default;
};

// Layer-level menu presentation facts (V10 M5: tree context menus
// consume the canonical evaluator). `raw_protected` is a menu
// ORCHESTRATION fact (RAW layer shows the "copy as draft" workflow
// entry), not a new gate.
struct LayerMenuFacts {
    std::optional<tool_policy::ToolAvailability> toggle_editing;
    std::optional<tool_policy::ToolAvailability> repair_geometry;
    bool raw_protected = false;
};

// UIContextSnapshot -> canonical ToolContextSnapshot (palette use).
// Missing inputs (selection count/undo stack/dirty etc.) use
// conservative values — palette applicability only needs
// "why unavailable" precision; the execution side re-gates with the
// full context.
tool_policy::ToolContextSnapshot tool_context_from_ui_snapshot(
    const UIContextSnapshot& snap);

// Layer facts flattening (canonical build_tool_context(layer_facts=...)
// input parity — the C++ ToolContextSnapshot takes the same flat fields).
void apply_layer_facts(const LayerCapabilitySnapshot& layer,
                       tool_policy::ToolContextSnapshot& ctx);

}  // namespace pwb::ui_workstation
