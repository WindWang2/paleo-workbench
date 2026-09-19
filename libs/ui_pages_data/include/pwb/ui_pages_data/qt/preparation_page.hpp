// UI-06 — preparation_page.py :: PreparationPage Qt shell.
//
// Splitter composition (tasks | preview+well-table | boundary) plus the
// prepare/contour worker orchestration. FactorTaskPanel, FactorPreviewGrid,
// WellTablePanel, BoundaryPanel, OwnedWorkerJob, the prepare scheduler,
// contour drafts and well QC are other slices' components — injected
// seams; the page keeps the guards, enablement and summary strings.
#pragma once

#include <QWidget>

#include <functional>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>

class QLabel;
class QPushButton;
class QSplitter;

namespace pwb::ui_pages_data::qt {

// FactorTaskPanel seam.
class FactorTaskPanelApi : public QWidget {
    Q_OBJECT
public:
    using QWidget::QWidget;
    virtual QString selected_method() const = 0;
    virtual void update_state(const pwb::domain::Json& tasks) = 0;
    virtual QPushButton* generate_btn() = 0;
    virtual QPushButton* contour_draft_btn() = 0;
    virtual QLabel* summary_label() = 0;
Q_SIGNALS:
    void generate_requested(const QString& method);
    void contour_draft_requested();
};

// WellTablePanel seam.
class WellTablePanelApi : public QWidget {
    Q_OBJECT
public:
    using QWidget::QWidget;
    virtual QPushButton* run_qc_btn() = 0;
    virtual void update_from_well_table(void* table) = 0;
};

// FactorPreviewGrid seam.
class FactorPreviewGridApi : public QWidget {
    Q_OBJECT
public:
    using QWidget::QWidget;
    virtual void update_state(const pwb::domain::Json& tasks) = 0;
};

// OwnedWorkerJob seam: is_running / shutdown(wait_ms)→joined / cancel /
// target. The host binds a real job; released→clear is the job's own
// signal into clear_prepare_job / clear_contour_job.
struct WorkerJobApi {
    std::function<bool()> is_running;
    std::function<bool(int wait_ms)> shutdown;
    std::function<void()> cancel;
    std::function<void*()> target;
};

// FactorPrepareProgress seam.
struct PrepareProgressView {
    int generation = 0;
    int clean = 0;
    int dirty = 0;
    int completed = 0;
    int total_tasks = 0;
    std::string phase;
    std::string message;
};

// FactorPrepareBatchResult seam.
struct PrepareResultView {
    int generation = 0;
    int clean_count = 0;
    int executed_count = 0;
    void* payload = nullptr;  // host result, passed to commit fn
};

class PreparationPage : public QWidget {
    Q_OBJECT
public:
    explicit PreparationPage(QWidget* parent = nullptr);

    // Panel seams.
    void set_task_panel(FactorTaskPanelApi* panel);
    void set_well_table_panel(WellTablePanelApi* panel);
    void set_preview_grid(FactorPreviewGridApi* panel);
    void set_boundary_panel(QWidget* panel);

    // Job seams.
    void set_prepare_job(WorkerJobApi job) { prepare_job_ = std::move(job); }
    void set_contour_job(WorkerJobApi job) { contour_job_ = std::move(job); }

    // Domain seams.
    // next/current prepare generation (factor_grid_artifacts).
    void set_generation_fns(std::function<int()> next_fn,
                            std::function<int()> current_fn);
    // build_prepare_snapshot → task count for the "制备中…" line.
    void set_snapshot_task_count_fn(
        std::function<int(void* project, const std::string& method,
                          int generation)> fn);
    // Start the prepare worker (host runs FactorPrepareWorker off-thread
    // and invokes exactly one terminal callback on the UI thread).
    void set_prepare_worker_fn(
        std::function<void(void* project, const std::string& method,
                           int generation,
                           std::function<void(const PrepareProgressView&)>,
                           std::function<void(const PrepareResultView&)>,
                           std::function<void(const QString&)>,
                           std::function<void()>)> fn);
    // commit_prepare_batch_result → number of discarded stale results.
    void set_commit_prepare_fn(
        std::function<int(void* project, const PrepareResultView&,
                          int expected_generation)> fn);
    // contour worker start (terminal: completed → drafts payload count,
    // failed → message).
    void set_contour_worker_fn(
        std::function<void(void* project,
                           std::function<void(void* result)>,
                           std::function<void(const QString&)>)> fn);
    // commit_contour_drafts → drafts count (0 → "没有可提取" summary).
    void set_commit_contour_fn(
        std::function<int(void* project, void* result)> fn);
    // Display-table resolution + project factor_map_tasks accessor.
    void set_display_well_table_fn(
        std::function<void*(void* project,
                            const pwb::domain::Json& tasks)> fn);
    void set_factor_map_tasks_fn(
        std::function<pwb::domain::Json(void* project)> fn);
    // Well QC: returns the info-message body on success; throws are
    // reported via the error string out-param semantics (error → warning
    // box). Null fn → "请先打开或绑定工程。" path stays native.
    void set_run_well_qc_fn(
        std::function<bool(void* project, std::string* info,
                           std::string* error)> fn);

    void set_project(void* project);
    void update_state(const pwb::domain::Json& tasks);

    bool is_prepare_running() const;
    bool is_contour_running() const;
    bool shutdown_workers(int wait_ms = 3000);

    FactorTaskPanelApi* task_panel() { return task_panel_; }
    WellTablePanelApi* well_table_panel() { return well_table_panel_; }
    FactorPreviewGridApi* preview_grid() { return preview_grid_; }
    QWidget* boundary_panel() { return boundary_panel_; }

Q_SIGNALS:
    void factor_maps_updated();
    void contour_drafts_updated();
    void generate_requested(const QString& method);

private:
    void set_generate_enabled(bool enabled);
    void refresh_well_table_view();
    void on_run_well_qc();
    void on_generate_requested(const QString& method);
    void start_prepare_worker(const std::string& method);
    void clear_prepare_job();
    void on_prepare_progress(const PrepareProgressView& update);
    void on_prepare_completed(const PrepareResultView& result);
    void on_prepare_failed(const QString& message);
    void on_prepare_cancelled();
    void on_contour_draft_requested();
    void on_contour_completed(void* result);
    void on_contour_failed(const QString& message);
    void clear_contour_job();

    void* project_ = nullptr;
    pwb::domain::Json tasks_ = pwb::domain::Json::array();
    int prepare_generation_ = 0;

    FactorTaskPanelApi* task_panel_ = nullptr;
    WellTablePanelApi* well_table_panel_ = nullptr;
    FactorPreviewGridApi* preview_grid_ = nullptr;
    QWidget* boundary_panel_ = nullptr;
    QSplitter* content_;

    WorkerJobApi prepare_job_;
    WorkerJobApi contour_job_;
    std::function<int()> next_generation_fn_;
    std::function<int()> current_generation_fn_;
    std::function<int(void*, const std::string&, int)>
        snapshot_task_count_fn_;
    std::function<void(void*, const std::string&, int,
                       std::function<void(const PrepareProgressView&)>,
                       std::function<void(const PrepareResultView&)>,
                       std::function<void(const QString&)>,
                       std::function<void()>)>
        prepare_worker_fn_;
    std::function<int(void*, const PrepareResultView&, int)>
        commit_prepare_fn_;
    std::function<void(void*, std::function<void(void*)>,
                       std::function<void(const QString&)>)>
        contour_worker_fn_;
    std::function<int(void*, void*)> commit_contour_fn_;
    std::function<void*(void*, const pwb::domain::Json&)>
        display_well_table_fn_;
    std::function<pwb::domain::Json(void*)> factor_map_tasks_fn_;
    std::function<bool(void*, std::string*, std::string*)> run_well_qc_fn_;
};

}  // namespace pwb::ui_pages_data::qt
