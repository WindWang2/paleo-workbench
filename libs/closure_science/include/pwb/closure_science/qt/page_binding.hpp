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

#include <pwb/domain/json.hpp>

#include <QObject>
#include <QPointer>

#include <filesystem>
#include <functional>
#include <memory>
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
