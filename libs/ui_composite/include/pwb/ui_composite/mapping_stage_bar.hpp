#pragma once

// Port of paleo_workbench/ui/workstation/mapping_stage_bar.py (UI-13).
// Compact stage-switch segmented bar near the AppBar: ordinal dot +
// short name + status badge per stage; the 层位 combo writes
// project.stratigraphy.target_horizon (not editable). Switching is
// instantaneous (group-visibility delta), never reloads the project.

#include <map>
#include <set>
#include <string>
#include <vector>

#include <pwb/tool_policy/stages.hpp>

#include <QComboBox>
#include <QFrame>
#include <QLabel>

namespace pwb::ui_composite {

// 单个阶段：序号圆点 + 短名 + 状态徽标。
class StageSegment : public QFrame {
    Q_OBJECT
public:
    explicit StageSegment(pwb::tool_policy::MappingStage stage,
                          QWidget* parent = nullptr);

    const pwb::tool_policy::MappingStage stage;
    QString text() const;
    bool isChecked() const { return active_; }
    void click() { emit clicked(); }
    void set_active(bool active);
    void set_badge(const QString& badge);

signals:
    void clicked();

protected:
    void mouseReleaseEvent(QMouseEvent* event) override;
    void keyPressEvent(QKeyEvent* event) override;

private:
    void refresh();

    bool active_ = false;
    QString badge_;
    QLabel* index_ = nullptr;
    QLabel* name_ = nullptr;
    QLabel* badge_label_ = nullptr;
};

class MappingStageBar : public QFrame {
    Q_OBJECT
public:
    explicit MappingStageBar(QWidget* parent = nullptr);

    // -- 状态同步（由宿主/MappingStageController 驱动） --------------------------
    void set_current_stage(const std::string& stage_value);
    void set_stage_badge(pwb::tool_policy::MappingStage stage,
                         const QString& badge);
    // 批量更新徽标（key = stage.value）。
    void refresh_badges(const std::map<std::string, QString>& badges);

    QString current_horizon() const;
    // 同步工程层位到选择框（不发 horizon_requested）。
    void set_horizon_state(const QString& horizon,
                           const std::vector<QString>& options = {});

    // V9 viewport 策略：紧凑视口隐藏「层位」前缀标签。
    void set_horizon_label_visible(bool visible) {
        horizon_label->setVisible(visible);
    }

    QLabel* horizon_label = nullptr;
    QComboBox* horizon_combo = nullptr;

signals:
    void stage_requested(const QString& stage_value);
    void horizon_requested(const QString& horizon);

private:
    void commit_horizon();

    std::map<pwb::tool_policy::MappingStage, StageSegment*> buttons_;
    std::vector<QFrame*> tracks_;
    bool suppress_horizon_ = false;
    QString last_committed_horizon_;
};

}  // namespace pwb::ui_composite
