#include "pwb/ui_ribbon/ribbon_state.hpp"

namespace pwb::ui_ribbon {

RibbonModeMetrics metrics_for(RibbonMode mode) {
    switch (mode) {
    case RibbonMode::Standard:
        return {kStandardBandMinHeight, kStandardBandMaxHeight};
    case RibbonMode::Compact:
        return {kCompactBandMinHeight, kCompactBandMaxHeight};
    case RibbonMode::Collapsed:
        return {0, 0};  // no band — the label (tab) row only
    }
    return {0, 0};
}

bool RibbonModeState::set_compact(bool on) {
    if (compact_ == on) return false;
    compact_ = on;
    return true;
}

bool RibbonModeState::set_collapsed(bool on) {
    if (collapsed_ == on) return false;
    collapsed_ = on;
    // Any collapse-state change ends a temporary expansion: collapsing
    // retracts it, and uncollapsing makes it meaningless (the band is
    // fixed-open now) — the flag never survives outside a collapsed band.
    temporarily_expanded_ = false;
    return true;
}

bool RibbonModeState::toggle_collapsed() { return set_collapsed(!collapsed_); }

bool RibbonModeState::toggle_compact() { return set_compact(!compact_); }

void RibbonModeState::set_temporarily_expanded(bool on) {
    // Only meaningful while collapsed; expanding the band outside a
    // collapsed ribbon is not a temporary state.
    if (!collapsed_) {
        temporarily_expanded_ = false;
        return;
    }
    temporarily_expanded_ = on;
}

CommandState evaluate_command(const CommandEvaluator& evaluator,
                              const std::string& command_id) {
    if (!evaluator) return CommandState{};  // enabled, no reason
    return evaluator(command_id);
}

}  // namespace pwb::ui_ribbon
