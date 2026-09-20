// UI-06 — preparation_page.cpp: PreparationPage Qt shell implementation.
//
// Port of paleo_workbench/ui/pages/preparation_page.py's page-level
// substance: the splitter composition, the prepare/contour worker
// lifecycle guards (generation guard, job-target guard, in-flight
// supersede on project switch) and the frozen summary strings from
// preparation_model. Panels and scientific backends stay injected seams —
// the closure installer binds the real ui_seqviz/ui_wellseis/
// ui_pages_mapedit panels and the ui_workers prepare/contour cores.

#include <pwb/ui_pages_data/qt/preparation_page.hpp>

#include <QLabel>
#include <QMessageBox>
#include <QPushButton>
#include <QSplitter>
#include <QVBoxLayout>
#include <QWidget>

#include <pwb/ui_pages_data/preparation_model.hpp>

namespace pwb::ui_pages_data::qt {
namespace {

// Honest not-installed panel surface — never a fake interactive page.
QLabel* placeholder_label(const QString& text, QWidget* parent) {
    auto* label = new QLabel(text, parent);
    label->setAlignment(Qt::AlignCenter);
    label->setObjectName(QStringLiteral("PreparationPanelPlaceholder"));
    return label;
}

}  // namespace

PreparationPage::PreparationPage(QWidget* parent) : QWidget(parent) {
    setObjectName(QStringLiteral("PreparationPage"));

    auto* root = new QVBoxLayout(this);
    root->setContentsMargins(0, 0, 0, 0);
    content_ = new QSplitter(Qt::Horizontal, this);
    content_->setObjectName(QStringLiteral("PreparationSplitter"));
    // Placeholders are replaced by set_task_panel / set_well_table_panel /
    // set_preview_grid / set_boundary_panel at install time.
    content_->addWidget(
        placeholder_label(QStringLiteral("制备面板未注入"), this));
    auto* center = new QSplitter(Qt::Vertical, content_);
    center->addWidget(
        placeholder_label(QStringLiteral("预览网格未注入"), this));
    center->addWidget(
        placeholder_label(QStringLiteral("井表面板未注入"), this));
    center->setSizes({240, 360});
    content_->addWidget(center);
    content_->addWidget(
        placeholder_label(QStringLiteral("边界面板未注入"), this));
    content_->setSizes({300, 620, 280});
    root->addWidget(content_, 1);
}

// -- panel seams ---------------------------------------------------------------

void PreparationPage::set_task_panel(FactorTaskPanelApi* panel) {
    if (panel == task_panel_) return;
    if (task_panel_ != nullptr) {
        disconnect(task_panel_, nullptr, this, nullptr);
    }
    task_panel_ = panel;
    if (task_panel_ != nullptr) {
        content_->replaceWidget(0, task_panel_);
        connect(task_panel_, &FactorTaskPanelApi::generate_requested, this,
                &PreparationPage::on_generate_requested);
        connect(task_panel_, &FactorTaskPanelApi::contour_draft_requested,
                this, &PreparationPage::on_contour_draft_requested);
        if (task_panel_->generate_btn() != nullptr &&
            task_panel_->contour_draft_btn() != nullptr) {
            QWidget::setTabOrder(task_panel_->generate_btn(),
                                 task_panel_->contour_draft_btn());
        }
        task_panel_->setVisible(true);
    }
}

void PreparationPage::set_well_table_panel(WellTablePanelApi* panel) {
    if (panel == well_table_panel_) return;
    if (well_table_panel_ != nullptr) {
        disconnect(well_table_panel_, nullptr, this, nullptr);
    }
    well_table_panel_ = panel;
    if (well_table_panel_ != nullptr) {
        // Center splitter: preview grid (index 0) above the well table.
        auto* center = qobject_cast<QSplitter*>(content_->widget(1));
        if (center != nullptr) center->replaceWidget(1, well_table_panel_);
        if (well_table_panel_->run_qc_btn() != nullptr) {
            connect(well_table_panel_->run_qc_btn(), &QPushButton::clicked,
                    this, &PreparationPage::on_run_well_qc);
        }
        well_table_panel_->setVisible(true);
    }
}

void PreparationPage::set_preview_grid(FactorPreviewGridApi* panel) {
    if (panel == preview_grid_) return;
    preview_grid_ = panel;
    if (preview_grid_ != nullptr) {
        auto* center = qobject_cast<QSplitter*>(content_->widget(1));
        if (center != nullptr) center->replaceWidget(0, preview_grid_);
        preview_grid_->setVisible(true);
    }
}

void PreparationPage::set_boundary_panel(QWidget* panel) {
    if (panel == boundary_panel_) return;
    boundary_panel_ = panel;
    if (boundary_panel_ != nullptr) {
        content_->replaceWidget(2, boundary_panel_);
        boundary_panel_->setVisible(true);
    }
}

// -- domain seams ---------------------------------------------------------------

void PreparationPage::set_generation_fns(std::function<int()> next_fn,
                                          std::function<int()> current_fn) {
    next_generation_fn_ = std::move(next_fn);
    current_generation_fn_ = std::move(current_fn);
}

void PreparationPage::set_snapshot_task_count_fn(
    std::function<int(void*, const std::string&, int)> fn) {
    snapshot_task_count_fn_ = std::move(fn);
}

void PreparationPage::set_prepare_worker_fn(
    std::function<void(void*, const std::string&, int,
                       std::function<void(const PrepareProgressView&)>,
                       std::function<void(const PrepareResultView&)>,
                       std::function<void(const QString&)>,
                       std::function<void()>)>
        fn) {
    prepare_worker_fn_ = std::move(fn);
}

void PreparationPage::set_commit_prepare_fn(
    std::function<int(void*, const PrepareResultView&, int)> fn) {
    commit_prepare_fn_ = std::move(fn);
}

void PreparationPage::set_contour_worker_fn(
    std::function<void(void*, std::function<void(void*)>,
                       std::function<void(const QString&)>)>
        fn) {
    contour_worker_fn_ = std::move(fn);
}

void PreparationPage::set_commit_contour_fn(
    std::function<int(void*, void*)> fn) {
    commit_contour_fn_ = std::move(fn);
}

void PreparationPage::set_display_well_table_fn(
    std::function<void*(void*, const domain::Json&)> fn) {
    display_well_table_fn_ = std::move(fn);
}

void PreparationPage::set_factor_map_tasks_fn(
    std::function<domain::Json(void*)> fn) {
    factor_map_tasks_fn_ = std::move(fn);
}

void PreparationPage::set_run_well_qc_fn(
    std::function<bool(void*, std::string*, std::string*)> fn) {
    run_well_qc_fn_ = std::move(fn);
}

// -- project / state ------------------------------------------------------------

void PreparationPage::set_project(void* project) {
    // Project switch supersedes any in-flight prepare generation.
    if (project != project_ && is_prepare_running()) {
        if (next_generation_fn_) {
            prepare_generation_ = next_generation_fn_();
        }
        if (prepare_job_.cancel) {
            prepare_job_.cancel();
        }
    }
    project_ = project;
    refresh_well_table_view();
}

void PreparationPage::update_state(const domain::Json& tasks) {
    tasks_ = tasks.is_array() ? tasks : domain::Json::array();
    if (task_panel_ != nullptr) {
        task_panel_->update_state(tasks_);
    }
    if (preview_grid_ != nullptr) {
        preview_grid_->update_state(tasks_);
    }
    refresh_well_table_view();
}

bool PreparationPage::is_prepare_running() const {
    return prepare_job_.is_running != nullptr && prepare_job_.is_running();
}

bool PreparationPage::is_contour_running() const {
    return contour_job_.is_running != nullptr && contour_job_.is_running();
}

bool PreparationPage::shutdown_workers(int wait_ms) {
    // A seam with no bound job is trivially joined (Python
    // OwnedWorkerJob.shutdown parity: nothing to join → True).
    const bool contour_joined = contour_job_.shutdown == nullptr ||
                                contour_job_.shutdown(wait_ms);
    const bool prepare_joined = prepare_job_.shutdown == nullptr ||
                                prepare_job_.shutdown(wait_ms);
    set_generate_enabled(true);
    return contour_joined && prepare_joined;
}

// -- internal helpers ------------------------------------------------------------

void PreparationPage::set_generate_enabled(bool enabled) {
    if (task_panel_ != nullptr) {
        if (auto* btn = task_panel_->generate_btn(); btn != nullptr) {
            btn->setEnabled(enabled);
        }
        if (auto* btn = task_panel_->contour_draft_btn(); btn != nullptr) {
            btn->setEnabled(enabled);
        }
    }
    if (well_table_panel_ != nullptr) {
        if (auto* btn = well_table_panel_->run_qc_btn(); btn != nullptr) {
            btn->setEnabled(enabled);
        }
    }
}

void PreparationPage::refresh_well_table_view() {
    if (well_table_panel_ == nullptr) return;
    void* table = nullptr;
    if (project_ != nullptr && display_well_table_fn_) {
        table = display_well_table_fn_(project_, tasks_);
    }
    well_table_panel_->update_from_well_table(table);
}

int PreparationPage::current_generation() const {
    return current_generation_fn_ ? current_generation_fn_()
                                  : prepare_generation_;
}

void* PreparationPage::prepare_job_target() const {
    return prepare_job_.target != nullptr ? prepare_job_.target() : nullptr;
}

void* PreparationPage::contour_job_target() const {
    return contour_job_.target != nullptr ? contour_job_.target() : nullptr;
}

// -- well QC -----------------------------------------------------------------------

void PreparationPage::on_run_well_qc() {
    if (project_ == nullptr) {
        QMessageBox::information(this, QStringLiteral("井点 QC"),
                                 QStringLiteral("请先打开或绑定工程。"));
        return;
    }
    if (!run_well_qc_fn_) {
        QMessageBox::warning(this, QStringLiteral("井点 QC 失败"),
                             QStringLiteral("QC 服务未接入"));
        return;
    }
    std::string info;
    std::string error;
    if (run_well_qc_fn_(project_, &info, &error)) {
        QMessageBox::information(this, QStringLiteral("井点 QC"),
                                 QString::fromStdString(info));
    } else {
        QMessageBox::warning(this, QStringLiteral("井点 QC 失败"),
                             QString::fromStdString(error));
    }
}

// -- prepare flow --------------------------------------------------------------------

void PreparationPage::on_generate_requested(const QString& method_q) {
    std::string method = method_q.toStdString();
    if (method.empty() && task_panel_ != nullptr) {
        method = task_panel_->selected_method().toStdString();
    }
    if (project_ == nullptr) {
        emit generate_requested(QString::fromStdString(method));
        return;
    }
    if (is_prepare_running()) {
        QMessageBox::information(this, QStringLiteral("单因素图"),
                                 QStringLiteral("正在生成中，请稍候…"));
        return;
    }
    start_prepare_worker(method);
}

void PreparationPage::start_prepare_worker(const std::string& method) {
    if (!prepare_worker_fn_) {
        return;  // no backend bound — stay inert, never a fake success
    }
    set_generate_enabled(false);
    prepare_generation_ =
        next_generation_fn_ ? next_generation_fn_() : prepare_generation_ + 1;
    const int generation = prepare_generation_;
    // Snapshot on the host thread so scientific inputs match the
    // Stage-4 fingerprints (Python parity).
    const int task_count = snapshot_task_count_fn_
                               ? snapshot_task_count_fn_(project_, method,
                                                         generation)
                               : 0;
    if (task_panel_ != nullptr && task_panel_->summary_label() != nullptr) {
        task_panel_->summary_label()
            ->setText(QString::fromStdString(
                prepare_start_label(task_count, generation)));
    }

    auto progress = [this](const PrepareProgressView& update) {
        on_prepare_progress(update);
    };
    auto completed = [this](const PrepareResultView& result) {
        on_prepare_completed(result);
    };
    auto failed = [this](const QString& message) {
        on_prepare_failed(message);
    };
    auto cancelled = [this]() { on_prepare_cancelled(); };
    // The host runs the worker off-thread and invokes exactly one terminal
    // callback on the UI thread (header contract).
    prepare_worker_fn_(project_, method, generation, progress, completed,
                       failed, cancelled);
}

void PreparationPage::clear_prepare_job() {
    if (!is_contour_running()) {
        set_generate_enabled(true);
    }
}

void PreparationPage::on_prepare_progress(const PrepareProgressView& update) {
    if (update.generation != current_generation()) return;
    const void* target = prepare_job_target();
    if (target != nullptr && target != project_) return;
    if (task_panel_ == nullptr || task_panel_->summary_label() == nullptr) {
        return;
    }
    task_panel_->summary_label()->setText(QString::fromStdString(
        prepare_progress_label(update.clean, update.dirty, update.completed,
                               update.total_tasks,
                               !update.message.empty() ? update.message
                                                       : update.phase)));
}

void PreparationPage::on_prepare_completed(const PrepareResultView& result) {
    if (project_ == nullptr) return;
    const void* target = prepare_job_target();
    if (target != nullptr && target != project_) return;
    if (result.generation != current_generation()) {
        // Superseded by a newer prepare request or project switch.
        return;
    }
    const int discarded =
        commit_prepare_fn_ ? commit_prepare_fn_(project_, result,
                                                current_generation())
                           : 0;
    if (factor_map_tasks_fn_) {
        update_state(factor_map_tasks_fn_(project_));
    }
    emit factor_maps_updated();
    if (task_panel_ != nullptr && task_panel_->summary_label() != nullptr) {
        int complete = 0;
        for (const auto& task : tasks_) {
            const auto status = task.find("status");
            if (status != task.end() && status->is_string() &&
                status->get<std::string>() == "complete") {
                ++complete;
            }
        }
        const int total = tasks_.is_array() ? int(tasks_.size()) : 0;
        task_panel_->summary_label()->setText(QString::fromStdString(
            prepare_done_label(complete, total, result.clean_count,
                               result.executed_count, discarded)));
    }
    clear_prepare_job();
}

void PreparationPage::on_prepare_failed(const QString& message) {
    const void* target = prepare_job_target();
    if (target != nullptr && target != project_) return;
    if (task_panel_ != nullptr && task_panel_->summary_label() != nullptr) {
        task_panel_->summary_label()->setText(QString::fromStdString(
            prepare_failed_label(message.toStdString())));
    }
    clear_prepare_job();
}

void PreparationPage::on_prepare_cancelled() {
    const void* target = prepare_job_target();
    if (target != nullptr && target != project_) return;
    if (task_panel_ != nullptr && task_panel_->summary_label() != nullptr) {
        task_panel_->summary_label()->setText(
            QString::fromStdString(std::string(kPrepareCancelledLabel)));
    }
    clear_prepare_job();
}

// -- contour flow ----------------------------------------------------------------------

void PreparationPage::on_contour_draft_requested() {
    if (project_ == nullptr) {
        QMessageBox::information(this, QStringLiteral("等值线初稿"),
                                 QStringLiteral("请先打开或绑定工程。"));
        return;
    }
    if (is_prepare_running()) {
        QMessageBox::information(this, QStringLiteral("等值线初稿"),
                                 QStringLiteral("单因素图仍在生成中。"));
        return;
    }
    if (is_contour_running()) return;
    if (!contour_worker_fn_) {
        return;  // no backend bound — stay inert
    }
    set_generate_enabled(false);
    auto completed = [this](void* result) { on_contour_completed(result); };
    auto failed = [this](const QString& message) {
        on_contour_failed(message);
    };
    contour_worker_fn_(project_, completed, failed);
}

void PreparationPage::clear_contour_job() {
    if (!is_prepare_running()) {
        set_generate_enabled(true);
    }
}

void PreparationPage::on_contour_completed(void* result) {
    if (project_ == nullptr) return;
    const void* target = contour_job_target();
    if (target != nullptr && target != project_) return;
    const int drafts = commit_contour_fn_
                           ? commit_contour_fn_(project_, result)
                           : 0;
    if (task_panel_ == nullptr || task_panel_->summary_label() == nullptr) {
        return;
    }
    if (drafts == 0) {
        // Async completions must not open a modal dialog (Python #897).
        task_panel_->summary_label()->setText(QString::fromStdString(
            contour_empty_label()));
        return;
    }
    if (factor_map_tasks_fn_) {
        update_state(factor_map_tasks_fn_(project_));
    }
    emit contour_drafts_updated();
    task_panel_->summary_label()->setText(
        QString::fromStdString(contour_done_label(drafts)));
    clear_contour_job();
}

void PreparationPage::on_contour_failed(const QString& message) {
    const void* target = contour_job_target();
    if (target != nullptr && target != project_) return;
    if (task_panel_ != nullptr && task_panel_->summary_label() != nullptr) {
        task_panel_->summary_label()->setText(QString::fromStdString(
            contour_failed_label(message.toStdString())));
    }
    clear_contour_job();
}

}  // namespace pwb::ui_pages_data::qt
