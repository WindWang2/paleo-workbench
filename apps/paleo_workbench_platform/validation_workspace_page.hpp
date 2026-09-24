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
#include <optional>
#include <utility>
#include <vector>

#include <QList>
#include <QString>
#include <QStringList>
#include <QVariant>
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
namespace pwb::qgis_processing {
class PwbTaskOwner;
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

    // ---- async QC seam（verify.cancel 的生产基础） -------------------------
    // 三段缝（装全才走异步；缺任一回退同步路径）：
    //   snapshot — GUI 线程取不可变工程快照 + 文档 id 清单；
    //   run      — worker 线程在快照副本上逐文档跑真 QC 内核（协作取消）；
    //   merge    — GUI 线程把报告合并进 LIVE root 并落盘（cancelled 永不
    //              到这里——上一份有效报告保持不变）。
    struct AsyncQc {
        std::function<std::optional<std::pair<pwb::domain::Json,
                                              std::vector<std::string>>>()>
            snapshot;
        std::function<std::vector<pwb::domain::Json>(
            pwb::domain::Json& snapshot_root,
            const std::vector<std::string>& doc_ids,
            const std::function<bool()>& check_cancelled)>
            run;
        std::function<std::string(
            const std::vector<pwb::domain::Json>& reports)>
            merge;
    };
    void set_async_qc(AsyncQc seam);
    // Task owner（JobCenter 派发；空 = 无异步宿主，run_qc 回退同步）。
    void set_task_owner(pwb::qgis_processing::PwbTaskOwner* owner);

    // Reports refresh (QualityReport dicts — active_quality_reports parity).
    void update_reports(const std::vector<pwb::domain::Json>& reports);

    // M5: inject the real widgets — ComparisonView 入底部「井验证
    // 对比」窗格，ReviewDispositionPanel 并入「选中问题详情」窗格。
    void set_compare_view(QWidget* view);
    void set_review_panel(QWidget* panel);

public slots:
    // 「运行验证」唯一入口（ribbon verify.run / 复核面板 rerun 直调）。
    void run_qc();
    // 取消运行中的异步 QC（同步回退路径无可取消任务——命令层口径一致）。
    void cancel_qc();

    // ---- IssueNavigator ----------------------------------------------------
    // 扁平化问题导航（verify.prev_issue = -1 / verify.locate = +1）。
    // 固定规则：wrap-around（到尾回到头），无问题时报状态不出错。
    void navigate_issue(int delta);
    // 定位当前游标问题（不动游标）。
    void locate_current_issue();

    // Test/inspection surface.
    pwb::ui_map::DisplayMapCanvas* map_canvas() const { return map_; }
    pwb::ui_review::qt::QcIssueTable* issue_table() const { return table_; }
    pwb::ui_widgets::InteractiveQCHub* qc_hub() const { return hub_; }
    QWidget* compare_view() const { return compare_view_; }
    QWidget* review_panel() const { return review_panel_; }
    const std::vector<pwb::domain::Json>& reports() const { return reports_; }
    bool qc_running() const { return qc_running_; }
    int issue_count() const { return flattened_issues_.size(); }
    int issue_cursor() const { return cursor_; }
    QString current_issue_key() const;

signals:
    void status_message(const QString& message);
    // The selected issue (table row click / hub focus) — the M5 review
    // panel consumes this to prefill its draft.
    void issue_selected(const QVariantMap& issue);
    // Emitted at the end of every update_reports — the M5 install
    // refreshes the staleness banner from this.
    void reports_refreshed();
    // Async QC lifecycle observation (ribbon applicability follows this).
    void qc_state_changed();

private:
    void locate_issue(const QVariantMap& issue);
    void locate_rule_row(int row, int column);
    void refresh_result_stats();
    void rebuild_flattened_issues();

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
    // Async QC orchestration state.
    AsyncQc async_qc_;
    pwb::qgis_processing::PwbTaskOwner* task_owner_ = nullptr;
    bool qc_running_ = false;
    // IssueNavigator state（全报告扁平化；key = report|qc_issue_key）。
    QList<QVariantMap> flattened_issues_;
    QStringList flattened_keys_;
    int cursor_ = -1;
};

}  // namespace pwb::app
