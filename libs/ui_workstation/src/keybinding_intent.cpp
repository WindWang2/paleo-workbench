#include "pwb/ui_workstation/keybinding_intent.hpp"

namespace pwb::ui_workstation {

namespace {

bool no_modifiers(const KeyEventFacts& f) {
    return !f.control && !f.shift && !f.alt;
}

}  // namespace

bool tab_cycle_scope_active(const std::string& mode_value) {
    return mode_value == "digitizing" || mode_value == "adjusting";
}

KeyIntent qc_hub_visibility_intent(bool shown) {
    return shown ? KeyIntent::QcHubShown : KeyIntent::QcHubHidden;
}

KeyIntent escape_chain_step(const KeyEventFacts& facts) {
    // Python handle_escape order (D9):
    //  1) digitizing gesture live (tool.points non-empty) → cancel the
    //     gesture, keep the tool;
    //  2) onion active → end the epoch compare;
    //  3) an active non-pan tool → deactivate to pan;
    //  4) QC hub visible → close it;
    //  5) else FSM ESC only.
    if (facts.active_tool_has_points) {
        return KeyIntent::EscapeCancelGesture;
    }
    if (facts.onion_active) {
        return KeyIntent::EscapeEndOnion;
    }
    if (!facts.active_tool_id.empty() && facts.active_tool_id != "pan") {
        return KeyIntent::EscapeDeactivateTool;
    }
    if (facts.qc_hub_visible) {
        return KeyIntent::EscapeCloseQcHub;
    }
    return KeyIntent::EscapeDispatchFsm;
}

KeyDecision interpret_key(const KeyEventFacts& facts) {
    // Text inputs get first refusal (D5) — everything passes through.
    if (facts.text_input_focused) {
        return {};
    }
    if (facts.type == KeyEventType::Press) {
        switch (facts.key) {
        case KeyCode::Space:
            if (no_modifiers(facts) &&
                !facts.active_tool_id.empty() &&
                facts.active_tool_id != "pan") {
                return {KeyIntent::BeginTemporaryPan, true};
            }
            // Space with no restorable tool still consumes? Python:
            // begin_temporary_pan() returns early but the event IS
            // consumed (return True) whenever Space+NoModifier hits.
            if (no_modifiers(facts)) {
                return {KeyIntent::BeginTemporaryPan, true};
            }
            return {};
        case KeyCode::Tab:
            if (tab_cycle_scope_active(facts.mode_value)) {
                return {KeyIntent::CycleSelection, true};
            }
            return {};  // pass through — no focus-chain theft
        case KeyCode::KeyZ:
            if (no_modifiers(facts)) {
                return {KeyIntent::ZoomCenterIn, true};
            }
            return {};
        case KeyCode::KeyX:
            if (no_modifiers(facts)) {
                return {KeyIntent::ZoomCenterOut, true};
            }
            return {};
        case KeyCode::KeyD:
            if (facts.control) {
                return {KeyIntent::PickFaciesFromSelection, true};
            }
            return {};
        case KeyCode::Escape:
            return {escape_chain_step(facts), true};
        default:
            return {};
        }
    }
    // Release: Space while a pan restore is pending restores the tool.
    if (facts.key == KeyCode::Space && facts.pan_restore_pending) {
        return {KeyIntent::ReleaseTemporaryPan, true};
    }
    return {};
}

}  // namespace pwb::ui_workstation
