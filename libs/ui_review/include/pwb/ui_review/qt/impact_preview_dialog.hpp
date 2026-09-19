#pragma once

// UI-11 — impact_preview_dialog.py Qt shell: the pre-destructive impact
// gate. ``confirm_trash_impact`` runs the bounded aggregation, returns
// true silently when there is no downstream impact, and otherwise shows
// the markdown detail dialog with 取消 as the default (conservative —
// Enter cancels).

#include <QDialog>

class QTextBrowser;

namespace pwb::ui_review {
class IDeleteImpact;
class IMapUsageSource;
struct TrashImpactSummary;
}  // namespace pwb::ui_review

namespace pwb::ui_review::qt {

// The dialog itself (public for tests; callers normally use the helper).
class ImpactPreviewDialog : public QDialog {
    Q_OBJECT
public:
    ImpactPreviewDialog(QWidget* parent,
                        const TrashImpactSummary& summary,
                        const std::vector<std::string>& asset_ids,
                        const std::vector<std::string>& asset_names);

    QTextBrowser* browser() const { return browser_; }

private:
    QTextBrowser* browser_ = nullptr;
};

// confirm_trash_impact parity. Returns true when the caller may proceed:
// silently true when nothing downstream is affected, otherwise the
// user's explicit confirmation. computation_errors > 0 counts as
// downstream (fail-closed — never silently allows).
[[nodiscard]] bool confirm_trash_impact(
    QWidget* parent, IDeleteImpact& impact,
    IMapUsageSource* map_usages,
    const std::vector<std::string>& asset_ids,
    const std::vector<std::string>& asset_names = {});

}  // namespace pwb::ui_review::qt
