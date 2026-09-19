#include "pwb/ui_workstation/keybinding_manager.hpp"

#include <QKeyEvent>

namespace pwb::ui_workstation {

KeybindingHintBar::KeybindingHintBar(QWidget* parent) : QLabel(parent) {
    setObjectName("KeybindingHintBar");
    setAlignment(Qt::AlignmentFlag::AlignCenter);
    setToolTip("编图快捷键随当前模式变化");
}

void KeybindingHintBar::apply_mode(WorkstationMode mode) {
    setText(mode_hint(mode));
}

// ---------------------------------------------------------------------

WorkstationKeyBindingManager::WorkstationKeyBindingManager(
    QObject* parent)
    : QObject(parent) {}

void WorkstationKeyBindingManager::set_hooks(Hooks hooks) {
    hooks_ = std::move(hooks);
}

void WorkstationKeyBindingManager::install_on(QObject* composite,
                                              QObject* canvas,
                                              QObject* qc_hub) {
    if (composite != nullptr) composite->installEventFilter(this);
    if (canvas != nullptr) canvas->installEventFilter(this);
    qc_hub_ = qc_hub;
    if (qc_hub_ != nullptr) qc_hub_->installEventFilter(this);
}

void WorkstationKeyBindingManager::on_tool_state_changed() {
    // 临时平移中的工具切换不是用户模式事件（防模式闪烁）。
    if (pan_restore_tool_.has_value()) return;
    const std::string tool_id =
        hooks_.active_tool_id ? hooks_.active_tool_id() : "";
    if (!tool_id.empty() && tool_id != "pan") {
        if (tool_id != last_tool_id_.value_or("")) {
            last_tool_id_ = tool_id;
            if (hooks_.dispatch_fsm_tool) {
                hooks_.dispatch_fsm_tool(ModeEvent::ToolActivated,
                                         tool_id);
            } else if (hooks_.dispatch_fsm) {
                hooks_.dispatch_fsm(ModeEvent::ToolActivated);
            }
        }
    } else if (last_tool_id_.has_value()) {
        last_tool_id_.reset();
        if (hooks_.dispatch_fsm) {
            hooks_.dispatch_fsm(ModeEvent::ToolDeactivated);
        }
    }
}

KeyEventFacts WorkstationKeyBindingManager::collect_facts(
    KeyCode key, KeyEventType type, bool ctrl, bool shift,
    bool alt) const {
    KeyEventFacts f;
    f.key = key;
    f.type = type;
    f.control = ctrl;
    f.shift = shift;
    f.alt = alt;
    f.text_input_focused =
        hooks_.text_input_focused && hooks_.text_input_focused();
    f.active_tool_id =
        hooks_.active_tool_id ? hooks_.active_tool_id() : "";
    f.active_tool_has_points =
        hooks_.active_tool_has_points && hooks_.active_tool_has_points();
    f.pan_restore_pending = pan_restore_tool_.has_value();
    f.qc_hub_visible =
        hooks_.qc_hub_visible && hooks_.qc_hub_visible();
    f.onion_active = hooks_.onion_active && hooks_.onion_active();
    f.mode_value = hooks_.mode_value ? hooks_.mode_value() : "";
    return f;
}

namespace {

KeyCode key_code_for(int qt_key) {
    switch (qt_key) {
    case Qt::Key_Space:  return KeyCode::Space;
    case Qt::Key_Tab:   return KeyCode::Tab;
    case Qt::Key_Z:     return KeyCode::KeyZ;
    case Qt::Key_X:     return KeyCode::KeyX;
    case Qt::Key_D:     return KeyCode::KeyD;
    case Qt::Key_Escape: return KeyCode::Escape;
    default:            return KeyCode::Other;
    }
}

}  // namespace

bool WorkstationKeyBindingManager::eventFilter(QObject* obj,
                                               QEvent* event) {
    // QC hub Show/Hide → FSM events (never consumed).
    if (obj != nullptr && obj == qc_hub_) {
        if (event->type() == QEvent::Type::Show) {
            if (hooks_.dispatch_fsm) {
                hooks_.dispatch_fsm(ModeEvent::QcHubActivated);
            }
        } else if (event->type() == QEvent::Type::Hide) {
            if (hooks_.dispatch_fsm) {
                hooks_.dispatch_fsm(ModeEvent::QcHubClosed);
            }
        }
        return false;
    }
    if (event->type() == QEvent::Type::KeyPress ||
        event->type() == QEvent::Type::KeyRelease) {
        auto* key_event = static_cast<QKeyEvent*>(event);
        if (key_event->isAutoRepeat() &&
            key_event->key() != Qt::Key_Space) {
            return false;
        }
        // D9：动画平移期间的任何用户按键先打断动画（幂等）。
        if (event->type() == QEvent::Type::KeyPress &&
            hooks_.cancel_smooth_pan) {
            hooks_.cancel_smooth_pan();
        }
        const auto mods = key_event->modifiers();
        const KeyEventFacts facts = collect_facts(
            key_code_for(key_event->key()),
            event->type() == QEvent::Type::KeyPress
                ? KeyEventType::Press
                : KeyEventType::Release,
            mods.testFlag(Qt::KeyboardModifier::ControlModifier),
            mods.testFlag(Qt::KeyboardModifier::ShiftModifier),
            mods.testFlag(Qt::KeyboardModifier::AltModifier));
        const KeyDecision decision = interpret_key(facts);
        if (decision.consumed) {
            run_intent(decision.intent);
        }
        return decision.consumed;
    }
    return false;
}

void WorkstationKeyBindingManager::run_intent(KeyIntent intent) {
    switch (intent) {
    case KeyIntent::BeginTemporaryPan:
        begin_temporary_pan();
        break;
    case KeyIntent::ReleaseTemporaryPan:
        release_temporary_pan();
        break;
    case KeyIntent::CycleSelection:
        if (hooks_.cycle_selection) hooks_.cycle_selection();
        break;
    case KeyIntent::ZoomCenterIn:
        if (hooks_.zoom_by) hooks_.zoom_by(kKeybindingZoomStep);
        break;
    case KeyIntent::ZoomCenterOut:
        if (hooks_.zoom_by) hooks_.zoom_by(1.0 / kKeybindingZoomStep);
        break;
    case KeyIntent::PickFaciesFromSelection:
        if (hooks_.pick_facies) hooks_.pick_facies();
        break;
    case KeyIntent::EscapeCancelGesture:
        if (hooks_.cancel_active_tool) hooks_.cancel_active_tool();
        break;
    case KeyIntent::EscapeEndOnion:
        if (hooks_.end_onion) hooks_.end_onion();
        if (hooks_.dispatch_fsm) hooks_.dispatch_fsm(ModeEvent::Esc);
        break;
    case KeyIntent::EscapeDeactivateTool:
        if (hooks_.activate_tool) hooks_.activate_tool("pan");
        if (hooks_.dispatch_fsm) hooks_.dispatch_fsm(ModeEvent::Esc);
        break;
    case KeyIntent::EscapeCloseQcHub:
        if (hooks_.close_qc_hub) hooks_.close_qc_hub();
        if (hooks_.dispatch_fsm) hooks_.dispatch_fsm(ModeEvent::Esc);
        break;
    case KeyIntent::EscapeDispatchFsm:
        if (hooks_.dispatch_fsm) hooks_.dispatch_fsm(ModeEvent::Esc);
        break;
    default:
        break;
    }
}

void WorkstationKeyBindingManager::begin_temporary_pan() {
    const std::string tool_id =
        hooks_.active_tool_id ? hooks_.active_tool_id() : "";
    if (tool_id.empty() || tool_id == "pan") return;
    pan_restore_tool_ = tool_id;
    if (hooks_.dispatch_fsm) hooks_.dispatch_fsm(ModeEvent::PanHeld);
    if (hooks_.activate_tool) hooks_.activate_tool("pan");
}

void WorkstationKeyBindingManager::release_temporary_pan() {
    const auto restore = pan_restore_tool_;
    pan_restore_tool_.reset();
    if (hooks_.dispatch_fsm) hooks_.dispatch_fsm(ModeEvent::PanReleased);
    if (restore.has_value() && hooks_.activate_tool) {
        hooks_.activate_tool(*restore);
    }
}

void WorkstationKeyBindingManager::handle_escape() {
    const KeyEventFacts facts =
        collect_facts(KeyCode::Escape, KeyEventType::Press,
                      false, false, false);
    run_intent(escape_chain_step(facts));
}

}  // namespace pwb::ui_workstation
