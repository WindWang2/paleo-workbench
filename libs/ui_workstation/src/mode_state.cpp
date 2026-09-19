#include "pwb/ui_workstation/mode_state.hpp"

#include <unordered_set>

namespace pwb::ui_workstation {

const char* workstation_mode_value(WorkstationMode mode) {
    switch (mode) {
        case WorkstationMode::Idle: return "IDLE";
        case WorkstationMode::Digitizing: return "DIGITIZING";
        case WorkstationMode::AdjustingBoundary: return "ADJUSTING_BOUNDARY";
        case WorkstationMode::InspectingQc: return "INSPECTING_QC";
        case WorkstationMode::TimeTravelling: return "TIME_TRAVELLING";
    }
    return "IDLE";
}

bool is_adjusting_tool(const std::string& tool_id) {
    static const std::unordered_set<std::string> tools = {
        "vertex", "reshape", "move_feature",
    };
    return tools.count(tool_id) != 0;
}

const char* mode_hint(WorkstationMode mode) {
    switch (mode) {
        case WorkstationMode::Idle:
            return "浏览：Space 平移 · Z/X 缩放 · Tab 循环要素 · Ctrl+D 吸属性";
        case WorkstationMode::Digitizing:
            return "数字化中：Space 平移 · Tab 下一要素 · Ctrl+D 吸属性 · Esc 取消";
        case WorkstationMode::AdjustingBoundary:
            return "边界调整：Tab 下一要素 · Z/X 缩放 · Esc 退出";
        case WorkstationMode::InspectingQc:
            return "质检向导：↑↓ 选择 · Enter 定位 · F 修复 · Esc 关闭";
        case WorkstationMode::TimeTravelling:
            return "期次对比：←→ 步进 · 洋葱皮 · Esc 返回编图";
    }
    return mode_hint(WorkstationMode::Idle);
}

void ModeStateMachine::dispatch(ModeEvent event,
                                const std::string& tool_id) {
    if (event == ModeEvent::PanHeld) {
        pan_held_ = true;
        return;
    }
    if (event == ModeEvent::PanReleased) {
        pan_held_ = false;
        return;
    }
    if (event == ModeEvent::OnionToggled) {
        return;  // self-loop: onion skin never changes state
    }

    const WorkstationMode current = mode_;
    WorkstationMode target = current;
    switch (event) {
        case ModeEvent::ToolActivated:
            if (current == WorkstationMode::TimeTravelling) {
                return;  // rejected: Esc ends time-travel first (02 table †)
            }
            target = is_adjusting_tool(tool_id)
                         ? WorkstationMode::AdjustingBoundary
                         : WorkstationMode::Digitizing;
            break;
        case ModeEvent::VertexAct:
            if (current == WorkstationMode::TimeTravelling) {
                return;
            }
            target = WorkstationMode::AdjustingBoundary;
            break;
        case ModeEvent::ToolDeactivated:
        case ModeEvent::Esc:
            target = WorkstationMode::Idle;
            break;
        case ModeEvent::QcHubActivated:
            target = WorkstationMode::InspectingQc;
            break;
        case ModeEvent::QcHubClosed:
            target = (current == WorkstationMode::InspectingQc)
                         ? WorkstationMode::Idle
                         : current;
            break;
        case ModeEvent::ScrubStart:
            if (current != WorkstationMode::TimeTravelling) {
                mode_before_travel_ = current;
            }
            target = WorkstationMode::TimeTravelling;
            break;
        case ModeEvent::EpochCommit:
            target = (current == WorkstationMode::TimeTravelling)
                         ? mode_before_travel_
                         : current;
            break;
        default:
            target = current;  // unknown event: no throw (D12)
            break;
    }
    if (target != current) {
        mode_ = target;
        if (on_mode_changed) {
            on_mode_changed(target);
        }
    }
}

}  // namespace pwb::ui_workstation
