#include "pwb/ui_workstation/workflow_panel.hpp"

#include <QCheckBox>
#include <QLabel>
#include <QSizePolicy>
#include <QToolButton>
#include <QVBoxLayout>

namespace pwb::ui_workstation {

WorkflowPanel::WorkflowPanel(QWidget* parent) : QFrame(parent) {
    setObjectName(QStringLiteral("WorkstationWorkflowPanel"));
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(0);

    title_ = new QLabel(this);
    title_->setObjectName(QStringLiteral("WorkstationPanelTitle"));
    title_->setContentsMargins(8, 6, 8, 4);
    layout->addWidget(title_);

    body_ = new QWidget(this);
    body_layout_ = new QVBoxLayout(body_);
    body_layout_->setContentsMargins(4, 0, 4, 4);
    body_layout_->setSpacing(1);
    layout->addWidget(body_, 1);
}

void WorkflowPanel::reset_body() {
    while (auto* item = body_layout_->takeAt(0)) {
        if (item->widget() != nullptr) {
            // deleteLater 前必须隐藏 —— takeAt 只移出布局，部件仍按旧
            // 几何位置绘制到事件循环真正销毁为止（工作区切换时旧步骤
            // 行会叠印在新内容上）。
            item->widget()->hide();
            item->widget()->deleteLater();
        }
        delete item;
    }
    delete step_group_;
    step_group_ = nullptr;
    checks_.clear();
}

void WorkflowPanel::set_steps(const QString& title,
                              const QStringList& steps) {
    reset_body();
    title_->setText(title);
    step_group_ = new QButtonGroup(this);
    step_group_->setExclusive(true);
    for (int i = 0; i < steps.size(); ++i) {
        auto* button = new QToolButton(body_);
        button->setObjectName(QStringLiteral("WorkflowStepButton"));
        button->setCheckable(true);
        button->setAutoRaise(true);
        button->setToolButtonStyle(Qt::ToolButtonTextBesideIcon);
        button->setText(QStringLiteral("%1  %2").arg(i + 1).arg(steps[i]));
        button->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Fixed);
        connect(button, &QToolButton::clicked, this,
                [this, i]() { emit step_activated(i); });
        step_group_->addButton(button, i);
        body_layout_->addWidget(button);
    }
    body_layout_->addStretch(1);
    body_->setVisible(!steps.isEmpty());
}

void WorkflowPanel::set_checks(const QString& title,
                               const QStringList& checks, bool checked) {
    reset_body();
    title_->setText(title);
    for (int i = 0; i < checks.size(); ++i) {
        auto* box = new QCheckBox(checks[i], body_);
        box->setObjectName(QStringLiteral("WorkflowCheckItem"));
        box->setChecked(checked);
        connect(box, &QCheckBox::toggled, this,
                [this, i](bool on) { emit check_toggled(i, on); });
        checks_.push_back(box);
        body_layout_->addWidget(box);
    }
    body_layout_->addStretch(1);
    body_->setVisible(!checks.isEmpty());
}

void WorkflowPanel::set_current_step(int index) {
    if (step_group_ == nullptr) return;
    if (auto* button = step_group_->button(index)) {
        button->setChecked(true);
    }
}

int WorkflowPanel::current_step() const {
    return step_group_ != nullptr ? step_group_->checkedId() : -1;
}

}  // namespace pwb::ui_workstation
