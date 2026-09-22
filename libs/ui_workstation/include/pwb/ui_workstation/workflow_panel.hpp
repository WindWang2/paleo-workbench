#pragma once

// 左栏下部工作流面板（qt_ribbon_native prototype parity）。两种形态：
//   * set_steps —— 编号步骤列表（「1 相团几何检查」式，单选高亮当前步）；
//   * set_checks —— 勾选清单（验证设置式）。
// 面板只做呈现与信号转发；步骤语义/勾选含义由宿主壳层决定。

#include <QStringList>

#include <QButtonGroup>
#include <QFrame>
#include <QVector>

class QCheckBox;
class QLabel;
class QToolButton;
class QVBoxLayout;

namespace pwb::ui_workstation {

class WorkflowPanel : public QFrame {
    Q_OBJECT
public:
    explicit WorkflowPanel(QWidget* parent = nullptr);

    // 编号步骤模式。空清单 = 隐藏正文（诚实缺席）。
    void set_steps(const QString& title, const QStringList& steps);
    // 勾选清单模式。
    void set_checks(const QString& title, const QStringList& checks,
                    bool checked = true);
    // 当前步高亮（set_steps 模式；-1 = 无高亮）。
    void set_current_step(int index);
    int current_step() const;

signals:
    void step_activated(int index);
    void check_toggled(int index, bool checked);

private:
    void reset_body();

    QLabel* title_ = nullptr;
    QWidget* body_ = nullptr;
    QVBoxLayout* body_layout_ = nullptr;
    QButtonGroup* step_group_ = nullptr;
    QVector<QCheckBox*> checks_;
};

}  // namespace pwb::ui_workstation
