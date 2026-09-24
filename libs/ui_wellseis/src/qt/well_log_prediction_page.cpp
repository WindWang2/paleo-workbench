#include <pwb/ui_wellseis/qt/well_log_prediction_page.hpp>

#include <algorithm>
#include <cctype>

#include <QCloseEvent>
#include <QComboBox>
#include <QFileDialog>
#include <QFileInfo>
#include <QHBoxLayout>
#include <QLabel>
#include <QMessageBox>
#include <QPixmap>
#include <QPushButton>
#include <QSplitter>
#include <QVBoxLayout>

#include <pwb/ui_wellseis/json_helpers.hpp>
#include <pwb/ui_wellseis/page_state.hpp>
#include <pwb/ui_wellseis/qt/prediction_evidence_panel.hpp>
#include <pwb/ui_wellseis/qt/task_panel_base.hpp>
#include <pwb/ui_wellseis/qt/well_log_canvas_panel.hpp>
#include <pwb/ui_wellseis/redact.hpp>
#include <pwb/ui_wellseis/run_diagnostic.hpp>
#include <pwb/ui_wellseis/task_state.hpp>

namespace pwb::ui_wellseis::qt {

namespace {

constexpr int kPanelMaxWidth = 360;

QString qs(const std::string& text) {
    return QString::fromUtf8(text.data(), static_cast<int>(text.size()));
}

std::vector<ResourceSlice> well_log_resources(const ProjectSlice* project) {
    std::vector<ResourceSlice> out;
    if (project == nullptr) {
        return out;
    }
    for (const auto& resource : project->resources) {
        if (is_well_log_resource(resource)) {
            out.push_back(resource);
        }
    }
    return out;
}

// The two workflow tags whose status line mentions the online route.
bool is_online_workflow(const std::string& workflow) {
    return workflow == "geoviz_online_well_log_facies" ||
           workflow == "inference_api_well_log_facies";
}

}  // namespace

WellLogPredictionPage::WellLogPredictionPage(QWidget* parent)
    : QWidget(parent) {
    setObjectName(QStringLiteral("WellLogPredictionPage"));

    auto* outer = new QVBoxLayout(this);
    outer->setContentsMargins(16, 16, 16, 16);
    outer->setSpacing(12);

    auto* source_row = new QHBoxLayout();
    auto* source_label =
        new QLabel(QStringLiteral("测井数据源"), this);
    source_label->setObjectName(QStringLiteral("WorkFieldLabel"));
    source_row->addWidget(source_label);
    well_source_combo_ = new QComboBox(this);
    well_source_combo_->setObjectName(
        QStringLiteral("WellPredictionSourceCombo"));
    well_source_combo_->setToolTip(QStringLiteral(
        "选择数据管理中已归档的 LAS 或 XML 测井数据，加载后可直接运行预测"));
    connect(well_source_combo_, &QComboBox::currentIndexChanged, this,
            [this](int) {
                const QString resource_id =
                    well_source_combo_->currentData().toString();
                if (!resource_id.isEmpty()) {
                    select_well_resource(resource_id.toStdString());
                }
            });
    source_row->addWidget(well_source_combo_, 1);
    auto* import_btn =
        new QPushButton(QStringLiteral("导入 LAS / XML…"), this);
    import_btn->setObjectName(QStringLiteral("SecondaryButton"));
    import_btn->setToolTip(QStringLiteral(
        "导入外部 LAS、WITSML 或 SpreadsheetML XML 测井数据，并纳入数据管理"));
    connect(import_btn, &QPushButton::clicked, this,
            &WellLogPredictionPage::on_import_well_logs);
    source_row->addWidget(import_btn);
    outer->addLayout(source_row);

    splitter_ = new QSplitter(Qt::Horizontal, this);
    splitter_->setObjectName(QStringLiteral("WellLogPredictionSplitter"));
    task_panel_ = new PredictionTaskPanel(splitter_);
    task_panel_->setMaximumWidth(kPanelMaxWidth);
    splitter_->addWidget(task_panel_);
    canvas_panel_ = new WellLogCanvasPanel(splitter_);
    splitter_->addWidget(canvas_panel_);
    evidence_panel_ = new PredictionEvidencePanel(splitter_);
    evidence_panel_->setMaximumWidth(kPanelMaxWidth);
    splitter_->addWidget(evidence_panel_);
    splitter_->setStretchFactor(0, 0);
    splitter_->setStretchFactor(1, 1);
    splitter_->setStretchFactor(2, 0);
    splitter_->setSizes({280, 860, 260});
    outer->addWidget(splitter_, 1);

    // M6 float/dock is platform infra — panels stay docked (ledger note).
    connect(task_panel_, &TaskPanelBase::task_selected, this,
            [this](int row) { on_task_selected(row); });
    connect(evidence_panel_, &PredictionEvidencePanel::run_requested, this,
            &WellLogPredictionPage::on_run);
    connect(evidence_panel_, &PredictionEvidencePanel::demo_requested, this,
            &WellLogPredictionPage::on_demo);
    connect(evidence_panel_, &PredictionEvidencePanel::send_requested, this,
            &WellLogPredictionPage::send_to_preparation_requested);
    connect(evidence_panel_, &PredictionEvidencePanel::export_requested,
            this, &WellLogPredictionPage::on_export);
    // A bound LAS finishes loading on a worker thread (#842); refresh the
    // evidence summary once it lands so the source label + export gating
    // track the actual canvas state.
    connect(canvas_panel_, &WellLogCanvasPanel::canvas_ready, this,
            &WellLogPredictionPage::on_canvas_ready);
}

void WellLogPredictionPage::set_hooks(WellLogPredictionHooks hooks) {
    hooks_ = std::move(hooks);
}

PredictionTaskPanel* WellLogPredictionPage::task_panel() const {
    return task_panel_;
}
WellLogCanvasPanel* WellLogPredictionPage::canvas_panel() const {
    return canvas_panel_;
}
PredictionEvidencePanel* WellLogPredictionPage::evidence_panel() const {
    return evidence_panel_;
}

void WellLogPredictionPage::set_project(const ProjectSlice* project) {
    if (project != project_) {
        ++session_token_;
        selected_resource_id_.reset();
    }
    project_ = project;
}

void WellLogPredictionPage::set_project_path(const QString& path) {
    project_path_ = path;
}

bool WellLogPredictionPage::shutdown_workers(int wait_ms) {
    const bool joined = !hooks_.shutdown || hooks_.shutdown(wait_ms);
    // A failed join means the controller keeps the current session and
    // catalog alive — keep the page's document/canvas intact as well.
    if (!joined) {
        return false;
    }
    ++session_token_;
    inference_active_ = false;
    project_ = nullptr;
    canvas_panel_->shutdown();
    return true;
}

void WellLogPredictionPage::closeEvent(QCloseEvent* event) {
    shutdown_workers();
    event->accept();
}

void WellLogPredictionPage::update_state(
    const std::vector<PredictionTaskSlice>& tasks,
    const ProjectSlice* project) {
    if (project != nullptr) {
        set_project(project);
    }
    // V11 C4: selection anchors the task id, never the position.
    const std::optional<std::string> selected_id = selected_task_id_;
    tasks_ = tasks;
    selected_index_.reset();
    if (selected_id.has_value()) {
        selected_index_ = index_of_task_id(tasks_, *selected_id);
    }
    sync_well_sources();
    const PredictionTaskSlice* task = current_task();
    task_panel_->update_state(tasks_, selected_index_);
    if (task != nullptr) {
        canvas_panel_->update_state(task, project_);
        evidence_panel_->update_state(
            task, canvas_panel_->has_bound_las());
        return;
    }
    const ResourceSlice* resource = selected_well_resource();
    if (resource != nullptr) {
        canvas_panel_->show_resource(*resource, project_);
        evidence_panel_->update_state(
            nullptr, canvas_panel_->has_bound_las(),
            /*selected_source=*/true);
        return;
    }
    canvas_panel_->update_state(nullptr, project_);
    evidence_panel_->update_state(nullptr, false);
}

const PredictionTaskSlice* WellLogPredictionPage::current_task() const {
    if (selected_index_.has_value() && *selected_index_ >= 0 &&
        *selected_index_ < static_cast<int>(tasks_.size())) {
        return &tasks_[static_cast<std::size_t>(*selected_index_)];
    }
    return active_prediction_task(tasks_);
}

void WellLogPredictionPage::on_canvas_ready(bool /*ready*/) {
    const PredictionTaskSlice* task = current_task();
    if (task != nullptr) {
        evidence_panel_->update_state(
            task, canvas_panel_->has_bound_las());
    } else if (selected_well_resource() != nullptr) {
        evidence_panel_->update_state(
            nullptr, canvas_panel_->has_bound_las(),
            /*selected_source=*/true);
    }
}

void WellLogPredictionPage::on_task_selected(int index) {
    selected_index_ = index;
    const PredictionTaskSlice* task = current_task();
    selected_task_id_ =
        task != nullptr ? std::optional<std::string>(task->id)
                        : std::nullopt;
    task_panel_->update_state(tasks_, selected_index_);
    canvas_panel_->update_state(task, project_);
    evidence_panel_->update_state(task, canvas_panel_->has_bound_las());
}

void WellLogPredictionPage::sync_well_sources() {
    const std::string previous = selected_resource_id_.value_or("");
    const auto resources = well_log_resources(project_);
    const auto entries =
        source_combo_entries(resources, "未命名测井",
                             "数据管理中暂无 LAS / XML 测井数据");
    const SourceSignature signature = source_signature(entries);
    if (signature == well_source_signature_) {
        // Same source revision: keep the combo and only re-assert the
        // selection invariant.
        const int target = previous.empty()
                               ? -1
                               : well_source_combo_->findData(
                                     qs(previous));
        if (target != well_source_combo_->currentIndex()) {
            well_source_combo_->blockSignals(true);
            well_source_combo_->setCurrentIndex(target);
            well_source_combo_->blockSignals(false);
        }
        return;
    }
    well_source_combo_->blockSignals(true);
    well_source_combo_->clear();
    for (const SourceComboEntry& entry : entries) {
        well_source_combo_->addItem(qs(entry.label),
                                    qs(entry.resource_id));
    }
    if (resources.empty()) {
        selected_resource_id_.reset();
    } else {
        const int selected = resolved_source_index(resources, previous);
        well_source_combo_->setCurrentIndex(selected);
        if (selected < 0) {
            selected_resource_id_.reset();
        }
    }
    well_source_combo_->blockSignals(false);
    well_source_signature_ = signature;
}

const ResourceSlice* WellLogPredictionPage::selected_well_resource()
    const {
    if (!selected_resource_id_.has_value() || project_ == nullptr) {
        return nullptr;
    }
    const auto resources = well_log_resources(project_);
    return find_resource(resources, *selected_resource_id_);
}

std::optional<std::string>
WellLogPredictionPage::selected_well_resource_id() const {
    return selected_resource_id_;
}

void WellLogPredictionPage::set_source_import_status(const QString& text) {
    evidence_panel_->set_status(text);
}

void WellLogPredictionPage::begin_external_run() {
    // Mirrors start_inference's busy state so the queued completion from
    // the RunSpec path passes the session guard.
    inference_active_ = true;
    evidence_panel_->set_inferring(true);
}

bool WellLogPredictionPage::select_well_resource(    const std::string& resource_id) {
    if (project_ == nullptr) {
        return false;
    }
    const auto resources = well_log_resources(project_);
    const ResourceSlice* resource = find_resource(resources, resource_id);
    if (resource == nullptr) {
        return false;
    }
    selected_resource_id_ = resource->id;
    const int combo_index =
        well_source_combo_->findData(qs(*selected_resource_id_));
    if (combo_index >= 0 &&
        combo_index != well_source_combo_->currentIndex()) {
        well_source_combo_->blockSignals(true);
        well_source_combo_->setCurrentIndex(combo_index);
        well_source_combo_->blockSignals(false);
    }
    // Selecting a source clears the selected task: before inference there
    // is no prediction overlay, only the user-selected source well.
    selected_index_.reset();
    selected_task_id_.reset();
    task_panel_->update_state(tasks_, std::nullopt);
    canvas_panel_->show_resource(*resource, project_);
    evidence_panel_->update_state(
        nullptr, canvas_panel_->has_bound_las(),
        /*selected_source=*/true);
    restore_latest_failed_online_run(resource->id);
    emit well_selection_changed(qs(*selected_resource_id_));
    return true;
}

bool WellLogPredictionPage::set_selected_well(
    const std::string& well_name) {
    // Cross-page seam (3D page -> prediction): select the task named for
    // the well, suppressing the list's re-entrant update (Python parity).
    if (well_name.empty()) {
        return false;
    }
    const auto index = index_of_task_named(tasks_, well_name);
    if (!index.has_value()) {
        return false;
    }
    selected_index_ = *index;
    selected_task_id_ = tasks_[static_cast<std::size_t>(*index)].id;
    task_panel_->update_state(tasks_, selected_index_);
    const PredictionTaskSlice* task = current_task();
    canvas_panel_->update_state(task, project_);
    evidence_panel_->update_state(task, canvas_panel_->has_bound_las());
    return true;
}

void WellLogPredictionPage::on_import_well_logs() {
    // Import stays owned by DataPage — this page only asks for files.
    if (project_ == nullptr) {
        QMessageBox::warning(this, QStringLiteral("导入测井数据"),
                             QStringLiteral("请先打开或创建工程"));
        return;
    }
    const QStringList paths =
        hooks_.open_file_names
            ? hooks_.open_file_names(
                  QStringLiteral("导入测井数据"),
                  QStringLiteral(
                      "测井数据 (*.las *.LAS *.xml *.XML)"))
            : QFileDialog::getOpenFileNames(
                  this, QStringLiteral("导入测井数据"), QString(),
                  QStringLiteral(
                      "测井数据 (*.las *.LAS *.xml *.XML)"));
    if (!paths.isEmpty()) {
        emit well_log_import_requested(paths);
    }
}

void WellLogPredictionPage::on_run() {
    // The explicit authenticated online single-well prediction route.
    if (project_ == nullptr) {
        QMessageBox::warning(this, QStringLiteral("测井预测"),
                             QStringLiteral("未绑定工程，无法运行"));
        return;
    }
    const ResourceSlice* resource = selected_well_resource();
    if (resource == nullptr) {
        QMessageBox::warning(
            this, QStringLiteral("测井预测"),
            QStringLiteral("请先从数据管理选择一口井数据"));
        return;
    }
    if (!hooks_.catalog_connected || !hooks_.catalog_connected()) {
        QMessageBox::warning(this, QStringLiteral("测井预测"),
                             QStringLiteral("未连接数据目录，无法运行推断"));
        return;
    }
    std::string route_error;
    std::optional<WellLogPredictionHooks::OnlineRoute> route;
    if (hooks_.online_route) {
        route = hooks_.online_route(route_error);
    } else {
        route_error = "online route unavailable";
    }
    if (!route.has_value()) {
        QMessageBox::warning(
            this, QStringLiteral("测井预测"),
            QStringLiteral("无法准备线上测井预测: %1")
                .arg(qs(route_error)));
        return;
    }
    domain::Json extra = domain::Json::object();
    extra["online_endpoint"] = route->endpoint;
    extra["online_model_version_id"] = route->remote_model_version_id;
    extra["online_wait_timeout_seconds"] = route->wait_timeout_seconds;
    extra["online_request_timeout_seconds"] = route->request_timeout_seconds;
    extra["online_poll_timeout_seconds"] = route->poll_timeout_seconds;
    start_inference(route->model_version_id,
                    "inference_api_well_log_facies", "线上测井相预测",
                    /*demo=*/false, resource->id, extra);
}

void WellLogPredictionPage::on_demo() {
    if (project_ == nullptr) {
        QMessageBox::warning(this, QStringLiteral("测井预测"),
                             QStringLiteral("未绑定工程，无法运行"));
        return;
    }
    const ResourceSlice* resource = selected_well_resource();
    if (resource == nullptr) {
        QMessageBox::warning(
            this, QStringLiteral("测井预测"),
            QStringLiteral("请先从数据管理选择一口井数据"));
        return;
    }
    if (!hooks_.catalog_connected || !hooks_.catalog_connected()) {
        QMessageBox::warning(this, QStringLiteral("测井预测"),
                             QStringLiteral("未连接数据目录，无法运行推断"));
        return;
    }
    std::string demo_error;
    std::optional<std::string> demo_version_id;
    if (hooks_.demo_model_id) {
        demo_version_id = hooks_.demo_model_id(demo_error);
    }
    if (!demo_version_id.has_value()) {
        QMessageBox::warning(
            this, QStringLiteral("测井预测"),
            QStringLiteral("演示模型未注册: %1").arg(qs(demo_error)));
        return;
    }
    start_inference(*demo_version_id, "well_log_facies", "测井相预测(Demo)",
                    /*demo=*/true, resource->id, domain::Json::object());
}

void WellLogPredictionPage::start_inference(
    const std::string& model_version_id, const std::string& workflow,
    const std::string& name_prefix, bool demo,
    const std::optional<std::string>& resource_id,
    const domain::Json& extra_parameters) {
    if (hooks_.is_running && hooks_.is_running()) {
        return;
    }
    std::vector<std::string> input_ids;
    if (demo && !resource_id.has_value()) {
        input_ids.clear();
    } else if (hooks_.resolve_inputs) {
        const auto error = hooks_.resolve_inputs(model_version_id,
                                                 resource_id, input_ids);
        if (error.has_value()) {
            QMessageBox::warning(
                this, QStringLiteral("测井预测"),
                QStringLiteral("输入不满足模型契约: %1").arg(qs(*error)));
            return;
        }
        if (workflow == "inference_api_well_log_facies" &&
            hooks_.resolve_postprocess_inputs) {
            hooks_.resolve_postprocess_inputs(input_ids);
            // list(dict.fromkeys(input_ids)) parity — dedupe, keep order.
            std::vector<std::string> unique;
            for (const auto& id : input_ids) {
                if (std::find(unique.begin(), unique.end(), id) ==
                    unique.end()) {
                    unique.push_back(id);
                }
            }
            input_ids = std::move(unique);
        }
    }
    domain::Json parameters = domain::Json::object();
    parameters["seed"] = static_cast<long long>(tasks_.size());
    parameters["workflow"] = workflow;
    parameters["name_prefix"] = name_prefix;
    parameters["demo"] = demo;
    parameters["well_log_resource_ids"] =
        resource_id.has_value()
            ? domain::Json::array({*resource_id})
            : domain::Json::array();
    if (extra_parameters.is_object()) {
        for (const auto& [key, value] : extra_parameters.items()) {
            parameters[key] = value;
        }
    }
    inference_active_ = true;
    evidence_panel_->set_inferring(true);
    if (is_online_workflow(workflow)) {
        evidence_panel_->set_status(
            QStringLiteral("正在调用线上测井预测服务…"));
    }
    RunSlice run_slice;
    if (hooks_.start_run) {
        run_slice = hooks_.start_run(model_version_id, input_ids,
                                     parameters);
    }
    // _write_run_diagnostic(run, status="推断中") — after run creation,
    // with the id filled like the Python path.
    write_run_diagnostic(run_slice.id.empty() ? nullptr : &run_slice,
                         "推断中");
}

void WellLogPredictionPage::on_inference_completed(
    const domain::Json& payload) {
    if (!inference_active_) {
        return;
    }
    inference_active_ = false;
    evidence_panel_->set_inferring(false);
    const Json& run = json_field(payload, "run");
    RunSlice run_slice;
    if (run.is_object()) {
        run_slice.id = json_str(run, "id", "");
        run_slice.status = json_str(run, "status", "");
        run_slice.created_at = json_str(run, "created_at", "");
        run_slice.parameters = json_object(run, "parameters");
        for (const auto& vid : json_array(run, "output_version_ids")) {
            if (vid.is_string()) {
                run_slice.output_version_ids.push_back(
                    vid.get<std::string>());
            }
        }
    }
    const bool run_failed =
        !run.is_object() || run_slice.status == "failed";
    if (run_failed) {
        const std::string error =
            run.is_object() ? run_error_text(run_slice) : "未知错误";
        evidence_panel_->set_status(
            QStringLiteral("推断失败: %1")
                .arg(qs(redact_diagnostic_text(error))));
        write_run_diagnostic(run.is_object() ? &run_slice : nullptr,
                             "失败", error);
        return;
    }
    // Terminal cancel: honest status — never "完成", never a failure scare.
    // The cancelled run's partial tiles stay resume-eligible (resume=true).
    if (run_slice.status == "cancelled") {
        evidence_panel_->set_status(QStringLiteral("推断已取消"));
        write_run_diagnostic(&run_slice, "已取消");
        return;
    }
    const Json& result = json_field(payload, "result");
    if (!result.is_object() || result.empty()) {
        std::string error =
            run.is_object()
                ? json_str(json_object(run, "parameters"), "error", "")
                : "";
        if (error.empty()) {
            error = "预测完成但未返回可用结果";
        }
        evidence_panel_->set_status(
            QStringLiteral("推断失败: %1")
                .arg(qs(redact_diagnostic_text(error))));
        write_run_diagnostic(run.is_object() ? &run_slice : nullptr,
                             "失败", error);
        return;
    }
    PredictionTaskSlice task;
    if (hooks_.materialize_task) {
        task = hooks_.materialize_task(run, result);
    }
    tasks_.push_back(task);
    selected_index_ = static_cast<int>(tasks_.size()) - 1;
    selected_task_id_ = task.id;
    update_state(tasks_, project_);
    const std::string model_type =
        json_str(task.result_summary, "model_type", "");
    if (model_type == "geoviz_online" ||
        model_type == "inference_api_online") {
        evidence_panel_->set_status(
            QStringLiteral("线上测井预测完成，结果已保存到数据管理"));
    } else {
        evidence_panel_->set_status(
            QStringLiteral("预测完成，结果已保存到数据管理"));
    }
    write_run_diagnostic(&run_slice, "完成");
    emit prediction_updated();
}

void WellLogPredictionPage::on_inference_failed(const std::string& text) {
    if (!inference_active_) {
        return;
    }
    inference_active_ = false;
    evidence_panel_->set_inferring(false);
    evidence_panel_->set_status(
        QStringLiteral("推断失败: %1")
            .arg(qs(redact_diagnostic_text(text))));
    write_run_diagnostic(nullptr, "异常中断", text);
}

void WellLogPredictionPage::restore_latest_failed_online_run(
    const std::string& resource_id) {
    if (inference_active_ || resource_id.empty() || !hooks_.list_runs ||
        !hooks_.catalog_connected || !hooks_.catalog_connected()) {
        return;
    }
    const std::vector<RunSlice> runs = hooks_.list_runs();
    const RunSlice* run = latest_failed_online_run(runs, resource_id);
    if (run == nullptr) {
        return;
    }
    const std::string error = run_error_text(*run);
    evidence_panel_->set_status(
        QStringLiteral("上次推断失败: %1")
            .arg(qs(redact_diagnostic_text(error))));
    write_run_diagnostic(run, "失败（历史运行）", error);
}

void WellLogPredictionPage::write_run_diagnostic(
    const RunSlice* run, const std::string& status,
    const std::string& error) {
    evidence_panel_->set_diagnostic_log(qs(run_diagnostic_log(
        run, status, error, selected_well_resource())));
}

void WellLogPredictionPage::on_export(const QString& format_label) {
    if (!canvas_panel_->is_canvas_ready()) {
        QMessageBox::warning(this, QStringLiteral("导出"),
                             QStringLiteral("当前没有可导出的测井剖面"));
        return;
    }
    const QString label = (format_label.isEmpty()
                               ? QStringLiteral("PNG")
                               : format_label)
                              .toUpper();
    const QString suffix =
        label == "SVG" ? QStringLiteral(".svg")
        : label == "PDF" ? QStringLiteral(".pdf")
                         : QStringLiteral(".png");
    std::string stem = canvas_panel_->well_name();
    if (stem.empty()) {
        stem = "well_log";
    }
    std::string safe;
    safe.reserve(stem.size());
    for (const char c : stem) {
        safe += (std::isalnum(static_cast<unsigned char>(c)) || c == '-' ||
                 c == '_')
                    ? c
                    : '_';
    }
    if (safe.size() > 64) {
        safe.resize(64);
    }
    const QString start_dir =
        hooks_.default_export_dir
            ? qs(hooks_.default_export_dir())
            : QString();
    const QString start =
        start_dir + "/" + qs(safe) + "_well" + suffix;
    const QString path =
        hooks_.save_file_name
            ? hooks_.save_file_name(
                  QStringLiteral("导出单井剖面 (%1)").arg(label), start,
                  QStringLiteral("%1 (*%2)").arg(label, suffix))
            : QFileDialog::getSaveFileName(
                  this, QStringLiteral("导出单井剖面 (%1)").arg(label),
                  start, QStringLiteral("%1 (*%2)").arg(label, suffix));
    if (path.isEmpty()) {
        return;
    }
    const PredictionTaskSlice* task = current_task();
    const std::vector<std::string> task_ids =
        task != nullptr ? std::vector<std::string>{task->id}
                        : std::vector<std::string>{};
    std::optional<std::string> error;
    if (canvas_panel_->backend() == kWellLogBackendEngine) {
        // Engine branch: PNG grab only — vector formats get the honest
        // redirect (well_log_export_block_reason parity).
        error = well_log_export_block_reason(canvas_panel_->backend(),
                                             label.toStdString());
        if (!error.has_value()) {
            QWidget* view = canvas_panel_->engine_view_widget();
            if (view == nullptr) {
                error = std::string("WellLogEngine 视图不可用");
            } else {
                const QPixmap pixmap = view->grab();
                if (pixmap.isNull()) {
                    error = std::string("WellLogEngine 抓屏失败");
                } else if (!pixmap.save(path, "PNG")) {
                    error = std::string("PNG 写入失败");
                } else if (hooks_.register_export &&
                           project_ != nullptr) {
                    hooks_.register_export(path.toStdString(), "png",
                                           task_ids);
                }
            }
        }
    } else {
        error = canvas_panel_->export_legacy(path.toStdString(),
                                             label.toStdString(), project_,
                                             task_ids);
    }
    if (error.has_value()) {
        QMessageBox::warning(this, QStringLiteral("导出失败"),
                             qs(*error));
        return;
    }
    QMessageBox::information(
        this, QStringLiteral("导出完成"),
        QStringLiteral("已导出: %1").arg(QFileInfo(path).fileName()));
}

}  // namespace pwb::ui_wellseis::qt
