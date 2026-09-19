#include "pwb/ui_review/qt/ai_check_advisor_dialog.hpp"

#include "pwb/ui_review/advisor_html.hpp"

#include <QLabel>
#include <QPushButton>
#include <QTextBrowser>

namespace pwb::ui_review::qt {

AICheckAdvisorDialog::AICheckAdvisorDialog(QWidget* parent,
                                           const domain::Json& bh_report,
                                           const domain::Json& fault_report)
    : ui_widgets::PwbDialog(
          QStringLiteral("地质数据一致性核复顾问（规则检查）"), parent) {
    setModal(false);
    resize(550, 650);

    auto* header =
        new QLabel(QStringLiteral("地质数据一致性核复报告（规则检查）"), this);
    header->setObjectName(QStringLiteral("PwbSectionHeader"));
    add_content(header);

    browser_ = new QTextBrowser(this);
    browser_->setOpenExternalLinks(true);
    add_content(browser_, 1);

    browser_->setHtml(
        QString::fromStdString(build_advisor_html(bh_report, fault_report)));

    auto* btn_close = new QPushButton(QStringLiteral("确认并关闭"), this);
    btn_close->setObjectName(QStringLiteral("PrimaryButton"));
    connect(btn_close, &QPushButton::clicked, this, &QDialog::accept);
    add_content(btn_close);
}

}  // namespace pwb::ui_review::qt
