#pragma once

// UI-11 — review_export_page.py Qt shell: the 成图审核 page (run QC →
// review issues → export report JSON → expert finalize). Reuses:
//   ui_pages_data::qt::ActionHeader  (UI-06 widget)
//   ui_pages_data::summarize_qc      (UI-06 core, via ResultSummaryPanel)
//   ui_shell::FloatController / LayoutPersistence / dock_manager (UI-01)
//   QCIssueTable + ResultSummaryPanel (this slice)
// The workflow calls stay behind IReviewActions — the page never touches
// the project or the QC engine directly.

#include "pwb/domain/json.hpp"
#include "pwb/ui_review/review_core.hpp"

#include <QToolButton>
#include <QWidget>

#include <functional>
#include <map>
#include <memory>
#include <string>

namespace pwb::ui_shell {
class FloatController;
class LayoutPersistence;
}  // namespace pwb::ui_shell
namespace pwb::ui_pages_data::qt {
class ActionHeader;
}  // namespace pwb::ui_pages_data::qt

class QEvent;
class QObject;
class QSplitter;
class QTimer;

namespace pwb::ui_review::qt {

class QcIssueTable;
class ResultSummaryPanel;

// PanelFloatButton parity: the ⇱ corner button that floats one side
// panel; hidden while the panel is afloat (the floating window carries
// its own dock-back button).
class PanelFloatButton : public QToolButton {
    Q_OBJECT
public:
    PanelFloatButton(const QString& key, QWidget* panel,
                     ui_shell::FloatController* controller);

protected:
    bool eventFilter(QObject* obj, QEvent* event) override;

private:
    void reposition();

    QString key_;
    QWidget* panel_;
    ui_shell::FloatController* controller_;
};

class ReviewExportPage : public QWidget {
    Q_OBJECT
public:
    ReviewExportPage(
        QWidget* parent,
        std::function<IReviewActions*()> actions_provider,
        ui_shell::LayoutPersistence* persistence = nullptr);
    ~ReviewExportPage() override;

    // CLOSURE-REVIEW (line 09): late provider binding for hosts that
    // install the real project backend after page construction (the
    // closure installer). Replacing the constructor-passed provider is the
    // whole contract — an empty std::function restores the unbound state.
    void set_actions_provider(
        std::function<IReviewActions*()> provider) {
        actions_provider_ = std::move(provider);
    }

    // set_project(project) parity — nullptr unbinds (run/finalize guard
    // "未绑定工程"; export falls back to the cached reports).
    void set_project_bound(bool bound);
    void update_state(const domain::Json& reports,
                      const domain::Json& map_documents,
                      const domain::Json& artifacts);

    // The page's four actions (action_header signal handlers).
    void run_qc();
    void export_report();
    void on_config();
    void finalize_version();

    // Python attribute surface.
    ui_pages_data::qt::ActionHeader* action_header() const {
        return action_header_;
    }
    QcIssueTable* qc_table() const { return qc_table_; }
    ResultSummaryPanel* result_summary() const { return result_summary_; }
    QSplitter* content_splitter() const { return content_splitter_; }
    ui_shell::FloatController* float_controller() const {
        return float_controller_;
    }

signals:
    void reports_updated();
    void version_finalized();

private:
    IReviewActions* actions() const;
    void refresh_from_project();
    void make_floatable(const QString& key, QWidget* panel,
                        const QString& title);
    void persist_docked_sizes();
    void setup_tab_order();

    std::function<IReviewActions*()> actions_provider_;
    ui_shell::LayoutPersistence* persistence_;  // not owned (may be null)
    std::unique_ptr<ui_shell::LayoutPersistence> owned_persistence_;
    std::map<QString, QWidget*> floatable_;
    domain::Json reports_ = domain::Json::array();
    domain::Json map_documents_ = domain::Json::array();
    domain::Json artifacts_ = domain::Json::array();
    bool project_bound_ = false;

    ui_pages_data::qt::ActionHeader* action_header_ = nullptr;
    QSplitter* content_splitter_ = nullptr;
    QcIssueTable* qc_table_ = nullptr;
    ResultSummaryPanel* result_summary_ = nullptr;
    ui_shell::FloatController* float_controller_ = nullptr;
    QTimer* float_sizes_timer_ = nullptr;
};

}  // namespace pwb::ui_review::qt
