// pwb::closure_science::qt — the ws1 prediction workflow controller:
// the single owner of the current PredictionRunSpec draft.
//
//   predict.select_well   -> open_well_selection()   (stable well ids)
//   predict.model_params  -> open_model_selection()  (registry + package)
//   predict.params        -> open_params()           (schema-driven)
//   predict.run           -> run()                   (preflight -> run)
//   predict.cancel        -> cancel()                (cooperative)
//   predict.link          -> link() toggle           (WellSeismicLink)
//
// The UI only ever edits the spec through this controller; the runner
// consumes the same spec; persistence (project section "prediction_run_
// spec") records the same spec — one contract end to end. The controller
// holds no catalog state of its own: every dialog query goes through the
// SciencePageBinding (document-lock guarded).
#pragma once

#include <pwb/closure_science/qt/page_binding.hpp>
#include <pwb/closure_science/qt/well_seismic_link.hpp>
#include <pwb/domain/errors.hpp>
#include <pwb/domain/json.hpp>
#include <pwb/prediction/run_spec.hpp>

#include <QObject>
#include <QString>
#include <QWidget>

#include <functional>
#include <optional>
#include <string>
#include <vector>

namespace pwb::ui_wellseis::qt {
class SeismicPredictionPage;
class WellLogPredictionPage;
}

namespace pwb::closure_science::qt {

class PredictionWorkflowController : public QObject {
    Q_OBJECT
public:
    // Project-document persistence seams (installed by the app; the
    // controller never touches the live store itself).
    struct ProjectSeams {
        // Current persisted spec section (null/absent = none stored).
        std::function<domain::Json()> read_run_spec;
        // Persist the section (returns non-Ok on save failure — surfaced,
        // never swallowed).
        std::function<domain::DataError(const domain::Json&)> write_run_spec;
    };

    PredictionWorkflowController(
        SciencePageBinding* binding,
        ui_wellseis::qt::WellLogPredictionPage* well_page,
        ui_wellseis::qt::SeismicPredictionPage* seismic_page,
        QObject* parent = nullptr);
    ~PredictionWorkflowController() override;

    void set_project_seams(ProjectSeams seams);
    void set_dialog_parent(QWidget* parent);

    // Restores the persisted spec (called on project open); keeps the
    // draft untouched when nothing valid is stored. Returns true when a
    // stored spec was restored.
    bool restore_persisted_spec();

    [[nodiscard]] const pwb::prediction::PredictionRunSpec& spec() const {
        return spec_;
    }

    // --- command bodies (ribbon callbacks land here) -------------------
    void open_well_selection();
    void open_model_selection();
    void open_params();
    // Full gate chain: build (spec as-is) -> preflight (inside the
    // binding, under the document lock) -> run. Errors/warnings surface
    // through status_message + the returned bool.
    bool run();
    // Cooperative cancel; returns false when nothing is running.
    bool cancel();

    // The ws1 well-seismic link (predict.link).
    [[nodiscard]] WellSeismicLinkController* link() const { return link_; }

    [[nodiscard]] bool is_running() const;

signals:
    void spec_changed();
    void status_message(const QString& message);

private:
    void persist_spec();
    void apply_seismic_selection(const std::string& resource_id);

    SciencePageBinding* binding_ = nullptr;
    ui_wellseis::qt::WellLogPredictionPage* well_page_ = nullptr;
    ui_wellseis::qt::SeismicPredictionPage* seismic_page_ = nullptr;
    ProjectSeams seams_;
    QWidget* dialog_parent_ = nullptr;
    pwb::prediction::PredictionRunSpec spec_;
    WellSeismicLinkController* link_ = nullptr;
};

// Installs the controller (findChild-able, objectName
// "PredictionWorkflowController"). The app's ribbon install resolves it
// lazily — the install order stays decoupled.
[[nodiscard]] PredictionWorkflowController* install_prediction_workflow(
    SciencePageBinding* binding,
    ui_wellseis::qt::WellLogPredictionPage* well_page,
    ui_wellseis::qt::SeismicPredictionPage* seismic_page,
    QObject* parent);

}  // namespace pwb::closure_science::qt
