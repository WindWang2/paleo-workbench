// UI-06 — module relationship model (module_relationship.py).
//
// Status→tone vocabulary and the step→card routing behind
// ModuleRelationshipCanvas.update_states. Card construction data (titles,
// items, page indices) also lives here — the Qt shell renders it.
// Painted arrows/legend stay in the Qt shell; this is the state math.
#pragma once

#include <map>
#include <string>
#include <vector>

namespace pwb::ui_pages_data {

// Badge tones (module_relationship._STATUS_TONES):
//   complete→success, running→primary, pending→neutral,
//   warning→warning, failed→error; unknown → neutral.
std::string_view step_tone(const std::string& status);

// ModuleCard/DatabaseModuleCard.set_status badge text:
//   tokens.STATUS_TEXT.get(status, "待开始") — note the default is the
//   literal "待开始", NOT the status passthrough used elsewhere.
std::string_view module_status_text(const std::string& status);

// update_states(steps): step_map = {step_type → status} (last wins), then
//   card_data     ← step_map["data_check"]  default "pending"
//   card_sequence ← step_map["factor_map"]  default "pending"
//   card_well     ← step_map["prediction"]  default "pending" (shared)
//   card_seismic  ← step_map["prediction"]  default "pending" (shared)
//   card_facies   ← step_map["map_compile"] default "pending"
//   card_mapping  ← step_map["qc"]          default "pending"
struct StepLike {
    std::string step_type;
    std::string status;
};
// Resolved card state: the status after step_map defaults plus the badge
// text/tone set_status would show.
struct ModuleCardState {
    std::string status;
    std::string badge_text;
    std::string tone;
};
// card key → state for all six cards (defaults applied when the step is
// absent — Python's step_map.get(type, "pending")).
std::map<std::string, ModuleCardState>
step_card_states(const std::vector<StepLike>& steps);

// home_page.update_state's step_to_contract mapping; the first step whose
// mapped contract exists AND whose status ∈ {pending, stale, running,
// warning} wins (loop order = steps order). "" when none applies.
std::string first_incomplete_contract(const std::vector<StepLike>& steps);

// --- card construction data (canvas layout is Qt's business) ---------------
struct ModuleCardSpec {
    std::string key;          // "sequence"|"well"|"seismic"|"facies"|"mapping"|"data"
    std::string title;
    std::vector<std::string> items;
    std::vector<std::string> inputs;
    std::vector<std::string> outputs;
    bool accented = false;
    int page_index = -1;
    // DatabaseModuleCard only: (label, icon_name, page_index) sub cards.
    std::vector<std::tuple<std::string, std::string, int>> sub_items;
    int min_width = 0;
    // grid placement: (row, col, row_span, col_span, align)
    int grid_row = 0, grid_col = 0, grid_row_span = 1, grid_col_span = 1;
    bool align_center = false;  // else AlignTop for row-1 cards
};

// The six cards in construction order (sequence, well, seismic, facies,
// mapping, data) — mirrors the canvas __init__ verbatim.
const std::vector<ModuleCardSpec>& module_card_specs();

}  // namespace pwb::ui_pages_data
