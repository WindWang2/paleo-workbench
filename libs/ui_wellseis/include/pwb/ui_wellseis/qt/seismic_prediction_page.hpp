#pragma once

// UI-09 — SeismicPredictionPage Qt shell (seismic_prediction_page.py).
// Reference-style seismic workbench: SeismicContextToolbar + horizontal
// splitter (attribute | view | control). The page owns task selection,
// the SEG-Y source combo lifecycle, run/demo guard chains + warnings,
// the inference busy state, and session-token staleness on completed /
// failed payloads. Catalog, model registry, workers and the GL view are
// injected hooks — never reached directly.

#include <cstdint>
#include <functional>
#include <optional>
#include <string>
#include <vector>

#include <QWidget>

#include <pwb/domain/json.hpp>
#include <pwb/ui_wellseis/slices.hpp>

class QSplitter;

namespace pwb::ui_wellseis::qt {

class SeismicAttributePanel;
class SeismicContextToolbar;
class SeismicControlPanel;
class SeismicViewPanel;

// Inference/catalog seams the Python page pulls from get_catalog_service
// + start_inference + InferenceWorker + materialize_prediction_task.
// The host binds the real implementations (ui_workers / catalog layer);
// empty hooks map to the Python "service is None" guards.
struct SeismicPredictionHooks {
    // get_catalog_service() is not None.
    std::function<bool()> catalog_connected;
    // ensure_default_models + find_production_model(CAPABILITY_FACIES);
    // nullopt -> the "未配置生产模型" warning.
    std::function<std::optional<std::string>()> production_model_id;
    // get_model_version(MODEL_ID_DEMO, "1"); nullopt -> "演示模型未注册".
    std::function<std::optional<std::string>()> demo_model_id;
    // resolve_inputs_for_model(strict=True); returns the contract-error
    // text or nullopt with `input_ids` filled.
    std::function<std::optional<std::string>(
        const std::string& model_version_id,
        const std::optional<std::string>& seismic_resource_id,
        std::vector<std::string>& input_ids)>
        resolve_inputs;
    // OwnedWorkerJob.is_running (#850-7 busy guard).
    std::function<bool()> is_running;
    // start_inference + InferenceWorker; the host re-enters the page via
    // on_inference_completed/on_inference_failed when the worker ends.
    std::function<void(const std::string& model_version_id,
                       const std::vector<std::string>& input_ids,
                       domain::Json parameters)>
        start_run;
    // materialize_prediction_task + prediction_tasks.append +
    // link_run_to_domain_task — returns the new task slice (host sets
    // model_metadata.link_failed when the bridge throws).
    std::function<PredictionTaskSlice(const domain::Json& run,
                                      const domain::Json& result)>
        materialize_task;
    // OwnedWorkerJob.shutdown(wait_ms).
    std::function<bool(int)> shutdown;
};

class SeismicPredictionPage : public QWidget {
    Q_OBJECT
public:
    explicit SeismicPredictionPage(QWidget* parent = nullptr);

    void set_hooks(SeismicPredictionHooks hooks);
    void set_project(const ProjectSlice* project);

    // update_state parity — project may be nullptr (keeps current).
    void update_state(const std::vector<PredictionTaskSlice>& tasks,
                      const ProjectSlice* project = nullptr);
    bool shutdown_workers(int wait_ms = 3000);

    // SEG-Y source selection (select_seismic_resource parity).
    [[nodiscard]] std::optional<std::string>
    selected_seismic_resource_id() const;
    bool select_seismic_resource(const std::string& resource_id);

    // Panel access for the host's engine wiring + tests.
    [[nodiscard]] SeismicContextToolbar* context_toolbar() const;
    [[nodiscard]] SeismicAttributePanel* attribute_panel() const;
    [[nodiscard]] SeismicViewPanel* view_panel() const;
    [[nodiscard]] SeismicControlPanel* control_panel() const;

public slots:
    // Run/demo entry points (context toolbar signals land here).
    void on_run();
    void on_demo();
    // Host worker re-entry — the session-token check happens inside.
    void on_inference_completed(const domain::Json& payload);
    void on_inference_failed(const std::string& text);

signals:
    void prediction_updated();
    void send_to_mapping_requested();

protected:
    void closeEvent(QCloseEvent* event) override;

private:
    const PredictionTaskSlice* current_task() const;
    const ResourceSlice* selected_seismic_resource() const;
    void sync_seismic_sources();
    void on_seismic_source_changed(int index);
    void on_attribute(const QString& label);
    void on_view_ready(bool enabled);
    void sync_workbench_context(const PredictionTaskSlice* task);
    void start_inference(const std::string& model_version_id,
                         const std::string& workflow,
                         const std::string& name_prefix, bool demo,
                         const std::optional<std::string>& resource_id);

    SeismicPredictionHooks hooks_;
    const ProjectSlice* project_ = nullptr;
    std::vector<PredictionTaskSlice> tasks_;
    SeismicContextToolbar* context_toolbar_ = nullptr;
    SeismicAttributePanel* attribute_panel_ = nullptr;
    SeismicViewPanel* view_panel_ = nullptr;
    SeismicControlPanel* control_panel_ = nullptr;
    QSplitter* splitter_ = nullptr;
    // Session-token parity: set_project()/shutdown_workers() invalidate
    // in-flight completions so a stale worker cannot publish into the
    // rebound page (_active_inference_context).
    std::uint64_t session_token_ = 0;
    bool inference_active_ = false;
    std::optional<std::string> selected_resource_id_;
    bool showing_selected_source_ = false;
};

}  // namespace pwb::ui_wellseis::qt
