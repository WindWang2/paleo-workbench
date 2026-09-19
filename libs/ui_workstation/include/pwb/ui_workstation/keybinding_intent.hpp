#pragma once

// Port of paleo_workbench/ui/workstation/keybinding_manager.py's key
// table (UI-12). Qt-free: the manager translates QKeyEvents into
// KeyEventFacts and executes the returned KeyIntent against injected
// hooks. The Python filter semantics live here so they're testable
// headless:
//
//  * text inputs get first refusal (focus_in_text_input — the adapter
//    supplies the verdict, this core never guesses);
//  * Space (no modifiers) press → temporary pan; release → restore the
//    pre-pan tool;
//  * Tab cycles the selection ONLY in DIGITIZING/ADJUSTING_BOUNDARY —
//    otherwise it passes through (no focus-chain theft);
//  * Z/X zoom the canvas center ×1.5 with NO modifiers (Ctrl+Z must not
//    be swallowed);
//  * Ctrl+D picks facies from the selection;
//  * Esc runs the safe-exit chain (gesture cancel → onion/epoch end →
//    deactivate tool → close QC hub → FSM idle) — the chain itself is
//    the Qt shell's because it touches widgets; the core decides WHICH
//    step applies from injected facts.

#include <optional>
#include <string>

namespace pwb::ui_workstation {

// Center zoom factor (Python ZOOM_STEP).
inline constexpr double kKeybindingZoomStep = 1.5;

enum class KeyCode {
    Space,
    Tab,
    KeyZ,
    KeyX,
    KeyD,
    Escape,
    Other,
};

enum class KeyEventType { Press, Release };

// What the adapter knows about the event + world.
struct KeyEventFacts {
    KeyCode key = KeyCode::Other;
    KeyEventType type = KeyEventType::Press;
    bool control = false;
    bool shift = false;
    bool alt = false;
    // focus_in_text_input() verdict (adapter-computed).
    bool text_input_focused = false;
    // Tool state facts (adapter read of the active tool).
    std::string active_tool_id;      // "" = none
    bool active_tool_has_points = false;  // digitizing gesture live
    bool pan_restore_pending = false;     // _pan_restore_tool set
    // QC hub visibility + onion state for the Esc chain.
    bool qc_hub_visible = false;
    bool onion_active = false;
    // FSM mode value ("digitizing" etc.; mode_state.hpp parity).
    std::string mode_value;
};

enum class KeyIntent {
    Ignored,             // pass through to the normal handler chain
    BeginTemporaryPan,   // Space press: remember tool, activate "pan"
    ReleaseTemporaryPan, // Space release: restore remembered tool
    CycleSelection,      // Tab in digitize/adjust scope
    ZoomCenterIn,        // Z, no modifiers — ×1.5
    ZoomCenterOut,       // X, no modifiers — ÷1.5
    PickFaciesFromSelection,  // Ctrl+D
    EscapeCancelGesture, // Esc while tool.points non-empty
    EscapeEndOnion,      // Esc while onion active
    EscapeDeactivateTool,// Esc with an active non-pan tool
    EscapeCloseQcHub,    // Esc with QC hub visible
    EscapeDispatchFsm,   // Esc fallback — FSM ESC event only
    QcHubShown,          // qc_hub Show event → QC_HUB_ACTIVATED
    QcHubHidden,         // qc_hub Hide → QC_HUB_CLOSED
};

// The one interpretation pass (Python eventFilter parity). `consumed`
// says whether the event was eaten (return True from the filter).
struct KeyDecision {
    KeyIntent intent = KeyIntent::Ignored;
    bool consumed = false;
};

// Key press/release → intent. QC hub Show/Hide events go through
// qc_hub_visibility_intent() instead.
KeyDecision interpret_key(const KeyEventFacts& facts);

// QC hub visibility events (Python eventFilter's qc_hub branch).
KeyIntent qc_hub_visibility_intent(bool shown);

// Tab cycle scope: DIGITIZING / ADJUSTING_BOUNDARY only.
bool tab_cycle_scope_active(const std::string& mode_value);

// Esc chain decision (Python handle_escape order):
// gesture points → cancel gesture; onion → end epoch compare; active
// non-pan tool → deactivate; QC hub visible → close; else FSM ESC.
KeyIntent escape_chain_step(const KeyEventFacts& facts);

}  // namespace pwb::ui_workstation
