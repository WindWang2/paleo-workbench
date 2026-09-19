#pragma once

// Port of paleo_workbench/ui/workstation/stage_actions.py's dispatch
// vocabulary (UI-12). The dispatcher is an orchestration seam, NOT a
// scientific implementation: the shell resolves each action_id to a
// dispatch key, and the host binds handlers per key against the real
// production services. This core owns the contract:
//
//  * the action-id → dispatch-key table (incl. aliases:
//    run_factor → open_factor_workbench, stage_qc → run_qa,
//    freeze_input_set → freeze_evidence_set);
//  * the horizon precondition set (_REQUIRES_HORIZON) — 相图按层位进行;
//  * the facies category color vocabulary (_BLANK_FACIES_VALUES /
//    _FACIES_FALLBACK_PALETTE) used when staging facies features.
//
// Unknown actions emit "未知阶段动作：<id>"; handler failures emit
// "阶段动作失败（<id>）：<err>" — the Qt shell does the emitting.
//
// Qt-free.

#include <functional>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <vector>

namespace pwb::ui_workstation {

// Every action_id the dispatcher knows (the Python handler dict keys).
const std::map<std::string, std::string>& stage_action_dispatch_table();

// action_id → dispatch key (handler name after alias resolution);
// empty for unknown ids.
std::string stage_action_dispatch_key(const std::string& action_id);
bool is_known_stage_action(const std::string& action_id);

// _REQUIRES_HORIZON parity — these actions refuse without a mapping
// horizon: "请先设定编图层位（相图按层位进行）".
bool stage_action_requires_horizon(const std::string& action_id);
extern const char* kStageActionHorizonMessage;

// --- facies color vocabulary -------------------------------------------

// _BLANK_FACIES_VALUES parity.
const std::set<std::string>& blank_facies_values();

// The deterministic fallback palette (md5(value) % 8 — identical index
// to Python, so the same facies class gets the same fallback color).
const std::vector<std::string>& facies_fallback_palette();

// facies_category_color parity: feature_color > known class fill
// (geological_symbols _FACIES_CLASSES, injected — empty map = module
// unavailable) > md5-hash fallback palette.
std::string facies_category_color(
    const std::string& value, const std::string& feature_color = "",
    const std::map<std::string, std::string>& known_fills = {});

// --- dispatcher ---------------------------------------------------------

// Handler seam: bound per dispatch key by the host (composite). Handlers
// are void(); exceptions surface through the status listener.
using StageActionHandler = std::function<void()>;
using StageStatusSink = std::function<void(const std::string&)>;

// The dispatch contract, Qt-free: returns the status message that would
// be emitted ("" when the handler ran silently) — the Qt shell forwards
// it to status_message. `mapping_horizon` is the horizon verdict from
// the host (empty = not set).
std::string dispatch_stage_action(
    const std::string& action_id, bool mapping_horizon_set,
    const std::map<std::string, StageActionHandler>& handlers);

}  // namespace pwb::ui_workstation
