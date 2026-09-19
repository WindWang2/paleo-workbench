#pragma once

// Qt shell over agent_plan (UI-12) — port of
// paleo_workbench/ui/workstation/agent_panel.py's widget layer.
// Risk-aware submission: plan → risk labels → WRITE gating (env opt-in
// / session grants / per-plan confirm dialog or injected hook) →
// injected executor. The panel owns NO action authority — the plan
// resolver, risk resolver, and executor are all injected seams.
// Late completions must not crash a destroyed UI (all callbacks are
// member-bound and Qt-disconnected on destruction).

#include <functional>
#include <optional>
#include <set>

#include <QFrame>
#include <QLabel>
#include <QLineEdit>
#include <QPlainTextEdit>
#include <QPushButton>

#include <pwb/ui_workstation/agent_plan.hpp>

namespace pwb::ui_workstation {

class AgentWorkspacePanel : public QFrame {
    Q_OBJECT
public:
    explicit AgentWorkspacePanel(QWidget* parent = nullptr);

    // --- injected seams ------------------------------------------------
    // Text → plan (None → the plan line is shown unreceived, honest).
    using PlanResolver =
        std::function<std::optional<AgentPlanSpec>(const QString&)>;
    // The plan executor (submits to the host scheduler).
    using PlanExecutor =
        std::function<void(const AgentPlanSpec& plan,
                           const std::set<AgentRisk>& permissions,
                           const QString& receipt_id)>;
    // Confirm-write hook: returns granted; one-shot grant (no session
    // memory — Python confirm_write parity). When unset, the built-in
    // grant dialog runs.
    using ConfirmWriteFn =
        std::function<bool(const std::vector<std::string>& action_ids)>;

    void set_plan_resolver(PlanResolver fn);
    void set_plan_executor(PlanExecutor fn);
    void set_risk_resolver(AgentRiskResolver fn);
    void set_confirm_write(ConfirmWriteFn fn);
    // allow_write_actions: tri-state — nullopt reads the env var
    // (PALEO_AGENT_ALLOW_WRITE); explicit value overrides (test seam).
    void set_allow_write_actions(std::optional<bool> allow);

    void set_context(const QString& workspace_name,
                     const QString& well_id = "");
    void submit(const QString& text);
    void submit_current();
    void cancel_current();

    // 会话内已授权的 WRITE 动作集合（精确集合；UIContext 只读）。
    const std::set<std::string>& write_granted_actions() const {
        return session_write_grants_;
    }

    QLineEdit* command_input() const { return command_input_; }
    QPlainTextEdit* history() const { return history_; }

signals:
    // V6 §4/§11：会话 WRITE 授权集合变化（UIContext write_granted 消费）。
    void write_grant_changed();
    // Host-visible lifecycle (plan accepted / rejected / unreceived).
    void plan_submitted(const QString& receipt_id);
    void plan_rejected(const QString& reason);
    void cancel_requested();

private:
    bool confirm_write_actions(
        const std::vector<std::string>& action_ids);
    void append_history(const QString& html);
    QString context_label() const;

    PlanResolver plan_resolver_;
    PlanExecutor plan_executor_;
    AgentRiskResolver risk_resolver_;
    ConfirmWriteFn confirm_write_;
    std::optional<bool> allow_write_override_;
    std::set<std::string> session_write_grants_;
    QString workspace_name_;
    QString well_id_;
    int receipt_counter_ = 0;

    QPlainTextEdit* history_ = nullptr;
    QLineEdit* command_input_ = nullptr;
    QLabel* context_label_ = nullptr;
    QLabel* consent_label_ = nullptr;
    QPushButton* send_button_ = nullptr;
    QPushButton* cancel_button_ = nullptr;
};

}  // namespace pwb::ui_workstation
