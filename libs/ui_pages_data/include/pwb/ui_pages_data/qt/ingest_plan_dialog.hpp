// V14-DATA-LINEAGE (P4) — Qt review dialog over the IngestPlanModel.
//
// Two-phase ingest, review half: the host builds the plan (worker, per
// the ui_review ingest dialog precedent), hands rows + two callbacks in,
// and the dialog owns the editable table + validation surface + the
// execute/cancel decision. The dialog itself never touches the catalog,
// the project or the filesystem — execute(rows) returns a user-visible
// summary string, cancel() is a plain notification. Offscreen-testable:
// no exec() inside the class, run_execute() is public.
#pragma once

#include <QDialog>

#include <functional>
#include <string>
#include <vector>

#include <pwb/ui_pages_data/ingest_plan_model.hpp>

class QLabel;
class QPushButton;
class QTableWidget;

namespace pwb::ui_pages_data::qt {

class IngestPlanDialog : public QDialog {
    Q_OBJECT
public:
    // execute: apply the reviewed rows (the host owns the domain plan —
    // pwb::ui_pages_data::apply_plan_rows + execute_ingest_plan) and
    // return a user-visible summary; may throw (caught + surfaced).
    using ExecuteFn =
        std::function<std::string(const std::vector<PlanItemRow>&)>;
    using CancelFn = std::function<void()>;

    IngestPlanDialog(std::vector<PlanItemRow> rows, ExecuteFn execute,
                     CancelFn cancel, QWidget* parent = nullptr);

    // Current review state (model copy — tests + hosts re-project it).
    const std::vector<PlanItemRow>& rows() const { return model_.rows(); }
    const IngestPlanModel& model() const { return model_; }

    // Programmatic bulk actions (buttons call the same slots).
    void accept_all();
    void skip_all();

    // Rebuild the table from the model (re-entrant safe). Public for
    // tests; every mutation path funnels back through here.
    void refresh_view();

    // Execute button body WITHOUT the exec loop: validates, runs the
    // execute callback, emits executed(summary) and closes on success.
    // Returns false (and refreshes the issues area) when validation
    // blocks the run.
    bool run_execute();

Q_SIGNALS:
    // accepted: Execute pressed and the callback returned (the summary
    // already reached the host through executed()).
    void accepted();
    void executed(const QString& summary);
    void cancelled();

private:
    void update_issues();
    void sync_row(std::size_t index);

    IngestPlanModel model_;
    ExecuteFn execute_;
    CancelFn cancel_;
    QTableWidget* table_ = nullptr;
    QLabel* issues_label_ = nullptr;
    QPushButton* execute_btn_ = nullptr;
    bool rebuilding_ = false;
};

}  // namespace pwb::ui_pages_data::qt
