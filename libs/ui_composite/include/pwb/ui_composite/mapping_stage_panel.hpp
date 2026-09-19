#pragma once

// Port of paleo_workbench/ui/workstation/mapping_stage_panel.py (UI-13).
// Stage-context dock content (QStackedWidget, one page per stage; the
// central map NEVER switches). Each page holds:
//   * readiness checklist (clickable to locate, V5 §54);
//   * stage context actions (availability mirrored from the canonical
//     evaluator via ui_composite::evaluate_stage_commands, V11 §7);
//   * stage description footnote;
// plus the phase-2 typed-constraint creation row.
//
// The panel only emits request signals — workflow execution lives in the
// host wiring; the panel itself never touches QGIS/Catalog.

#include <map>
#include <string>
#include <utility>
#include <vector>

#include <pwb/tool_policy/stages.hpp>
#include <pwb/ui/stage_readiness.hpp>

#include <QFrame>
#include <QLabel>
#include <QListWidget>
#include <QStackedWidget>
#include <QWidget>

class QVBoxLayout;

namespace pwb::ui_composite {

// Availability verdict map: action_id -> (enabled, reason|"").
using ActionAvailability = std::map<std::string, std::pair<bool, std::string>>;

// 就绪度清单：status glyph + 标题；点击发定位请求。
class StageReadinessList : public QListWidget {
    Q_OBJECT
public:
    explicit StageReadinessList(QWidget* parent = nullptr);

    QSize minimumSizeHint() const override;
    void show_readiness(const pwb::ui::StageReadiness* readiness);

signals:
    void item_located(const QString& target);
};

// 阶段动作清单：一行一个动作；set_action_availability 按 canonical 判词
// 灰化/禁用（禁用行保持可见 + 「不可用：{reason}」tooltip）。
class StageCommandList : public QListWidget {
    Q_OBJECT
public:
    StageCommandList(
        const std::vector<std::pair<std::string, std::string>>& commands,
        QWidget* parent = nullptr);

    void set_action_availability(const ActionAvailability& availability);
    QSize sizeHint() const override;
    QSize minimumSizeHint() const override;

signals:
    void action_requested(const QString& action_id);
};

// 单阶段页：就绪度 + 上下文动作 + 说明脚注。
class StagePage : public QFrame {
    Q_OBJECT
public:
    StagePage(pwb::tool_policy::MappingStage stage,
              const std::vector<std::pair<std::string, std::string>>& actions,
              QWidget* parent = nullptr);

    const pwb::tool_policy::MappingStage stage;

    void show_readiness(const pwb::ui::StageReadiness* readiness);
    void set_action_availability(const ActionAvailability& availability);

    QLabel* readiness_status = nullptr;
    StageReadinessList* readiness = nullptr;
    StageCommandList* actions = nullptr;  // nullptr when no actions

signals:
    void action_requested(const QString& action_id);
    void locate_requested(const QString& target);
};

class MappingStagePanel : public QWidget {
    Q_OBJECT
public:
    explicit MappingStagePanel(QWidget* parent = nullptr);

    // -- 状态驱动 --------------------------------------------------------------
    void set_stage(const std::string& stage_value);
    // stage_value 缺省 = 当前页。宿主经 evaluate_stage_commands 供给判词；
    // 面板自身不判定（单一动作权威）。
    void set_action_availability(const ActionAvailability& availability,
                                 const std::string& stage_value = "");
    void show_readiness(pwb::tool_policy::MappingStage stage,
                        const pwb::ui::StageReadiness* readiness);

    QStackedWidget* stack = nullptr;

signals:
    void action_requested(const QString& stage_value,
                          const QString& action_id);
    void locate_requested(const QString& stage_value,
                          const QString& target);
    void stage_switch_requested(const QString& stage_value);
    void constraint_requested(const QString& constraint_kind_value);

private:
    void build_constraints_row(QVBoxLayout* layout);
    void update_constraints_visibility(pwb::tool_policy::MappingStage stage);

    std::map<pwb::tool_policy::MappingStage, StagePage*> pages_;
    QWidget* constraints_row_ = nullptr;
};

}  // namespace pwb::ui_composite
