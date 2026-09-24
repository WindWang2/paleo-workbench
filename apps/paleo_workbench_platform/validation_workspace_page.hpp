#pragma once

// M3 (ribbon five-workspaces, plan 00-plan.md §4-M3 / D5) — the 验证
// workspace (ws4) composition page (mockup-faithful-2026-09-24 改订):
//
//   QSplitter(H):
//     left  QSplitter(V):
//             top    QSplitter(H): 只读 DisplayMapCanvas（验证对比）|
//                                  地震剖面窗格（两套解释对照）
//             bottom 井验证对比窗格（ComparisonView，宿主注入）
//     right QSplitter(V):
//             top    验证结果窗格（QcIssueTable 结构化问题列表）
//             bottom 选中问题详情窗格（InteractiveQCHub 定位 +
//                    复核处置面板，宿主注入）
//
// Contracts:
//   * QC runs through the EXISTING IReviewActions (closure_review binding —
//     the same provider the review page uses); no second review authority.
//     Ribbon 的「运行验证」直调 run_qc() —— 单一命令入口。
//   * Issue click → SmoothPanController::pan_to_extent on the read-only
//     DisplayMapCanvas (locate point padded 10%) — never a text-only popup.
//   * 未注入的窗格保持诚实空态 —— 无伪造对比、无假复核状态。

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

    // M5: inject the real widgets — ComparisonView 入底部「井验证
    // 对比」窗格，ReviewDispositionPanel 并入「选中问题详情」窗格。
    void set_compare_view(QWidget* view);
    void set_review_panel(QWidget* panel);

public slots:
    // 「运行验证」唯一入口（ribbon verify.run / 复核面板 rerun 直调）。
    void run_qc();

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
    void locate_issue(const QVariantMap& issue);
    void locate_rule_row(int row, int column);
    void refresh_result_stats();

    pwb::ui_map::DisplayMapCanvas* map_ = nullptr;
    QWidget* seismic_host_ = nullptr;
    QLabel* seismic_empty_ = nullptr;
    pwb::ui_review::qt::QcIssueTable* table_ = nullptr;
    QLabel* stats_pass_ = nullptr;
    QLabel* stats_pending_ = nullptr;
    QLabel* stats_skipped_ = nullptr;
    pwb::ui_widgets::InteractiveQCHub* hub_ = nullptr;
    pwb::ui_widgets::SmoothPanController* pan_ = nullptr;
    QWidget* compare_host_ = nullptr;   // 「井验证对比」窗格内容槽
    QWidget* detail_host_ = nullptr;    // 「选中问题详情」窗格内容槽
    QWidget* compare_view_ = nullptr;
    QWidget* review_panel_ = nullptr;
    std::function<pwb::ui_review::IReviewActions*()> actions_provider_;
    std::vector<pwb::domain::Json> reports_;
};

}  // namespace pwb::app
