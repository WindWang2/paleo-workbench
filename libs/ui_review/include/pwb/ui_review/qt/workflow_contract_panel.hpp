#pragma once

// UI-11 — workflow_contract_panel.py Qt shell: compact Chinese contract
// card (功能/输入/操作/输出/上下游/QC/就绪/待专家确认 + 开发/咨询详情
// toggle). Line spec comes from the Qt-free contract_panel_lines core;
// the panel only paints it.

#include "pwb/ui_review/contract_lines.hpp"

#include <QFrame>

#include <functional>
#include <optional>
#include <string>
#include <vector>

class QLabel;
class QPushButton;
class QScrollArea;
class QVBoxLayout;
class QWidget;

namespace pwb::ui_review::qt {

// project → readiness report seam (evaluate_readiness); returns nullptr
// when no project is bound (→ "当前状态：未绑定工程" line).
using ReadinessFn =
    std::function<std::optional<workflow_contracts::ReadinessReport>(
        const std::string& contract_id)>;

class WorkflowContractPanel : public QFrame {
    Q_OBJECT
public:
    explicit WorkflowContractPanel(
        QWidget* parent = nullptr,
        const workflow_contracts::WorkflowContractRegistry* registry =
            nullptr);

    // set_contract_id / set_project parity: re-render on each change.
    // readiness_fn == nullptr → the unbound-project branch.
    void set_contract_id(const QString& contract_id);
    void set_readiness_fn(ReadinessFn readiness_fn);

    QLabel* title() const { return title_; }
    QPushButton* dev_btn() const { return dev_btn_; }
    const std::vector<QLabel*>& lines() const { return lines_; }

private:
    void clear_lines();
    void add_line(const ContractLine& line);
    void refresh();

    const workflow_contracts::WorkflowContractRegistry* registry_;
    ReadinessFn readiness_fn_;
    std::string contract_id_ = "factor_interpolation";
    bool dev_mode_ = false;
    std::vector<QLabel*> lines_;

    QLabel* title_ = nullptr;
    QPushButton* dev_btn_ = nullptr;
    QScrollArea* scroll_ = nullptr;
    QWidget* body_ = nullptr;
    QVBoxLayout* body_layout_ = nullptr;
};

}  // namespace pwb::ui_review::qt
