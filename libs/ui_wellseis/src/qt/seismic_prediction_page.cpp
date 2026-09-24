#include <pwb/ui_wellseis/qt/seismic_prediction_page.hpp>

#include <QCloseEvent>
#include <QComboBox>
#include <QMessageBox>
#include <QSplitter>
#include <QVBoxLayout>

#include <pwb/ui_wellseis/json_helpers.hpp>
#include <pwb/ui_wellseis/output_labels.hpp>
#include <pwb/ui_wellseis/qt/seismic_attribute_panel.hpp>
#include <pwb/ui_wellseis/qt/seismic_context_toolbar.hpp>
#include <pwb/ui_wellseis/qt/seismic_control_panel.hpp>
#include <pwb/ui_wellseis/qt/seismic_view_panel.hpp>
#include <pwb/ui_wellseis/resource_sources.hpp>
#include <pwb/ui_wellseis/task_state.hpp>

namespace pwb::ui_wellseis::qt {

namespace {

constexpr int kPanelMaxWidth = 360;

QString qs(const std::string& text) {
    return QString::fromUtf8(text.data(), static_cast<int>(text.size()));
}

std::vector<ResourceSlice> segy_resources(const ProjectSlice* project) {
    std::vector<ResourceSlice> out;
    if (project == nullptr) {
        return out;
    }
    for (const auto& resource : project->resources) {
        if (is_segy_resource(resource)) {
            out.push_back(resource);
        }
    }
    return out;
}

}  // namespace

SeismicPredictionPage::SeismicPredictionPage(QWidget* parent)
    : QWidget(parent) {
    setObjectName(QStringLiteral("SeismicPredictionPage"));

    auto* outer = new QVBoxLayout(this);
    outer->setContentsMargins(16, 16, 16, 16);
    outer->setSpacing(12);

    context_toolbar_ = new SeismicContextToolbar(this);
    outer->addWidget(context_toolbar_);

    splitter_ = new QSplitter(Qt::Horizontal, this);
    splitter_->setObjectName(QStringLiteral("SeismicPredictionSplitter"));

    // 属性 | 视图 | 控制: the view stays the stretchy center.
    attribute_panel_ = new SeismicAttributePanel(splitter_);
    attribute_panel_->setMaximumWidth(kPanelMaxWidth);
    splitter_->addWidget(attribute_panel_);
    view_panel_ = new SeismicViewPanel(splitter_);
    splitter_->addWidget(view_panel_);
    control_panel_ = new SeismicControlPanel(splitter_);
    control_panel_->setMaximumWidth(kPanelMaxWidth);
    splitter_->addWidget(control_panel_);
    splitter_->setStretchFactor(0, 0);
    splitter_->setStretchFactor(1, 1);
    splitter_->setStretchFactor(2, 0);
    splitter_->setSizes({280, 900, 280});
    outer->addWidget(splitter_, 1);

    // M6 float/dock is platform infra — the slice keeps panels docked and
    // wires the page-level signal graph verbatim (ledger note).
    connect(context_toolbar_, &SeismicContextToolbar::run_requested, this,
            &SeismicPredictionPage::on_run);
    connect(context_toolbar_, &SeismicContextToolbar::demo_requested, this,
            &SeismicPredictionPage::on_demo);
    connect(context_toolbar_, &SeismicContextToolbar::attribute_changed,
            this, &SeismicPredictionPage::on_attribute);
    connect(context_toolbar_,
            &SeismicContextToolbar::display_mode_changed, view_panel_,
            &SeismicViewPanel::set_display_mode);
    connect(context_toolbar_,
            &SeismicContextToolbar::display_mode_changed, control_panel_,
            &SeismicControlPanel::set_display_mode);
    connect(context_toolbar_, &SeismicContextToolbar::source_changed, this,
            [this](const QString& resource_id) {
                if (!resource_id.isEmpty()) {
                    select_seismic_resource(resource_id.toStdString());
                }
            });
    connect(control_panel_, &SeismicControlPanel::send_requested, this,
            &SeismicPredictionPage::send_to_mapping_requested);
    connect(control_panel_,
            &SeismicControlPanel::display_mode_changed, view_panel_,
            &SeismicViewPanel::set_display_mode);
    connect(attribute_panel_,
            &SeismicAttributePanel::attribute_changed, this,
            &SeismicPredictionPage::on_attribute);
    connect(control_panel_, &SeismicControlPanel::well_tie_toggled,
            view_panel_, &SeismicViewPanel::set_well_tie_enabled);
    connect(view_panel_, &SeismicViewPanel::view_ready, this,
            &SeismicPredictionPage::on_view_ready);
}

void SeismicPredictionPage::set_hooks(SeismicPredictionHooks hooks) {
    hooks_ = std::move(hooks);
}

SeismicContextToolbar* SeismicPredictionPage::context_toolbar() const {
    return context_toolbar_;
}
SeismicAttributePanel* SeismicPredictionPage::attribute_panel() const {
    return attribute_panel_;
}
SeismicViewPanel* SeismicPredictionPage::view_panel() const {
    return view_panel_;
}
SeismicControlPanel* SeismicPredictionPage::control_panel() const {
    return control_panel_;
}

void SeismicPredictionPage::set_project(const ProjectSlice* project) {
    if (project != project_) {
        ++session_token_;
        selected_resource_id_.reset();
        showing_selected_source_ = false;
    }
    project_ = project;
}

bool SeismicPredictionPage::shutdown_workers(int wait_ms) {
    const bool joined =
        !hooks_.shutdown || hooks_.shutdown(wait_ms);
    // A switch is aborted when a job cannot join — preserve the page and
    // session; the detached worker's results were already disconnected.
    if (!joined) {
        return false;
    }
    ++session_token_;
    inference_active_ = false;
    project_ = nullptr;
    view_panel_->shutdown();
    return true;
}

void SeismicPredictionPage::closeEvent(QCloseEvent* event) {
    // A page owns its inference thread; joining here covers direct widget
    // destruction as well as normal project-session shutdown.
    shutdown_workers();
    event->accept();
}

void SeismicPredictionPage::update_state(
    const std::vector<PredictionTaskSlice>& tasks,
    const ProjectSlice* project) {
    if (project != nullptr) {
        set_project(project);
    }
    tasks_ = tasks;
    sync_seismic_sources();
    const PredictionTaskSlice* task =
        showing_selected_source_ ? nullptr : current_task();
    const ResourceSlice* resource = selected_seismic_resource();
    if (showing_selected_source_ && resource != nullptr) {
        view_panel_->show_resource(*resource, project_);
    } else {
        view_panel_->update_state(task, project_);
    }
    control_panel_->update_state(task, view_panel_->volume_shape());
    sync_workbench_context(task);
    control_panel_->set_controls_enabled(view_panel_->is_view_ready());
}

const PredictionTaskSlice* SeismicPredictionPage::current_task() const {
    return active_prediction_task(tasks_);
}

void SeismicPredictionPage::sync_seismic_sources() {
    const std::string previous = selected_resource_id_.value_or("");
    const auto resources = segy_resources(project_);
    auto entries = source_combo_entries(resources, "未命名地震体", "");
    // Python parity: an empty list clears the combo (no placeholder row).
    context_toolbar_->set_source_entries(entries);
    const int selected =
        resolved_source_index(resources, previous);
    if (resources.empty() || selected < 0) {
        selected_resource_id_.reset();
        showing_selected_source_ = false;
    }
}

const ResourceSlice* SeismicPredictionPage::selected_seismic_resource()
    const {
    if (!selected_resource_id_.has_value() || project_ == nullptr) {
        return nullptr;
    }
    const auto resources = segy_resources(project_);
    return find_resource(resources, *selected_resource_id_);
}

std::optional<std::string>
SeismicPredictionPage::selected_seismic_resource_id() const {
    return selected_resource_id_;
}

bool SeismicPredictionPage::select_seismic_resource(
    const std::string& resource_id) {
    if (project_ == nullptr) {
        return false;
    }
    const auto resources = segy_resources(project_);
    const ResourceSlice* resource = find_resource(resources, resource_id);
    if (resource == nullptr) {
        return false;
    }
    selected_resource_id_ = resource->id;
    showing_selected_source_ = true;
    const bool loaded = view_panel_->show_resource(*resource, project_);
    control_panel_->update_state(nullptr, view_panel_->volume_shape());
    sync_workbench_context(nullptr);
    control_panel_->set_controls_enabled(view_panel_->is_view_ready());
    emit seismic_selection_changed(qs(*selected_resource_id_));
    return loaded;
}

void SeismicPredictionPage::on_attribute(const QString& label) {
    view_panel_->set_attribute_label(label);
    attribute_panel_->set_selected_attribute(label);
    sync_workbench_context(current_task());
}

void SeismicPredictionPage::on_view_ready(bool enabled) {
    control_panel_->set_controls_enabled(enabled);
    if (enabled) {
        const PredictionTaskSlice* task =
            showing_selected_source_ ? nullptr : current_task();
        sync_workbench_context(task);
    }
}

void SeismicPredictionPage::sync_workbench_context(
    const PredictionTaskSlice* task) {
    const QString attribute = view_panel_->attribute_label();
    const QString mode = view_panel_->display_mode();
    attribute_panel_->set_selected_attribute(attribute);
    control_panel_->set_attribute_label(attribute);
    // Python mirrors the control panel's horizon/shape/mock text into the
    // toolbar card; the same fields derive from the slice directly here.
    const std::string horizon =
        task != nullptr
            ? target_horizon_of(task->model_metadata, task->result_summary)
            : std::string();
    context_toolbar_->set_context(
        task, horizon, attribute.toStdString(), mode.toStdString(),
        view_panel_->volume_shape(),
        task != nullptr
            ? std::optional<std::string>(
                  seismic_output_nature(task->result_summary))
            : std::nullopt);
}

void SeismicPredictionPage::on_run() {
    // Production inference: resolve a production model, never auto-run
    // mock (spec P2 §3d — demo requires explicit demo mode).
    if (project_ == nullptr) {
        QMessageBox::warning(this, QStringLiteral("地震预测"),
                             QStringLiteral("未绑定工程，无法运行"));
        return;
    }
    if (!hooks_.catalog_connected || !hooks_.catalog_connected()) {
        QMessageBox::warning(this, QStringLiteral("地震预测"),
                             QStringLiteral("未连接数据目录，无法运行推断"));
        return;
    }
    const auto model_version_id =
        hooks_.production_model_id ? hooks_.production_model_id()
                                   : std::nullopt;
    if (!model_version_id.has_value()) {
        QMessageBox::warning(
            this, QStringLiteral("地震预测"),
            QStringLiteral(
                "未配置生产模型，无法运行科学预测。\n"
                "请先注册生产模型（ModelRegistry），"
                "或通过「运行演示预测」查看演示结果。"));
        return;
    }
    start_inference(*model_version_id, "seismic_facies", "地震相预测",
                    /*demo=*/false, selected_resource_id_);
}

void SeismicPredictionPage::on_demo() {
    // Explicit demo mode: run the registered DemoModelProvider.
    if (project_ == nullptr) {
        QMessageBox::warning(this, QStringLiteral("地震预测"),
                             QStringLiteral("未绑定工程，无法运行"));
        return;
    }
    if (!hooks_.catalog_connected || !hooks_.catalog_connected()) {
        QMessageBox::warning(this, QStringLiteral("地震预测"),
                             QStringLiteral("未连接数据目录，无法运行推断"));
        return;
    }
    const auto demo_version_id =
        hooks_.demo_model_id ? hooks_.demo_model_id() : std::nullopt;
    if (!demo_version_id.has_value()) {
        QMessageBox::warning(this, QStringLiteral("地震预测"),
                             QStringLiteral("演示模型未注册"));
        return;
    }
    start_inference(*demo_version_id, "seismic_facies",
                    "地震相预测(Demo)", /*demo=*/true,
                    selected_resource_id_);
}

void SeismicPredictionPage::start_inference(
    const std::string& model_version_id, const std::string& workflow,
    const std::string& name_prefix, bool demo,
    const std::optional<std::string>& resource_id) {
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
                this, QStringLiteral("地震预测"),
                QStringLiteral("输入不满足模型契约: %1")
                    .arg(qs(*error)));
            return;
        }
    }
    domain::Json parameters = domain::Json::object();
    parameters["seed"] = static_cast<long long>(tasks_.size());
    parameters["workflow"] = workflow;
    parameters["name_prefix"] = name_prefix;
    parameters["demo"] = demo;
    parameters["seismic_resource_ids"] =
        resource_id.has_value()
            ? domain::Json::array({*resource_id})
            : domain::Json::array();
    inference_active_ = true;
    context_toolbar_->set_inferring(true);
    if (hooks_.start_run) {
        hooks_.start_run(model_version_id, input_ids, parameters);
    }
}

void SeismicPredictionPage::on_inference_completed(
    const domain::Json& payload) {
    // Session-token parity: a stale worker (project switched / shutdown)
    // cannot publish into the rebound page.
    if (!inference_active_) {
        return;
    }
    inference_active_ = false;
    context_toolbar_->set_inferring(false);
    const Json& run = json_field(payload, "run");
    const std::string run_status =
        run.is_object() ? json_str(run, "status", "") : "";
    if (!run.is_object() || run_status == "failed") {
        std::string error = "未知错误";
        if (run.is_object()) {
            error = json_str(json_object(run, "parameters"), "error",
                             "未知错误");
        }
        // Async completion: in-page status instead of a modal dialog.
        context_toolbar_->set_status(
            QStringLiteral("推断失败: %1").arg(qs(error)));
        return;
    }
    // Terminal cancel: honest status — never a fabricated completion and
    // never a failure scare (the partial tiles stay resume-eligible).
    if (run_status == "cancelled") {
        context_toolbar_->set_status(QStringLiteral("推断已取消"));
        return;
    }
    const Json& result = json_field(payload, "result");
    if (!result.is_object() || result.empty()) {
        const std::string error =
            run.is_object()
                ? json_str(json_object(run, "parameters"), "error",
                           "预测完成但未返回可用结果")
                : "预测完成但未返回可用结果";
        context_toolbar_->set_status(
            QStringLiteral("推断失败: %1").arg(qs(error)));
        return;
    }
    if (hooks_.materialize_task) {
        tasks_.push_back(hooks_.materialize_task(run, result));
    }
    showing_selected_source_ = false;
    update_state(tasks_, project_);
    emit prediction_updated();
}

void SeismicPredictionPage::on_inference_failed(const std::string& text) {
    if (!inference_active_) {
        return;
    }
    inference_active_ = false;
    context_toolbar_->set_inferring(false);
    context_toolbar_->set_status(
        QStringLiteral("推断失败: %1").arg(qs(text)));
}

}  // namespace pwb::ui_wellseis::qt
