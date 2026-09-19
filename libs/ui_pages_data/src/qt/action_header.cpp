// UI-06 — ActionHeader shell (see qt/action_header.hpp).
#include <pwb/ui_pages_data/qt/action_header.hpp>

#include <QHBoxLayout>
#include <QLabel>
#include <QPushButton>
#include <QVBoxLayout>

#include <pwb/ui_pages_data/qc_summary.hpp>
#include <pwb/ui_pages_data/vocab.hpp>
#include <pwb/ui_shell/style_registry.hpp>

namespace pwb::ui_pages_data::qt {
namespace {

QString pal(const char* token) {
    const auto p = ui_shell::style_palette();
    const auto it = p.find(token);
    return it != p.end() ? QString::fromStdString(it->second) : QString();
}

}  // namespace

ActionHeader::ActionHeader(QWidget* parent) : QFrame(parent) {
    setObjectName(QStringLiteral("PanelCard"));
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(12, 12, 12, 12);  // SPACE_3
    layout->setSpacing(12);                      // SPACE_3

    title_label_ = new QLabel(
        QStringLiteral("成图与审核 · — 古地理图（自动质检 + 人工审核）"),
        this);
    ui_shell::style_bind(title_label_, [] {
        return QStringLiteral(
                   "color: %1; font-size: 14px; font-weight: 600;"
                   " border: none; background: transparent;")
            .arg(pal("TEXT_PRIMARY"));           // FONT_SIZE_TITLE
    });
    layout->addWidget(title_label_);

    auto* button_row = new QHBoxLayout();
    button_row->setSpacing(8);                   // SPACE_2
    run_btn_ = new QPushButton(QStringLiteral("运行检查"), this);
    run_btn_->setObjectName(QStringLiteral("PrimaryButton"));
    run_btn_->setToolTip(QStringLiteral("运行自动质检规则"));
    connect(run_btn_, &QPushButton::clicked, this,
            &ActionHeader::run_requested);
    button_row->addWidget(run_btn_);
    config_btn_ = new QPushButton(QStringLiteral("规则配置"), this);
    config_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    config_btn_->setToolTip(
        QStringLiteral("当前规则见下方列表（配置面板后续迭代）"));
    connect(config_btn_, &QPushButton::clicked, this,
            &ActionHeader::config_requested);
    button_row->addWidget(config_btn_);
    export_btn_ = new QPushButton(QStringLiteral("导出检查报告"), this);
    export_btn_->setObjectName(QStringLiteral("PrimaryButton"));
    export_btn_->setToolTip(QStringLiteral("导出质检报告文件"));
    connect(export_btn_, &QPushButton::clicked, this,
            &ActionHeader::export_requested);
    button_row->addWidget(export_btn_);
    finalize_btn_ = new QPushButton(QStringLiteral("专家定稿"), this);
    finalize_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    finalize_btn_->setToolTip(
        QStringLiteral("将当前古地理图写入 VersionSet 快照并标记为 final"));
    connect(finalize_btn_, &QPushButton::clicked, this,
            &ActionHeader::finalize_requested);
    button_row->addWidget(finalize_btn_);
    button_row->addStretch();
    layout->addLayout(button_row);

    std::string rules;
    for (std::size_t i = 0; i < kDefaultQcRules.size(); ++i) {
        if (i) rules += " · ";
        rules += kDefaultQcRules[i];
    }
    rules_label_ = new QLabel(
        QStringLiteral("检查规则: %1").arg(QString::fromStdString(rules)),
        this);
    ui_shell::style_bind(rules_label_, [] {
        return QStringLiteral(
                   "color: %1; font-size: 11px;"
                   " border: none; background: transparent;")
            .arg(pal("TEXT_SECONDARY"));         // FONT_SIZE_STATUS
    });
    layout->addWidget(rules_label_);
}

void ActionHeader::update_state(const domain::Json& reports,
                                const domain::Json& docs) {
    const ActionHeaderState s = resolve_action_header(reports, docs);
    title_label_->setText(QString::fromStdString(s.title));
    rules_label_->setText(QString::fromStdString(s.rules_line));
    run_btn_->setEnabled(s.run_enabled);
    export_btn_->setEnabled(s.export_enabled);
    finalize_btn_->setEnabled(s.finalize_enabled);
}

}  // namespace pwb::ui_pages_data::qt
