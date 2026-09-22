#pragma once

// M3 (ribbon five-workspaces, plan 00-plan.md §4-M3 / D5) — the 验证
// workspace (ws4) composition page:
//
//   QSplitter(H):
//     left  QSplitter(V):
//             top    QSplitter(H): 只读 DisplayMapCanvas | 地震剖面窗格
//             bottom QcIssueTable (结构化问题列表)
//     right QTabWidget: 复核详情 (InteractiveQCHub + 定位)
//                       | 解释 vs 预测对比 (M5 占位)
//                       | 复核记录 (M5 占位)
//
// Contracts:
//   * QC runs through the EXISTING IReviewActions (closure_review binding —
//     the same provider the review page uses); no second review authority.
//   * Issue click → SmoothPanController::pan_to_extent on the read-only
//     DisplayMapCanvas (locate point padded 10%) — never a text-only popup.
//   * The M5 gaps (解释 vs 预测对比视图, 问题级人工复核状态机) are EXPLICIT
//     placeholders — no fabricated comparison, no fake review state.

#include <functional>
#include <vector>

#include <QWidget>

#include <pwb/domain/json.hpp>

class QLabel;
class QSplitter;
class QTabWidget;

namespace pwb::ui_map {
class DisplayMapCanvas;
}
namespace pwb::ui_review::qt {
class QcIssueTable;
}
namespace pwb::ui_widgets {
class InteractiveQCHub;
class SmoothPanController;
}
namespace pwb::ui_review {
class IReviewActions;
}

namespace pwb::app {

class ValidationWorkspacePage : public QWidget {
    Q_OBJECT
public:
    explicit ValidationWorkspacePage(QWidget* parent = nullptr);
    ~ValidationWorkspacePage() override;

    // ---- host assembly seams ----------------------------------------------
    // The seismic comparison pane (a host-created SeismicSliceWidget); a
    // null widget keeps the honest empty surface.
    void set_seismic_pane(QWidget* pane);
    // The closure_review binding injects the SAME IReviewActions provider
    // the review page carries (unbound → every run reports 未绑定工程).
    void set_actions_provider(
        std::function<pwb::ui_review::IReviewActions*()> provider);

    // Reports refresh (QualityReport dicts — active_quality_reports parity).
    void update_reports(const std::vector<pwb::domain::Json>& reports);

    // M5: replace the 对比视图（M5）/ 复核记录（M5）placeholder tabs with
    // the real widgets (ComparisonView / ReviewDispositionPanel).
    void set_compare_view(QWidget* view);
    void set_review_panel(QWidget* panel);

    // Test/inspection surface.
    pwb::ui_map::DisplayMapCanvas* map_canvas() const { return map_; }
    pwb::ui_review::qt::QcIssueTable* issue_table() const { return table_; }
    pwb::ui_widgets::InteractiveQCHub* qc_hub() const { return hub_; }
    QWidget* compare_view() const { return compare_view_; }
    QWidget* review_panel() const { return review_panel_; }
    const std::vector<pwb::domain::Json>& reports() const { return reports_; }

signals:
    void status_message(const QString& message);
    // The selected issue (table row click / hub focus) — the M5 review
    // panel consumes this to prefill its draft.
    void issue_selected(const QVariantMap& issue);
    // Emitted at the end of every update_reports — the M5 install
    // refreshes the staleness banner from this.
    void reports_refreshed();

private:
    void run_qc();
    void locate_issue(const QVariantMap& issue);
    void locate_rule_row(int row, int column);

    pwb::ui_map::DisplayMapCanvas* map_ = nullptr;
    QWidget* seismic_host_ = nullptr;
    QLabel* seismic_empty_ = nullptr;
    pwb::ui_review::qt::QcIssueTable* table_ = nullptr;
    pwb::ui_widgets::InteractiveQCHub* hub_ = nullptr;
    pwb::ui_widgets::SmoothPanController* pan_ = nullptr;
    QTabWidget* right_tabs_ = nullptr;
    QWidget* compare_view_ = nullptr;
    QWidget* review_panel_ = nullptr;
    std::function<pwb::ui_review::IReviewActions*()> actions_provider_;
    std::vector<pwb::domain::Json> reports_;
};

}  // namespace pwb::app
