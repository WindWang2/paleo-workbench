#include "pwb/ui_review/qt/workflow_contract_panel.hpp"

#include "pwb/ui_review/tokens.hpp"
#include "pwb/workflow_contracts/registry.hpp"

#include <QHBoxLayout>
#include <QLabel>
#include <QPushButton>
#include <QScrollArea>
#include <QVBoxLayout>

namespace pwb::ui_review::qt {

WorkflowContractPanel::WorkflowContractPanel(
    QWidget* parent,
    const workflow_contracts::WorkflowContractRegistry* registry)
    : QFrame(parent), registry_(registry) {
    setObjectName(QStringLiteral("WorkflowContractPanel"));
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(tokens::kSpace3, tokens::kSpace3,
                               tokens::kSpace3, tokens::kSpace3);
    layout->setSpacing(tokens::kSpace2);

    auto* header = new QHBoxLayout();
    title_ = new QLabel(QStringLiteral("专业工作流合同"), this);
    header->addWidget(title_, 1);
    dev_btn_ = new QPushButton(QStringLiteral("开发/咨询详情"), this);
    dev_btn_->setObjectName(
        QStringLiteral("WorkflowContractDevToggle"));
    dev_btn_->setCheckable(true);
    connect(dev_btn_, &QPushButton::toggled, this,
            [this](bool on) {
                dev_mode_ = on;
                refresh();
            });
    header->addWidget(dev_btn_);
    layout->addLayout(header);

    scroll_ = new QScrollArea(this);
    scroll_->setWidgetResizable(true);
    scroll_->setFrameShape(QFrame::NoFrame);
    body_ = new QWidget();
    body_layout_ = new QVBoxLayout(body_);
    body_layout_->setContentsMargins(0, 0, 0, 0);
    body_layout_->setSpacing(tokens::kSpace1);
    scroll_->setWidget(body_);
    layout->addWidget(scroll_, 1);

    refresh();
}

void WorkflowContractPanel::set_contract_id(
    const QString& contract_id) {
    contract_id_ = contract_id.toStdString();
    refresh();
}

void WorkflowContractPanel::set_readiness_fn(ReadinessFn readiness_fn) {
    readiness_fn_ = std::move(readiness_fn);
    refresh();
}

void WorkflowContractPanel::clear_lines() {
    while (body_layout_->count()) {
        QLayoutItem* item = body_layout_->takeAt(0);
        if (QWidget* w = item->widget()) {
            w->deleteLater();
        }
        delete item;
    }
    lines_.clear();
}

void WorkflowContractPanel::add_line(const ContractLine& line) {
    auto* label = new QLabel(QString::fromStdString(line.text), body_);
    label->setWordWrap(true);
    const char* color = line.warn       ? "#b45309"   // WARNING
                        : line.primary  ? "#18232d"   // TEXT_PRIMARY
                                        : "#53616c";  // TEXT_SECONDARY
    label->setStyleSheet(QStringLiteral(
        "color: %1; font-size: 12px; font-weight: %2;")
        .arg(QString::fromLatin1(color))
        .arg(line.primary ? 600 : 400));
    label->setTextInteractionFlags(Qt::TextSelectableByMouse);
    body_layout_->addWidget(label);
    lines_.push_back(label);
}

void WorkflowContractPanel::refresh() {
    clear_lines();
    const workflow_contracts::WorkflowContractRegistry* registry =
        registry_ != nullptr ? registry_
                             : &workflow_contracts::
                                   get_default_registry();
    const workflow_contracts::DomainWorkflowContract* contract =
        registry->get_contract(contract_id_);
    title_->setText(QString::fromStdString(
        contract_title_text(contract).empty()
            ? QStringLiteral("专业工作流合同").toStdString()
            : contract_title_text(contract)));
    const std::optional<workflow_contracts::ReadinessReport> report =
        readiness_fn_ ? readiness_fn_(contract_id_) : std::nullopt;
    for (const ContractLine& line :
         contract_panel_lines(contract, report ? &*report : nullptr,
                              dev_mode_, contract_id_)) {
        add_line(line);
    }
    body_layout_->addStretch();
}

}  // namespace pwb::ui_review::qt
