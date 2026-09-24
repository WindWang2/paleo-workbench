#pragma once

// UI-14 — WorkflowController Qt shell (workflow_controller.py QObject
// surface parity).
//
// Owns WorkflowCore + the recompute/prepare JobOwnerRunners
// (self._recompute_job / self._prepare_job parity) and binds the dialog
// seams onto QMessageBox + the post_to_gui marshal onto a queued
// QMetaObject invocation. Page/app_shell surfaces stay injected through
// the *_api() accessors; wire_* mirrors the Python wire_* helpers with
// runtime signal-name checks (hasattr parity) and string-based connects —
// the integration adapter hands in the live page widgets.

#include <QObject>
#include <QString>

#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <vector>

#include <pwb/qgis_processing/task_bridge.hpp>
#include <pwb/ui_controllers/qt/job_owner_runner.hpp>
#include <pwb/ui_controllers/workflow_controller.hpp>

class QWidget;

namespace pwb::ui_controllers::qt {


class WorkflowController : public QObject {
    Q_OBJECT
public:
    // `gate` may be null (no admission — runners' tasks go straight to
    // QgsTaskManager); when non-null and no process-shared gate is
    // installed yet (JobCenter installs one app-lifetime), it becomes the
    // shared gate so the runners' tasks pass admission + task_key dedupe.
    explicit WorkflowController(
        pwb::qgis_processing::PwbTaskGate* gate = nullptr,
        QObject* parent = nullptr);
    ~WorkflowController() override;

    // The seam bags the integration adapter fills (bind before first
    // core() use).
    WorkflowPageApi& page_api() { return pages_; }
    WorkflowDialogApi& dialogs() { return dialogs_; }
    WorkflowServiceApi& services() { return services_; }
    CatalogRuntimeApi& catalog_api() { return catalog_; }
    PrepareGenerationApi& generation_api() { return generation_; }
    LiveFactorGridApi& grids_api() { return grids_; }
    FactorRecomputeSeams& factor_recompute() { return factor_recompute_; }
    ui_workers::FactorPrepareSeams& prepare_seams() {
        return prepare_seams_;
    }

    WorkflowCore& core();
    void rebind() { core_.reset(); }

    // QMessageBox binds (information/warning + the dirty Save/Discard/
    // Cancel question) + the queued post_to_gui marshal.
    void bind_dialogs(QWidget* parent);

    // ---- wire_* parity ---------------------------------------------------
    // Every wire_* checks the page's metaobject for the signal (Python
    // hasattr(page, "signal") parity) and string-connects it to the core
    // slot. `defer_page_binding(hub, page)` rides the injected seam —
    // app_shell.defer_page_project_binding parity.
    void set_defer_page_binding(
        std::function<void(int hub, QObject* page)> fn) {
        defer_page_binding_ = std::move(fn);
    }
    void wire_home_page(QObject* page);
    void wire_data_visualization_jump(QObject* page);
    void wire_mapping_page(QObject* page);
    void wire_preparation_page(QObject* page);
    void wire_sequence_page(QObject* page);
    void wire_seismic_page(QObject* page);
    void wire_well_log_page(QObject* page);
    void wire_geomodel_page(QObject* page);
    void wire_review_page(QObject* page);

    UiJobRunner* recompute_job() { return recompute_job_.get(); }
    UiJobRunner* prepare_job() { return prepare_job_.get(); }

public slots:
    void request_recompute() { core().request_recompute(); }
    void on_qc_reports_updated() { core().on_qc_reports_updated(); }
    void on_well_log_prediction_updated() {
        core().on_well_log_prediction_updated();
    }
    void on_seismic_prediction_updated() {
        core().on_seismic_prediction_updated();
    }
    void on_factor_maps_updated() { core().on_factor_maps_updated(); }
    void on_contour_drafts_updated() { core().on_contour_drafts_updated(); }
    void on_stratigraphy_updated() { core().on_stratigraphy_updated(); }
    void on_well_log_send_to_prep() { core().on_well_log_send_to_prep(); }
    void on_seismic_send_to_mapping() {
        core().on_seismic_send_to_mapping();
    }
    void on_generate_demo_map_draft() { core().on_generate_demo_map_draft(); }
    void on_home_navigation(int legacy_index) {
        core().on_home_navigation(legacy_index);
    }
    void show_preview_settings() { core().show_preview_settings(); }

private slots:
    // String-connect targets for the argless page signals (SLOT syntax
    // needs declared slots — the core's typed handlers can't be reached
    // by name).
    void slotQcReportsUpdated() { on_qc_reports_updated(); }
    void slotWellLogPredictionUpdated() { on_well_log_prediction_updated(); }
    void slotSeismicPredictionUpdated() { on_seismic_prediction_updated(); }
    void slotFactorMapsUpdated() { on_factor_maps_updated(); }
    void slotContourDraftsUpdated() { on_contour_drafts_updated(); }
    void slotStratigraphyUpdated() { on_stratigraphy_updated(); }
    void slotWellLogSendToPrep() { on_well_log_send_to_prep(); }
    void slotSeismicSendToMapping() { on_seismic_send_to_mapping(); }
    void slotGenerateDemoMapDraft() { on_generate_demo_map_draft(); }
    void slotHomeNavigation(int hub) { on_home_navigation(hub); }

private:
    // hasattr(page, name) + string-connect to `slot` when present.
    void wire_signal_(QObject* page, int defer_hub,
                      const char* signal_signature,
                      const char* slot_signature);
    void defer_(int hub, QObject* page);

    pwb::qgis_processing::PwbTaskGate* gate_ = nullptr;  // not owned
    std::unique_ptr<JobOwnerRunner> recompute_job_;
    std::unique_ptr<JobOwnerRunner> prepare_job_;
    std::unique_ptr<WorkflowCore> core_;
    WorkflowPageApi pages_;
    WorkflowDialogApi dialogs_;
    WorkflowServiceApi services_;
    CatalogRuntimeApi catalog_;
    PrepareGenerationApi generation_;
    LiveFactorGridApi grids_;
    FactorRecomputeSeams factor_recompute_;
    ui_workers::FactorPrepareSeams prepare_seams_;
    std::function<void(int, QObject*)> defer_page_binding_;
};

}  // namespace pwb::ui_controllers::qt
