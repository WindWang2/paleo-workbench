#pragma once

// UI-10 — Qt shell for visualization_page.py: the display-first 可视化
// page combining the geo-viz hosts.
//
// Widget tree (Python parity): temp banner → top bar (asset combo +
// coordinate relabel toggle) → horizontal splitter [workspace | trace]
// with the summary panel dormant-hidden. The trace panel floats through
// the shared FloatController; the composite center is never registered
// (reparenting native views is the fragile case).
//
// Behavior: signature-gated asset combo refill, cached auto-open file
// probes, engine_preview requests through PreviewRequestController,
// well_log opens through the UI-04 well-log worker (sync fast path only
// when the injected cache seam reports a hit), latest-wins load seq
// guards, and export gating by the active tab's capabilities.

#include <QWidget>

#include <any>
#include <functional>
#include <memory>
#include <optional>
#include <set>
#include <string>
#include <vector>

#include <pwb/job_runtime/qt/job_bridge.hpp>
#include <pwb/ui_seqviz/qt/viz_workspace.hpp>
#include <pwb/ui_seqviz/viz_page_state.hpp>
#include <pwb/ui_workers/well_log_load.hpp>

class QComboBox;
class QLabel;
class QPushButton;
class QSplitter;

namespace pwb::ui_shell {
class FloatController;
class LayoutPersistence;
}  // namespace pwb::ui_shell

namespace pwb::ui_seqviz::qt {

class PreviewRequestController;
class VisualizationSummaryPanel;
class VisualizationTracePanel;

// ---------------------------------------------------------------------------
// Page-level seams beyond the workspace's host surfaces.
// ---------------------------------------------------------------------------
struct VizPageSeams {
    VizWorkspaceSeams workspace;
    VizPageResolveSeams resolve;

    // viz/well_log_load.is_well_log_cached — absent ⇒ every open takes
    // the cold-parse worker path (Python cold-cache parity).
    std::function<bool(const std::string& abs_path)> well_log_cached_fn;

    // start_map_export_job seam — unified-canvas PNG export through the
    // host's map-export worker. Return true when the job was started;
    // false ⇒ the page falls through to the synchronous snapshot path.
    // The callbacks fire on the GUI thread.
    std::function<bool(
        QWidget* widget, const std::string& path,
        std::function<void(const std::string& path)> on_finished,
        std::function<void(const std::string& message)> on_failed,
        std::function<void()> on_cancelled)>
        map_png_export_fn;

    // register_exported_view provenance seam (best-effort; absent ⇒ skip).
    std::function<void(QWidget* widget, const std::string& path,
                       const std::string& format)>
        register_view_fn;

    // default_export_dir — the suggested save dir for file dialogs.
    std::function<std::string()> export_dir_fn;
};

class VisualizationPage : public QWidget {
    Q_OBJECT
public:
    explicit VisualizationPage(
        QWidget* parent,
        ui_data_core::PreviewProvider preview_provider,
        ui_shell::LayoutPersistence* persistence = nullptr);
    ~VisualizationPage() override;

    void set_seams(VizPageSeams seams);
    const VizPageSeams& seams() const { return seams_; }

    // set_project_path — the real *.paleo.json path for export/artifact
    // routing (never a fabricated name).
    void set_project_path(const std::string& path);

    // update_state(resources, prediction_tasks, map_documents, project).
    void update_state(const VizPageProjectSlice& project);

    // open_ref — the public ref-open entry (combo activation, summary
    // selection, reload, auto-open all land here).
    void open_ref(const VizRefSlice& ref);

    // _reload_current — refresh button parity.
    void reload_current();

    // shutdown_workers — release async previews/exports/LAS loads before
    // the shell is replaced.
    bool shutdown_workers(int wait_ms = 3'000);

    // -- Python member surfaces ------------------------------------------
    VisualizationWorkspace* composite_panel() const { return composite_; }
    VisualizationSummaryPanel* summary_panel() const { return summary_; }
    VisualizationTracePanel* trace_panel() const { return trace_; }
    QComboBox* asset_combo() const { return asset_combo_; }
    QPushButton* coord_button() const { return coord_btn_; }
    QSplitter* content_splitter() const { return splitter_; }
    PreviewRequestController* preview_controller() const {
        return preview_controller_;
    }
    const std::optional<VizRefSlice>& current_ref() const {
        return current_ref_;
    }

signals:
    // QMessageBox seams — the host decides presentation.
    void warning_requested(const QString& title, const QString& message);
    void info_requested(const QString& title, const QString& message);

protected:
    void closeEvent(QCloseEvent* event) override;
    bool event(QEvent* event) override;

private:
    void on_asset_combo_changed(int index);
    void on_coord_toggle();
    void sync_export_capabilities();
    void export_current_view(const QString& format_label);
    void begin_export_busy();
    void end_export_busy();

    void open_well_log(const VizRefSlice& ref);
    void apply_well_log_payload(const VizRefSlice& ref,
                                const UiVizPayload& payload);
    void on_well_log_resolved(const VizRefSlice& ref,
                              const ui_workers::VizPayloadSlice& slice,
                              long long seq);
    void on_well_log_failed(const VizRefSlice& ref,
                            const std::string& message);
    void on_well_log_job_released();

    void show_preview_loading();
    void apply_preview_result(
        const ui_data_core::PreviewResult& result);
    void show_preview_error(const QString& message);

    void persist_docked_sizes();
    void make_floatable(const std::string& key, QWidget* panel,
                        const QString& title);

    VizPageSeams seams_;
    VizPageProjectSlice project_;
    std::string project_path_;
    std::optional<VizRefSlice> current_ref_;
    std::optional<VizRefSlice> pending_well_log_ref_;
    std::vector<VizComboEntry> combo_entries_;
    VizRefSignature combo_signature_;
    VizRefSignature probe_signature_;
    std::optional<VizRefSlice> probe_first_ref_;
    long long load_seq_ = 0;
    bool export_busy_ = false;

    ui_workers::WellLogLoadPhasePtr well_log_phase_;

    QLabel* banner_ = nullptr;
    QComboBox* asset_combo_ = nullptr;
    QPushButton* coord_btn_ = nullptr;
    QSplitter* splitter_ = nullptr;
    VisualizationWorkspace* composite_ = nullptr;
    VisualizationSummaryPanel* summary_ = nullptr;
    VisualizationTracePanel* trace_ = nullptr;
    PreviewRequestController* preview_controller_ = nullptr;
    job::qtbridge::JobOwner* well_log_job_ = nullptr;
    job::qtbridge::JobOwner* export_job_ = nullptr;
    ui_shell::LayoutPersistence* persistence_ = nullptr;
    std::unique_ptr<ui_shell::FloatController> float_controller_;
    std::vector<std::pair<std::string, QWidget*>> floatable_;
};

}  // namespace pwb::ui_seqviz::qt
