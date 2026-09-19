#pragma once

// Port of paleo_workbench/ui/workstation/state_language.py (UI-12).
// Unified state language (V6 §5): one mapping of domain state ->
// glyph + label + tone.
//
// Design constraints:
//  * Dual signal: every state has glyph AND text; tone is only for the
//    style layer (badge/徽标), never the sole signal (readable under
//    high-contrast/color-blind themes).
//  * Honest unknown: unknown value -> 「未知」 + muted; unknown CATEGORY
//    is a programming error -> throws (Python KeyError parity).
//  * Consumers: status-bar workbench segment (workbench_context_text),
//    inspector badges, task center, agent panel. No second color system —
//    tone is interpreted by the existing token/QSS consumers.
//
// Qt-free.

#include <functional>
#include <optional>
#include <string>

#include <pwb/ui_workstation/ui_context.hpp>

namespace pwb::ui_workstation {

struct StateToken {
    std::string glyph;
    std::string label;
    // ok | info | warn | error | muted | locked (style layer interprets)
    std::string tone;

    bool operator==(const StateToken&) const = default;
};

// The unknown-value token (glyph 「·」 label 「未知」 tone muted).
const StateToken& unknown_state_token();

// Look up the vocabulary; unknown values honestly return the unknown
// token, an unknown category throws std::out_of_range (Python KeyError
// parity — programming error surfaced early).
StateToken state_token(const std::string& category,
                       const std::optional<std::string>& value);
StateToken state_token(const std::string& category, const char* value);

// state_language tone -> PwbBadge tone (one-way bridge; badge consumers
// must not re-map). Unknown tone falls back to "neutral".
std::string tone_to_badge(const std::string& tone);

// Status-bar workbench segment text:
// 「阶段 · 编辑目标 · 后端 · 任务」. No tasks -> no task segment; a
// blocked edit target must show its reason; a fallback canvas must be
// visible. `layer_name` resolves the active layer id to a display name
// (nullptr -> the layer segment is skipped, Python parity).
std::string workbench_context_text(
    const UIContextSnapshot& snapshot,
    const std::function<std::string(const std::string&)>& layer_name =
        nullptr);

}  // namespace pwb::ui_workstation
