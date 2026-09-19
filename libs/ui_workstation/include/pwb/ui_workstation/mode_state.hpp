#pragma once

// Port of paleo_workbench/ui/workstation/mode_state.py (UI-12).
// Workstation mode state machine (M5, 02-state-machine-design.md).
//
// Projection layer only (00-decisions D12): observes existing signals
// (tool activation / epoch commit / QC panel show-hide / transient pan)
// and broadcasts mode_changed for read-only consumers (hint bar,
// shortcut-domain checks); it owns no tool/canvas state — removing this
// layer changes no system behavior. Loop contract: consumers must not
// dispatch events back into the FSM (M5-ECHO test pins this).
//
// Qt-free core; the QObject shell is ModeStateMachineQt
// (mode_state_qt.hpp).

#include <functional>
#include <string>

namespace pwb::ui_workstation {

enum class WorkstationMode {
    Idle,
    Digitizing,
    AdjustingBoundary,
    InspectingQc,
    TimeTravelling,
};

// Python WorkstationMode.value strings.
const char* workstation_mode_value(WorkstationMode mode);

enum class ModeEvent {
    ToolActivated,
    ToolDeactivated,
    Esc,
    VertexAct,
    QcHubActivated,
    QcHubClosed,
    ScrubStart,
    EpochCommit,
    OnionToggled,
    PanHeld,
    PanReleased,
};

// Vertex/reshape-class tools: TOOL_ACTIVATED enters ADJUSTING_BOUNDARY
// directly (Python ADJUSTING_TOOLS frozenset).
bool is_adjusting_tool(const std::string& tool_id);

// Per-mode hint-bar text (S5-2 lookup table; signal-driven, not polled).
const char* mode_hint(WorkstationMode mode);

class ModeStateMachine {
public:
    // Single change listener (Python mode_changed parity). Fired only on
    // real transitions — self-loops/rejected events emit nothing.
    std::function<void(WorkstationMode)> on_mode_changed;

    WorkstationMode mode() const { return mode_; }
    // Transient flag above the mode; never alters it.
    bool pan_held() const { return pan_held_; }

    // Deterministic transition (see the 02 table). Unknown/None events do
    // not throw (D12). `tool_id` matters only for ToolActivated.
    void dispatch(ModeEvent event, const std::string& tool_id = "");

    // Convenience injection (host wiring parity).
    void dispatch_tool_activated(const std::string& tool_id) {
        dispatch(ModeEvent::ToolActivated, tool_id);
    }

    const char* hint_text() const { return mode_hint(mode_); }

    // Test injection seam (Python tests write _mode/_mode_before_travel
    // directly for the full-matrix audit).
    void inject_mode_for_test(WorkstationMode mode,
                              WorkstationMode before_travel) {
        mode_ = mode;
        mode_before_travel_ = before_travel;
    }

private:
    WorkstationMode mode_ = WorkstationMode::Idle;
    WorkstationMode mode_before_travel_ = WorkstationMode::Idle;
    bool pan_held_ = false;
};

}  // namespace pwb::ui_workstation
