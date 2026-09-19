#include "pwb/ui_review/qt/impact_preview_dialog.hpp"

#include "pwb/ui_review/impact_markdown.hpp"

#include <QHBoxLayout>
#include <QLabel>
#include <QPushButton>
#include <QStringList>
#include <QTextBrowser>
#include <QVBoxLayout>

#include <algorithm>

namespace pwb::ui_review::qt {

ImpactPreviewDialog::ImpactPreviewDialog(
    QWidget* parent, const TrashImpactSummary& summary,
    const std::vector<std::string>& asset_ids,
    const std::vector<std::string>& asset_names)
    : QDialog(parent) {
    setWindowTitle(QStringLiteral("移出项目 — 影响预览"));
    resize(560, 420);
    auto* layout = new QVBoxLayout(this);

    QString names;
    if (!asset_names.empty()) {
        const size_t shown = std::min<size_t>(5, asset_names.size());
        QStringList parts;
        for (size_t i = 0; i < shown; ++i) {
            parts << QString::fromStdString(asset_names[i]);
        }
        names = parts.join(QStringLiteral("、"));
        if (asset_names.size() > 5) {
            names += QStringLiteral("…");
        }
    } else {
        names = QStringLiteral("%1 个资产").arg(asset_ids.size());
    }
    auto* header =
        new QLabel(QStringLiteral("即将移出：") + names, this);
    header->setWordWrap(true);
    layout->addWidget(header);

    browser_ = new QTextBrowser(this);
    browser_->setOpenExternalLinks(false);
    // Python renders markdown→HTML with a plaintext fallback; Qt renders
    // markdown natively.
    browser_->setMarkdown(
        QString::fromStdString(summary.render_markdown()));
    layout->addWidget(browser_, 1);

    auto* buttons = new QHBoxLayout();
    buttons->addStretch(1);
    auto* cancel_btn = new QPushButton(QStringLiteral("取消"), this);
    cancel_btn->setDefault(true);  // 保守：默认聚焦取消
    auto* proceed_btn =
        new QPushButton(QStringLiteral("仍然移出（进回收站）"), this);
    proceed_btn->setObjectName(QStringLiteral("PrimaryButton"));
    buttons->addWidget(cancel_btn);
    buttons->addWidget(proceed_btn);
    layout->addLayout(buttons);

    connect(proceed_btn, &QPushButton::clicked, this, &QDialog::accept);
    connect(cancel_btn, &QPushButton::clicked, this, &QDialog::reject);
}

bool confirm_trash_impact(QWidget* parent, IDeleteImpact& impact,
                          IMapUsageSource* map_usages,
                          const std::vector<std::string>& asset_ids,
                          const std::vector<std::string>& asset_names) {
    const TrashImpactSummary summary =
        collect_trash_impact(impact, map_usages, asset_ids);
    if (!summary.has_downstream()) {
        return true;
    }
    ImpactPreviewDialog dialog(parent, summary, asset_ids, asset_names);
    return dialog.exec() == QDialog::Accepted;
}

}  // namespace pwb::ui_review::qt
