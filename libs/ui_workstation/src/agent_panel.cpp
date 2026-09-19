#include "pwb/ui_workstation/agent_panel.hpp"

#include <QCheckBox>
#include <QDialog>
#include <QDialogButtonBox>
#include <QHBoxLayout>
#include <QLabel>
#include <QScrollArea>
#include <QVBoxLayout>

namespace pwb::ui_workstation {

AgentWorkspacePanel::AgentWorkspacePanel(QWidget* parent)
    : QFrame(parent) {
    setObjectName("WorkstationAgentPanel");
    setMinimumHeight(140);

    auto* outer = new QVBoxLayout(this);
    outer->setContentsMargins(8, 8, 8, 8);
    outer->setSpacing(6);

    context_label_ = new QLabel(this);
    context_label_->setObjectName("WorkstationAgentContext");
    outer->addWidget(context_label_);

    consent_label_ = new QLabel(this);
    consent_label_->setObjectName("WorkstationAgentConsent");
    consent_label_->setWordWrap(true);
    outer->addWidget(consent_label_);

    history_ = new QPlainTextEdit(this);
    history_->setObjectName("WorkstationAgentHistory");
    history_->setReadOnly(true);
    outer->addWidget(history_, 1);

    auto* row = new QHBoxLayout();
    command_input_ = new QLineEdit(this);
    command_input_->setObjectName("WorkstationAgentInput");
    command_input_->setPlaceholderText(
        "描述要执行的受控动作（默认只读/计算权限）…");
    connect(command_input_, &QLineEdit::returnPressed, this,
            &AgentWorkspacePanel::submit_current);
    row->addWidget(command_input_, 1);
    send_button_ = new QPushButton("执行", this);
    connect(send_button_, &QPushButton::clicked, this,
            &AgentWorkspacePanel::submit_current);
    row->addWidget(send_button_);
    cancel_button_ = new QPushButton("取消", this);
    cancel_button_->setObjectName("SecondaryButton");
    connect(cancel_button_, &QPushButton::clicked, this,
            &AgentWorkspacePanel::cancel_current);
    row->addWidget(cancel_button_);
    outer->addLayout(row);

    set_context("", "");
}

void AgentWorkspacePanel::set_plan_resolver(PlanResolver fn) {
    plan_resolver_ = std::move(fn);
}

void AgentWorkspacePanel::set_plan_executor(PlanExecutor fn) {
    plan_executor_ = std::move(fn);
}

void AgentWorkspacePanel::set_risk_resolver(AgentRiskResolver fn) {
    risk_resolver_ = std::move(fn);
}

void AgentWorkspacePanel::set_confirm_write(ConfirmWriteFn fn) {
    confirm_write_ = std::move(fn);
}

void AgentWorkspacePanel::set_allow_write_actions(
    std::optional<bool> allow) {
    allow_write_override_ = allow;
    const bool allowed =
        allow_write_override_.value_or(env_allows_write_actions());
    consent_label_->setText(
        QString::fromStdString(agent_consent_text(allowed)));
}

void AgentWorkspacePanel::set_context(const QString& workspace_name,
                                      const QString& well_id) {
    workspace_name_ = workspace_name;
    well_id_ = well_id;
    context_label_->setText(context_label());
    consent_label_->setText(QString::fromStdString(
        agent_consent_text(
            allow_write_override_.value_or(env_allows_write_actions()))));
}

QString AgentWorkspacePanel::context_label() const {
    QStringList parts;
    parts << (workspace_name_.isEmpty() ? "工程：未打开"
                                       : "工程：" + workspace_name_);
    if (!well_id_.isEmpty()) parts << "井：" + well_id_;
    return parts.join(" · ");
}

void AgentWorkspacePanel::append_history(const QString& html) {
    history_->appendHtml(html);
}

void AgentWorkspacePanel::submit(const QString& text) {
    const QString trimmed = text.trimmed();
    if (trimmed.isEmpty()) return;
    const QString receipt_id =
        QString("A-%1").arg(++receipt_counter_, 4, 10, QChar('0'));
    append_history("<b>» " + trimmed.toHtmlEscaped() + "</b>");

    if (!plan_resolver_) {
        append_history("计划解析未接入 — 未执行（诚实提示）");
        emit plan_rejected("no-resolver");
        return;
    }
    const auto plan = plan_resolver_(trimmed);
    if (!plan.has_value()) {
        append_history("无法解析为受控动作 — 未执行");
        emit plan_rejected("unparsed");
        return;
    }
    const std::string risks = [&] {
        std::string out;
        for (const AgentRisk r : agent_plan_risks(*plan, risk_resolver_)) {
            if (!out.empty()) out += "、";
            out += agent_risk_labels().at(r);
        }
        return out;
    }();
    append_history(QString::fromStdString(
        "计划 " + plan->action_id + " · [" + risks + "]"));
    const auto write_actions =
        agent_plan_write_actions(*plan, risk_resolver_);
    if (!write_actions.empty() &&
        !confirm_write_actions(write_actions)) {
        append_history("WRITE 授权被拒 — 未执行");
        emit plan_rejected("write-denied");
        return;
    }
    const bool write_ok =
        !write_actions.empty() ||
        allow_write_override_.value_or(env_allows_write_actions());
    if (plan_executor_) {
        plan_executor_(*plan, agent_allowed_risks(write_ok), receipt_id);
    }
    emit plan_submitted(receipt_id);
}

void AgentWorkspacePanel::submit_current() {
    const QString text = command_input_->text().trimmed();
    if (text.isEmpty()) return;
    command_input_->clear();
    submit(text);
}

void AgentWorkspacePanel::cancel_current() {
    emit cancel_requested();
    append_history("<b>取消请求已发送</b> · 将在安全点停止。");
}

bool AgentWorkspacePanel::confirm_write_actions(
    const std::vector<std::string>& action_ids) {
    // V6：会话授权命中（精确集合）→ 不再打扰。
    if (agent_write_granted_for(session_write_grants_, action_ids)) {
        return true;
    }
    if (confirm_write_) {
        // Injected hook exceptions deny (fail closed).
        try {
            if (confirm_write_(action_ids)) {
                // Hook grant is one-shot (no session memory).
                return true;
            }
        } catch (...) {
        }
        return false;
    }
    // Built-in WRITE grant dialog (V6 §11): action cards + scope +
    // session granularity; 拒绝 is the default button, 记住授权 is an
    // explicit unchecked box.
    QDialog dialog(this);
    dialog.setObjectName("WriteGrantDialog");
    dialog.setWindowTitle("写入授权");
    dialog.setModal(true);
    bool granted = false;
    auto* layout = new QVBoxLayout(&dialog);
    auto* intro = new QLabel(
        "以下 Agent 动作将执行写入（WRITE）——修改工程数据或写盘。"
        "逐项核对后授权；拒绝不会执行任何动作。",
        &dialog);
    intro->setWordWrap(true);
    layout->addWidget(intro);

    auto* cards = new QFrame(&dialog);
    cards->setObjectName("WriteGrantActionList");
    auto* cards_layout = new QVBoxLayout(cards);
    cards_layout->setContentsMargins(6, 6, 6, 6);
    for (const auto& id : action_ids) {
        auto* title = new QLabel(
            QString::fromStdString("▣ " + id), cards);
        title->setObjectName("WriteGrantActionTitle");
        cards_layout->addWidget(title);
        const bool known = risk_resolver_ && risk_resolver_(id);
        auto* detail = new QLabel(
            known ? QString::fromStdString(id)
                  : "（注册表中无此动作描述——按 WRITE 对待）",
            cards);
        detail->setWordWrap(true);
        cards_layout->addWidget(detail);
    }
    auto* scroll = new QScrollArea(&dialog);
    scroll->setWidget(cards);
    scroll->setWidgetResizable(true);
    layout->addWidget(scroll, 1);

    auto* remember = new QCheckBox(
        "本会话内记住该授权（同一动作集合不再询问）", &dialog);
    layout->addWidget(remember);

    auto* buttons = new QDialogButtonBox(
        QDialogButtonBox::StandardButton::Yes |
            QDialogButtonBox::StandardButton::No,
        &dialog);
    buttons->button(QDialogButtonBox::StandardButton::No)
        ->setText("拒绝");
    buttons->button(QDialogButtonBox::StandardButton::Yes)
        ->setText("授权");
    buttons->button(QDialogButtonBox::StandardButton::No)
        ->setDefault(true);
    buttons->button(QDialogButtonBox::StandardButton::No)->setFocus();
    connect(buttons, &QDialogButtonBox::accepted, &dialog,
            [&] { granted = true; dialog.accept(); });
    connect(buttons, &QDialogButtonBox::rejected, &dialog,
            &QDialog::reject);
    layout->addWidget(buttons);
    dialog.exec();
    if (!granted) return false;
    if (remember->isChecked()) {
        session_write_grants_.insert(action_ids.begin(),
                                     action_ids.end());
        emit write_grant_changed();
    }
    return true;
}

}  // namespace pwb::ui_workstation
