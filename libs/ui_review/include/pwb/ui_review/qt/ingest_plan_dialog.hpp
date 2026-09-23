#pragma once

// UI-11 — ingest_plan_dialog.py Qt shell: two-phase zero-side-effect
// ingest UI (build on a worker → editable plan table → execute on a
// worker, cooperative cancel). The dialog shares the same data-suite
// entry points the harness ingest action uses — UI import and agent
// import are NOT two implementations.
//
// Service seam: the host binds the project document + writable session
// into IngestDialogHooks; tests inject fakes. The dialog itself never
// touches the catalog or the project directly.

#include "pwb/data/ingest_exec.hpp"
#include "pwb/data/ingest_plan.hpp"
#include "pwb/ui_review/ingest_columns.hpp"

#include <QDialog>
#include <QFrame>

#include <filesystem>
#include <functional>
#include <memory>
#include <vector>

namespace pwb::qgis_processing {
class PwbTaskOwner;
}  // namespace pwb::qgis_processing
namespace pwb::ui_widgets {
class ObjectTableModel;
}  // namespace pwb::ui_widgets

class QCheckBox;
class QComboBox;
class QCloseEvent;
class QLabel;
class QProgressBar;
class QPushButton;
class QTableView;

namespace pwb::ui_review::qt {

// Host bindings — the Python ``service``/``project`` pair. project_json
// supplies the wells/seismic_surveys rows for the entity combo; build /
// execute wrap data::build_ingest_plan / data::execute_ingest_plan with
// the session already bound (worker-thread callables).
struct IngestDialogHooks {
    // project wells/surveys for the entity combo (id/name/uwi rows).
    std::function<std::vector<IngestEntityRow>()> wells;
    std::function<std::vector<IngestEntityRow>()> surveys;
    std::function<data::IngestPlan(const std::filesystem::path&,
                                   const data::IngestPlanOptions&)>
        build;
    std::function<data::IngestExecuteReport(
        const data::IngestPlan&, const data::IngestExecuteOptions&)>
        execute;
};

// _ItemDetailPanel parity — decision/role/entity/primary editors for the
// selected plan item.
class IngestItemDetailPanel : public QFrame {
    Q_OBJECT
public:
    explicit IngestItemDetailPanel(QWidget* parent = nullptr);

    // set_item parity — repopulates combos (signal-suppressed) and gates
    // enabled state. wells/surveys feed the entity combo.
    void set_item(data::PlannedItem* item,
                  const std::vector<IngestEntityRow>& wells,
                  const std::vector<IngestEntityRow>& surveys);

    QComboBox* decision_combo() const { return decision_combo_; }
    QComboBox* role_combo() const { return role_combo_; }
    QComboBox* entity_combo() const { return entity_combo_; }
    QCheckBox* primary_check() const { return primary_check_; }
    QLabel* title_label() const { return title_label_; }

signals:
    void item_edited();

private:
    void reload_roles(const data::PlannedItem& item);
    void reload_entities(const data::PlannedItem& item);
    void apply();

    data::PlannedItem* item_ = nullptr;
    std::vector<IngestEntityRow> wells_;
    std::vector<IngestEntityRow> surveys_;
    bool suppress_sync_ = false;

    QLabel* title_label_ = nullptr;
    QComboBox* decision_combo_ = nullptr;
    QComboBox* role_combo_ = nullptr;
    QComboBox* entity_combo_ = nullptr;
    QCheckBox* primary_check_ = nullptr;
};

class IngestPlanDialog : public QDialog {
    Q_OBJECT
public:
    IngestPlanDialog(QWidget* parent, IngestDialogHooks hooks,
                     std::filesystem::path root);
    ~IngestPlanDialog() override;

    // Python attribute surface.
    QLabel* header_label() const { return header_label_; }
    QLabel* summary_label() const { return summary_label_; }
    QProgressBar* progress() const { return progress_; }
    QTableView* table() const { return table_; }
    ui_widgets::ObjectTableModel* model() const { return model_; }
    IngestItemDetailPanel* detail() const { return detail_; }
    QPushButton* accept_all_btn() const { return accept_all_btn_; }
    QPushButton* skip_unresolved_btn() const { return skip_unresolved_btn_; }
    QPushButton* cancel_run_btn() const { return cancel_run_btn_; }
    QPushButton* execute_btn() const { return execute_btn_; }
    const data::IngestPlan* plan() const {
        return plan_ ? &*plan_ : nullptr;
    }

signals:
    void ingest_finished();

protected:
    void closeEvent(QCloseEvent* event) override;

private:
    void start_build();
    void execute();
    void cancel_run();
    void teardown_worker();
    void set_running(bool running);
    void on_selection_changed();
    void on_item_edited();
    void accept_all();
    void skip_unresolved();
    void refresh_summary();
    void rebuild_rows();
    std::vector<IngestEntityRow> wells() const;
    std::vector<IngestEntityRow> surveys() const;

    IngestDialogHooks hooks_;
    std::filesystem::path root_;
    std::unique_ptr<pwb::qgis_processing::PwbTaskOwner> job_;
    std::optional<data::IngestPlan> plan_;
    bool running_ = false;

    QLabel* header_label_ = nullptr;
    QLabel* summary_label_ = nullptr;
    QProgressBar* progress_ = nullptr;
    ui_widgets::ObjectTableModel* model_ = nullptr;
    QTableView* table_ = nullptr;
    IngestItemDetailPanel* detail_ = nullptr;
    QPushButton* accept_all_btn_ = nullptr;
    QPushButton* skip_unresolved_btn_ = nullptr;
    QPushButton* cancel_run_btn_ = nullptr;
    QPushButton* execute_btn_ = nullptr;
};

}  // namespace pwb::ui_review::qt
