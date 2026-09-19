#include <pwb/ui_controllers/qt/workflow_controller.hpp>

#include <QMessageBox>
#include <QTimer>
#include <QWidget>

#include <pwb/ui_controllers/qt/job_owner_runner.hpp>

namespace pwb::ui_controllers::qt {

WorkflowController::WorkflowController(job::JobScheduler& scheduler,
                                       QObject* parent)
    : QObject(parent), scheduler_(scheduler) {
    recompute_job_ = std::make_unique<JobOwnerRunner>(scheduler_, this);
    prepare_job_ = std::make_unique<JobOwnerRunner>(scheduler_, this);
    // The worker progress hop: QMetaObject::invokeMethod queued onto this
    // object's thread (QueuedConnection parity — a QTimer(0) post is the
    // same contract and needs no receiver object).
    pages_.post_to_gui = [](std::function<void()> fn) {
        QTimer::singleShot(0, [fn = std::move(fn)]() mutable { fn(); });
    };
}

WorkflowController::~WorkflowController() = default;

WorkflowCore& WorkflowController::core() {
    if (core_ == nullptr) {
        core_ = std::make_unique<WorkflowCore>(
            pages_, dialogs_, services_, catalog_, generation_, grids_,
            factor_recompute_, prepare_seams_, recompute_job_.get(),
            prepare_job_.get());
    }
    return *core_;
}

void WorkflowController::bind_dialogs(QWidget* parent) {
    dialogs_.info = [parent](const std::string& title,
                             const std::string& text) {
        QMessageBox::information(parent, QString::fromStdString(title),
                                 QString::fromStdString(text));
    };
    dialogs_.warning = [parent](const std::string& title,
                                const std::string& text) {
        QMessageBox::warning(parent, QString::fromStdString(title),
                             QString::fromStdString(text));
    };
    dialogs_.dirty_confirm =
        [parent](const std::string& title,
                 const std::string& text) -> WorkflowDialogApi::DirtyChoice {
        const auto reply = QMessageBox::question(
            parent, QString::fromStdString(title),
            QString::fromStdString(text),
            QMessageBox::StandardButton::Save |
                QMessageBox::StandardButton::Discard |
                QMessageBox::StandardButton::Cancel,
            QMessageBox::StandardButton::Save);
        switch (reply) {
            case QMessageBox::StandardButton::Save:
                return WorkflowDialogApi::DirtyChoice::save;
            case QMessageBox::StandardButton::Discard:
                return WorkflowDialogApi::DirtyChoice::discard;
            default:
                return WorkflowDialogApi::DirtyChoice::cancel;
        }
    };
    // preview_settings_editor stays an integration seam (the ported
    // PreviewSettingsDialog widget binds it).
}

// ---------------------------------------------------------------------------
// wire_* — hasattr + string-connect parity
// ---------------------------------------------------------------------------

void WorkflowController::defer_(int hub, QObject* page) {
    if (defer_page_binding_) defer_page_binding_(hub, page);
}

void WorkflowController::wire_signal_(QObject* page, int defer_hub,
                                      const char* signal_signature,
                                      const char* slot_signature) {
    if (page == nullptr) return;
    if (defer_hub >= 0) defer_(defer_hub, page);
    // SIGNAL() prepends the "2" flag char (qFlagLocation) — strip it
    // before the metaobject lookup or the hasattr parity check always
    // misses and nothing ever connects.
    const char* raw = signal_signature;
    if (raw[0] == '2' || raw[0] == '1' || raw[0] == '0') ++raw;
    const QByteArray signal_name = QMetaObject::normalizedSignature(raw);
    if (page->metaObject()->indexOfSignal(signal_name.constData()) < 0) {
        return;  // hasattr(..., None) parity — no surface, no wire.
    }
    QObject::connect(page, signal_signature, this, slot_signature);
}

void WorkflowController::wire_home_page(QObject* page) {
    wire_signal_(page, -1, SIGNAL(navigation_requested(int)),
                 SLOT(slotHomeNavigation(int)));
}

void WorkflowController::wire_data_visualization_jump(QObject* page) {
    // open_in_* carry payloads — bound by the integrator via core()
    // (typed refs aren't string-connectable without a metatype).
    (void)page;
}

void WorkflowController::wire_mapping_page(QObject* page) {
    wire_signal_(page, ui_shell::kPageIndexMapping,
                 SIGNAL(generate_demo_draft_requested()),
                 SLOT(slotGenerateDemoMapDraft()));
    wire_signal_(page, -1, SIGNAL(contour_drafts_updated()),
                 SLOT(slotContourDraftsUpdated()));
}

void WorkflowController::wire_preparation_page(QObject* page) {
    wire_signal_(page, ui_shell::kPageIndexMapping,
                 SIGNAL(factor_maps_updated()),
                 SLOT(slotFactorMapsUpdated()));
    wire_signal_(page, -1, SIGNAL(contour_drafts_updated()),
                 SLOT(slotContourDraftsUpdated()));
}

void WorkflowController::wire_sequence_page(QObject* page) {
    wire_signal_(page, ui_shell::kPageIndexWell,
                 SIGNAL(stratigraphy_updated()),
                 SLOT(slotStratigraphyUpdated()));
}

void WorkflowController::wire_seismic_page(QObject* page) {
    wire_signal_(page, ui_shell::kPageIndexSeismic,
                 SIGNAL(prediction_updated()),
                 SLOT(slotSeismicPredictionUpdated()));
    wire_signal_(page, -1, SIGNAL(send_to_mapping_requested()),
                 SLOT(slotSeismicSendToMapping()));
}

void WorkflowController::wire_well_log_page(QObject* page) {
    wire_signal_(page, ui_shell::kPageIndexWell,
                 SIGNAL(prediction_updated()),
                 SLOT(slotWellLogPredictionUpdated()));
    wire_signal_(page, -1, SIGNAL(send_to_preparation_requested()),
                 SLOT(slotWellLogSendToPrep()));
    // well_log_import_requested(paths) carries a payload — the integrator
    // calls core().on_well_log_import_requested directly.
}

void WorkflowController::wire_geomodel_page(QObject* page) {
    // Cross-page well sync is mediated by the shared SelectionContext
    // (#1029) — only the deferred binding rides here.
    defer_(ui_shell::kPageIndexSeismic, page);
}

void WorkflowController::wire_review_page(QObject* page) {
    wire_signal_(page, ui_shell::kPageIndexMapping,
                 SIGNAL(reports_updated()), SLOT(slotQcReportsUpdated()));
}

}  // namespace pwb::ui_controllers::qt
