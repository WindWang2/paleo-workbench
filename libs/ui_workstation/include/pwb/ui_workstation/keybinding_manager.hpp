#pragma once

// Qt event-filter shell over keybinding_intent (UI-12) — port of
// paleo_workbench/ui/workstation/keybinding_manager.py:
// composite/canvas/qc_hub 三挂键过滤器 + Esc 退出链 + FSM 事件桥。
// Every fact it needs (focused text input, active tool, gesture
// points, onion state, QC hub visibility, FSM mode) is an injected
// probe; every action (activate tool, cancel gesture, zoom, pick
// facies, cycle selection, dispatch FSM event) is an injected hook —
// the filter owns no state beyond the pan-restore tool id.

#include <functional>
#include <optional>
#include <string>

#include <QEvent>
#include <QLabel>
#include <QObject>

#include <pwb/ui_workstation/keybinding_intent.hpp>
#include <pwb/ui_workstation/mode_state.hpp>

namespace pwb::ui_workstation {

// The mode hint bar (Python KeybindingHintBar).
class KeybindingHintBar : public QLabel {
    Q_OBJECT
public:
    explicit KeybindingHintBar(QWidget* parent = nullptr);
    void apply_mode(WorkstationMode mode);
};

class WorkstationKeyBindingManager : public QObject {
    Q_OBJECT
public:
    // All probes/hooks are plain std::functions — the host binds the
    // composite's real seams.
    struct Hooks {
        std::function<bool()> text_input_focused;   // required
        std::function<std::string()> active_tool_id;
        std::function<bool()> active_tool_has_points;
        std::function<bool()> qc_hub_visible;
        std::function<bool()> onion_active;
        std::function<std::string()> mode_value;
        std::function<void()> cancel_smooth_pan;      // D9
        std::function<void(const std::string&)> activate_tool;
        std::function<void()> cancel_active_tool;
        std::function<void(double)> zoom_by;
        std::function<void()> cycle_selection;
        std::function<void()> pick_facies;
        std::function<void()> end_onion;              // onion off + epoch
        std::function<void()> close_qc_hub;
        std::function<void(ModeEvent)> dispatch_fsm;
        std::function<void(ModeEvent, const std::string&)>
            dispatch_fsm_tool;
    };

    explicit WorkstationKeyBindingManager(QObject* parent = nullptr);
    void set_hooks(Hooks hooks);

    // composite/canvas/qc_hub 三挂 (Python install()).
    void install_on(QObject* composite, QObject* canvas = nullptr,
                    QObject* qc_hub = nullptr);

    // Tool-state → FSM bridge (Python _on_tool_state_changed):
    // call when the active tool changed; suppressed while a temporary
    // pan holds (mode flicker guard).
    void on_tool_state_changed();

    bool eventFilter(QObject* obj, QEvent* event) override;

    // Direct action entries (Python public methods).
    void begin_temporary_pan();
    void release_temporary_pan();
    void handle_escape();

    const std::optional<std::string>& pan_restore_tool() const {
        return pan_restore_tool_;
    }

private:
    KeyEventFacts collect_facts(KeyCode key, KeyEventType type,
                                bool ctrl, bool shift, bool alt) const;
    void run_intent(KeyIntent intent);

    Hooks hooks_;
    std::optional<std::string> pan_restore_tool_;
    std::optional<std::string> last_tool_id_;
    QObject* qc_hub_ = nullptr;
};

}  // namespace pwb::ui_workstation
