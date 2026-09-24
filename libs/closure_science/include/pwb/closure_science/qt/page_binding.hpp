// pwb::closure_science::qt — production binding for the prediction pages
// (line 03). This is the real counterpart of Python app_shell's catalog /
// inference-worker wiring for WellLogPredictionPage + SeismicPredictionPage:
//
//   catalog_connected     — a CatalogServiceCore over the current project's
//                           canonical store (opened lazily, cached, re-opened
//                           on project switch, released on close);
//   production_model_id   — catalog::find_production_model(facies);
//   demo_model_id         — ensure_default_models (idempotent seed);
//   resolve_inputs        — schema-driven resolution (input_contract core);
//   start_run             — DataRun + provider execution on a worker thread
//                           (demo = frozen synthetic; tiled_onnx = real ONNX
//                           Runtime through the native task runtime), the
//                           result persisted as a DERIVED version with run
//                           linkage, re-entry via the page's
//                           on_inference_completed/failed slots;
//   materialize_task      — PredictionTask dict + journal record;
//   list_runs / register_export / default_export_dir — the page's
//                           diagnostics + provenance seams.
//
// Honesty: no fake provider and no fabricated completion. A missing model,
// missing executor or failed contract surfaces through the same guard text
// paths the Python product uses; an unavailable provider name is the
// explicit "Unknown model provider" error.
#pragma once

#include <pwb/closure_science/run_spec_service.hpp>
#include <pwb/domain/json.hpp>
#include <pwb/prediction/run_spec.hpp>

#include <QObject>
#include <QPointer>

#include <filesystem>
#include <functional>
#include <memory>
#include <string>
#include <vector>

namespace pwb::ui_wellseis::qt {
class SeismicPredictionPage;
class WellLogPredictionPage;
}

namespace pwb::closure_science::qt {

using domain::Json;

class SciencePageBinding : public QObject {
    Q_OBJECT
public:
    struct Config {
        // The current .paleo.json project file (empty = none open). Read
        // lazily on every hook: a project switch rebinds the catalog +
        // journal and invalidates in-flight completions by identity token.
        std::function<std::filesystem::path()> project_file;
        // Optional GUI-thread publish seam: a materialized prediction task
        // is offered here right after the journal record, so the host can
        // land it in the PROJECT document (the section ws2/ws3 overlays
        // and the pages' update_state read). The worker thread never
        // touches the host's live project store — this runs on the GUI
        // thread inside the page's materialize_task hook.
        std::function<domain::DataError(const Json& task)> publish_task;
    };

    SciencePageBinding(Config config, QObject* parent = nullptr);
    ~SciencePageBinding() override;

    SciencePageBinding(const SciencePageBinding&) = delete;
    SciencePageBinding& operator=(const SciencePageBinding&) = delete;

    // Installs the production hooks into both prediction pages.
    void attach(ui_wellseis::qt::WellLogPredictionPage& well_page,
                ui_wellseis::qt::SeismicPredictionPage& seismic_page);

    // Bounded worker shutdown (page shutdown_workers parity).
    bool shutdown_workers(int wait_ms);

    // Late-installed publish seam (the app assembles the binding before
    // the project store is reachable; this wires Config::publish_task).
    void set_publish_task(
        std::function<domain::DataError(const Json& task)> publish_task);

    // Cooperative cancel of the in-flight inference run (the provider
    // stops at the next tile-group seam; a cancelled run is terminal and
    // never reported as success). Returns true when a run was active.
    bool request_cancel();

    // The RunSpec path (predict.run): preflight -> start_inference ->
    // worker, single-flight with the page runs (worker_active_ guard).
    // *completion_page* receives on_inference_completed/failed (queued,
    // project-token guarded) — pass the seismic page for production runs.
    struct SpecRunResult {
        bool started = false;
        std::vector<std::string> errors;  // preflight/start failures
        std::string run_id;
    };
    SpecRunResult start_spec_run(
        const pwb::prediction::PredictionRunSpec& spec,
        QObject* completion_page);

    // True while a run (page-started or spec-started) is in flight.
    [[nodiscard]] bool is_running() const;

    // Selection-dialog data (stable ids; try-locked against the document —
    // during an in-flight run these fill *error instead of freezing the
    // GUI thread).
    [[nodiscard]] std::vector<WellCandidate> well_candidates(
        const std::optional<std::string>& model_version_id = std::nullopt,
        std::string* error = nullptr);
    [[nodiscard]] std::vector<ModelCandidate> model_candidates(
        std::string* error = nullptr);

    // The current project's recorded tasks (journal restore on reopen);
    // empty when the journal is absent. A corrupt journal is reported in
    // the error channel, never silently dropped.
    [[nodiscard]] std::vector<Json> restored_tasks() const;

private:
    struct CatalogContext;
    class Impl;
    std::unique_ptr<Impl> impl_;
};

// Convenience: create the binding (parent-owned) and attach it to the two
// prediction pages. Returns the raw pointer (ownership with *parent).
[[nodiscard]] SciencePageBinding* attach_prediction_pages(
    ui_wellseis::qt::WellLogPredictionPage& well_page,
    ui_wellseis::qt::SeismicPredictionPage& seismic_page,
    std::function<std::filesystem::path()> project_file,
    QObject* parent = nullptr);

}  // namespace pwb::closure_science::qt
