#pragma once

// UI-14 — MapActionController Qt-free core (map_action_controller.py +
// the static identity half of mapping/action_registry.py).
//
// The Python module holds three vocabularies (checkable canvas tools,
// one-shot commands, surface-extension commands), an icon/label/shortcut
// resolution chain, the availability→QAction text contract, and the
// toolbar group-separator rule. All of that is Qt-free and lives here;
// the QObject shell (pwb_ui_controllers_qt) materializes QActions from
// `action_specs()` and applies `availability_text()` onto them.
//
// action_registry.py parity note: ACTION_SPECS composes
// tool_policy::tool_ids()/tool_groups() (semantic groups stay in the
// evaluator) + ui_workstation::tool_labels()/tool_shortcuts() + the
// surface_icons/risk/surfaces literal sets — composed here, not copied.

#include <map>
#include <optional>
#include <string>
#include <vector>

#include <pwb/tool_policy/tool_availability.hpp>

namespace pwb::ui_controllers {

// ActionSpec parity (static identity — never an availability verdict).
struct MapActionSpec {
    std::string tool_id;
    std::string label;
    std::string group;
    std::string icon;                        // assets/icons/{icon}.svg stem
    std::string risk;                        // read|selection|write|structural
    std::string shortcut;
    std::vector<std::string> surfaces;       // toolbar/palette/layer_menu/canvas_menu
    bool canvas_interaction = false;
    bool requires_native = false;
};

// Risk vocabulary (action_registry.RISK_* parity).
inline constexpr const char* kRiskRead = "read";
inline constexpr const char* kRiskSelection = "selection";
inline constexpr const char* kRiskWrite = "write";
inline constexpr const char* kRiskStructural = "structural";

// MapActionController._TOOL_IDS — checkable canvas MapTools (exclusive
// QActionGroup members; triggering one emits tool_requested).
const std::vector<std::string>& map_tool_ids();

// MapActionController._COMMAND_IDS — command-surface ids (trigger once,
// never mutate current_tool).
const std::vector<std::string>& map_command_ids();

// The checkable subset of _COMMAND_IDS (snapping / topology /
// toggle_editing / avoid_intersections / tracing / vertex_scope).
const std::vector<std::string>& map_checkable_command_ids();

// MapActionController._SURFACE_EXTENSION_IDS — the V7 extension panel
// commands appended after the core set (build order is the contract).
const std::vector<std::string>& map_surface_extension_ids();

// ACTION_SPECS parity — every registered action's static identity,
// composed over the canonical registries. Unknown ids in the
// vocabularies still produce a spec (label falls back to the id).
const std::map<std::string, MapActionSpec>& action_specs();

// Per-action presentation plan: what apply_availability writes onto the
// QAction for one evaluator verdict (+ optional help override).
struct MapActionPresentation {
    bool enabled = false;
    bool visible = true;
    bool checked = false;
    std::string tooltip;
    std::string status_tip;
};

// apply_availability parity: evaluator verdict → presentation plan.
// `help_override` is the (tooltip, statusTip) pair the host derives from
// ui_workstation::explain()/format_*; absent → the name+reason two-line
// fallback (Python `f"{label}\n{reason}"` / `f"{label}（{reason}）"`).
MapActionPresentation availability_text(
    const std::string& action_id,
    const tool_policy::ToolAvailability& result,
    const std::optional<std::pair<std::string, std::string>>& help_override =
        std::nullopt);

// toolbar(title, action_ids) parity: entries are single ids or groups;
// a separator goes BETWEEN grouped entries (a lone id never produces
// one). `ToolbarEntry::separator` marks an explicit split slot.
struct ToolbarEntry {
    bool separator = false;
    std::string action_id;
};
std::vector<ToolbarEntry> toolbar_plan(
    const std::vector<std::vector<std::string>>& action_id_entries);

}  // namespace pwb::ui_controllers
