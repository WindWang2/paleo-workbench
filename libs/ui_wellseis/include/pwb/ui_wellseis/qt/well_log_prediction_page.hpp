#pragma once

// UI-09 — WellLogPredictionPage Qt shell (well_log_prediction_page.py).
// LAS-bound well + lithology/facies tracks + export: source combo row,
// splitter (tasks | canvas | evidence), online run/demo guard chains,
// id-anchored task selection, persisted-failure replay, redacted run
// diagnostics, and the engine-PNG / legacy-vector export gate. Catalog,
// model registry, workers and the canvas engine are injected hooks.

#include <cstdint>
#include <functional>
#include <optional>
#include <string>
#include <vector>

#include <QString>
#include <QWidget>

#include <pwb/domain/json.hpp>
#include <pwb/ui_wellseis/resource_sources.hpp>
#include <pwb/ui_wellseis/slices.hpp>

class QComboBox;
class QSplitter;

namespace pwb::ui_wellseis::qt {

class PredictionEvidencePanel;
class PredictionTaskPanel;
class WellLogCanvasPanel;

// Catalog/inference seams (Python get_catalog_service +
// ensure_geoviz_online_model + resolve_inputs_for_model +
// InferenceWorker + materialize_prediction_task + record_export). Empty
// hooks map to the Python "service is None" guards.
struct WellLogPredictionHooks {
    // ensure_geoviz_online_model + the five online run parameters, read
    // together like Python; error text -> "无法准备线上测井预测: {e}".
    struct OnlineRoute {
        std::string model_version_id;
        std::string endpoint;
        std::string remote_model_version_id;
        std::string wait_timeout_seconds;
        std::string request_timeout_seconds;
        std::string poll_timeout_seconds;
    };
    std::function<bool()> catalog_connected;
    std::function<std::optional<OnlineRoute>(std::string& error)>
        online_route;
    std::function<std::optional<std::string>(std::string& error)>
        demo_model_id;
    // resolve_inputs_for_model(strict=True); error text on contract fail.
    std::function<std::optional<std::string>(
        const std::string& model_version_id,
        const std::optional<std::string>& well_log_resource_id,
        std::vector<std::string>& input_ids)>
        resolve_inputs;
    // resolve_prediction_postprocess_inputs — online workflow only.
    std::function<void(std::vector<std::string>& input_ids)>
        resolve_postprocess_inputs;
    std::function<bool()> is_running;
    // start_inference + InferenceWorker — returns the created run slice
    // (the 推断中 diagnostic needs run.id like the Python path); the host
    // re-enters via on_inference_completed/on_inference_failed later.
    std::function<RunSlice(const std::string& model_version_id,
                           const std::vector<std::string>& input_ids,
                           domain::Json parameters)>
        start_run;
    // materialize_prediction_task + append + link_run_to_domain_task.
    std::function<PredictionTaskSlice(const domain::Json& run,
                                      const domain::Json& result)>
        materialize_task;
    // service.list_runs() for the persisted-failure replay.
    std::function<std::vector<RunSlice>()> list_runs;
    // OwnedWorkerJob.shutdown(wait_ms).
    std::function<bool(int)> shutdown;
    // record_export / register_export_output — best-effort provenance.
    std::function<void(const std::string& path, const std::string& fmt,
                       const std::vector<std::string>& source_task_ids)>
        register_export;
    // default_export_dir(project_path) anchor.
    std::function<std::string()> default_export_dir;
    // Dialog seams — tests inject fixed answers, production uses
    // QFileDialog (installed by default when nullopt).
    std::function<QString(const QString& caption, const QString& start,
                          const QString& filter)>
        save_file_name;
    std::function<QStringList(const QString& caption, const QString& filter)>
        open_file_names;
};

class WellLogPredictionPage : public QWidget {
    Q_OBJECT
public:
    explicit WellLogPredictionPage(QWidget* parent = nullptr);

    void set_hooks(WellLogPredictionHooks hooks);
    void set_project(const ProjectSlice* project);
    void set_project_path(const QString& path);

    void update_state(const std::vector<PredictionTaskSlice>& tasks,
                      const ProjectSlice* project = nullptr);
    bool shutdown_workers(int wait_ms = 3000);

    // Data-management source-well selection.
    [[nodiscard]] std::optional<std::string> selected_well_resource_id()
        const;
    bool select_well_resource(const std::string& resource_id);
    // Cross-page seam: pick the task whose name matches (3D-page sync).
    bool set_selected_well(const std::string& well_name);
    void set_source_import_status(const QString& text);

    [[nodiscard]] PredictionTaskPanel* task_panel() const;
    [[nodiscard]] WellLogCanvasPanel* canvas_panel() const;
    [[nodiscard]] PredictionEvidencePanel* evidence_panel() const;

public slots:
    void on_run();
    void on_demo();
    void on_export(const QString& format_label);
    void on_inference_completed(const domain::Json& payload);
    void on_inference_failed(const std::string& text);

signals:
    void prediction_updated();
    void send_to_preparation_requested();
    void well_log_import_requested(const QStringList& paths);

protected:
    void closeEvent(QCloseEvent* event) override;

private:
    const PredictionTaskSlice* current_task() const;
    const ResourceSlice* selected_well_resource() const;
    void sync_well_sources();
    void on_task_selected(int index);
    void on_canvas_ready(bool ready);
    void on_import_well_logs();
    void restore_latest_failed_online_run(const std::string& resource_id);
    void write_run_diagnostic(const RunSlice* run, const std::string& status,
                              const std::string& error = {});
    void start_inference(const std::string& model_version_id,
                         const std::string& workflow,
                         const std::string& name_prefix, bool demo,
                         const std::optional<std::string>& resource_id,
                         const domain::Json& extra_parameters);

    WellLogPredictionHooks hooks_;
    const ProjectSlice* project_ = nullptr;
    QString project_path_;
    std::vector<PredictionTaskSlice> tasks_;
    std::optional<int> selected_index_;
    std::optional<std::string> selected_task_id_;
    std::optional<std::string> selected_resource_id_;
    SourceSignature well_source_signature_;
    std::uint64_t session_token_ = 0;
    bool inference_active_ = false;

    QComboBox* well_source_combo_ = nullptr;
    PredictionTaskPanel* task_panel_ = nullptr;
    WellLogCanvasPanel* canvas_panel_ = nullptr;
    PredictionEvidencePanel* evidence_panel_ = nullptr;
    QSplitter* splitter_ = nullptr;
};

}  // namespace pwb::ui_wellseis::qt
