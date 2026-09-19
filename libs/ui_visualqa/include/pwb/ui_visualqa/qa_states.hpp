#pragma once

// UI-16 — visual-QA state/scenario registries + constants.
//
// Port of the shot-table vocabulary across visual_qa_v{6..11}.py: every
// capture state name, the WRITE-grant action fixture, the palette filter
// words, the window-size ladder, and the V11 scenario/theme-matrix tables.
// The *semantics* of each state (drive recipe + check list) live in
// qa_checks.hpp / qt/qa_driver.hpp — this header is the registry surface
// the screenshot harness consumes. Qt-free.

#include <string>
#include <vector>

namespace pwb::ui_visualqa {

// ---- V6 (visual_qa_v6.py) ----------------------------------------------

// V6_STATES: the six new capture states (file names = state names).
const std::vector<std::string>& v6_states();

// WRITE_GRANT_ACTION_IDS: real registry WRITE actions the grant-dialog
// fixture uses (no "unknown action" degradation on the card).
const std::vector<std::string>& write_grant_action_ids();

// PALETTE_CONTEXT_FILTER: filter word hitting a stage-2-scoped command
// (current stage 1 -> disabled + reason visible).
const std::string& palette_context_filter();

// ---- V7 (visual_qa_v7.py) ----------------------------------------------

// V7_STATES: tool availability / tree decorations / cancelling / overflow /
// inspector extension states.
const std::vector<std::string>& v7_states();

// ---- V8 (visual_qa_v8.py) ----------------------------------------------

// V8_STATES: canonical-contract deterministic states.
const std::vector<std::string>& v8_states();

// ---- V9 (visual_qa_v9.py) ----------------------------------------------

// V9_STATES: adaptive workstation layout states.
const std::vector<std::string>& v9_states();

// Target window sizes (logical px; offscreen platform does not scale).
struct QaSize {
    int width = 0;
    int height = 0;
};
inline constexpr QaSize kCompactSize{1000, 700};
inline constexpr QaSize kWideSize{1920, 1080};
inline constexpr QaSize kUltrawideSize{2560, 1440};
inline constexpr QaSize kNarrowSize{960, 600};
// Python's mid-sequence (1600, 900) resize between prime steps.
inline constexpr QaSize kPrimeSize{1600, 900};

// ---- V10 (visual_qa_v10.py) --------------------------------------------

// V10_STATES: professional authoring-UX surface states.
const std::vector<std::string>& v10_states();

inline constexpr QaSize kCompact1366{1366, 768};

// ---- V11 (visual_qa_v11.py) --------------------------------------------

// V11_SCENARIOS: scenario names (check keys + harness render names).
const std::vector<std::string>& v11_scenarios();

// THEME_MATRIX_THEMES / _SIZES: the scenario-10 combination axes.
const std::vector<std::string>& theme_matrix_themes();
const std::vector<QaSize>& theme_matrix_sizes();

// PALETTE_STAGE_FILTER: stage-scoped filter word (same source as the V6
// PALETTE_CONTEXT_FILTER — kept under the V11 name for parity).
const std::string& palette_stage_filter();
// PALETTE_TOOL_FILTER: surface tool-group filter word (map: commands get
// the action_help full-explanation tooltip incl. 前置条件 rows).
const std::string& palette_tool_filter();

// ---- shot tables ---------------------------------------------------------

// One (state -> drive) registration entry. `needs_project` distinguishes
// the empty-project states that consume the none_factory (V8's
// empty_project_tool_surface parity); the project factory itself is a
// host concern — the table only records which states take it.
struct QaShotEntry {
    std::string state;
    bool needs_project = true;
};

// v6/v7/v8/v9/v10_shot_table parity — ordered by Python registration.
const std::vector<QaShotEntry>& v6_shot_table();
const std::vector<QaShotEntry>& v7_shot_table();
const std::vector<QaShotEntry>& v8_shot_table();
const std::vector<QaShotEntry>& v9_shot_table();
const std::vector<QaShotEntry>& v10_shot_table();

// v11_shot_table parity: scenario -> builder-name table (the builders
// themselves live in the qt target).
const std::vector<std::string>& v11_shot_table();

// scenario_needs_workstation_shell parity — see ledger divergence note:
// in C++ only first_open_empty_shell constructs a full workstation shell
// (via the injected QaShellSurface); command_palette_disabled_reason is
// built directly on the real CommandPalette + CommandRegistry evaluator,
// which IS the authoritative verdict path the Python shell wires.
bool scenario_needs_workstation_shell(const std::string& name);

// Every registered state name across V6..V10 (drive dispatch table).
const std::vector<std::string>& all_v6_v10_states();

}  // namespace pwb::ui_visualqa
