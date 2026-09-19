#pragma once

// Qt signal shell over ModeStateMachine (UI-12). mode_changed fires
// only on real transitions; consumers are read-only observers (the
// M5-ECHO loop contract — they must not dispatch back).

#include <QObject>

#include <pwb/ui_workstation/mode_state.hpp>

namespace pwb::ui_workstation {

class ModeStateMachineQt : public QObject {
    Q_OBJECT
public:
    explicit ModeStateMachineQt(QObject* parent = nullptr)
        : QObject(parent) {
        machine_.on_mode_changed = [this](WorkstationMode mode) {
            emit mode_changed(mode);
        };
    }

    ModeStateMachine& machine() { return machine_; }
    const ModeStateMachine& machine() const { return machine_; }

    WorkstationMode mode() const { return machine_.mode(); }
    bool pan_held() const { return machine_.pan_held(); }

    void dispatch(ModeEvent event, const std::string& tool_id = "") {
        machine_.dispatch(event, tool_id);
    }
    void dispatch_tool_activated(const std::string& tool_id) {
        machine_.dispatch_tool_activated(tool_id);
    }
    const char* hint_text() const { return machine_.hint_text(); }

signals:
    void mode_changed(pwb::ui_workstation::WorkstationMode mode);

private:
    ModeStateMachine machine_;
};

}  // namespace pwb::ui_workstation
