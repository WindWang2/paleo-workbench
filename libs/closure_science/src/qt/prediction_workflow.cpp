#include <pwb/closure_science/qt/prediction_workflow.hpp>

#include <pwb/closure_science/qt/prediction_workflow_dialogs.hpp>
#include <pwb/ui_wellseis/qt/seismic_prediction_page.hpp>
#include <pwb/ui_wellseis/qt/well_log_prediction_page.hpp>

#include <QMessageBox>
#include <QObject>
#include <QString>

#include <map>
#include <utility>

namespace pwb::closure_science::qt {

using ui_wellseis::qt::SeismicPredictionPage;
using ui_wellseis::qt::WellLogPredictionPage;

namespace {
QString qs(const std::string& text) {
    return QString::fromStdString(text);
}
}  // namespace

PredictionWorkflowController::PredictionWorkflowController(
    SciencePageBinding* binding, WellLogPredictionPage* well_page,
    SeismicPredictionPage* seismic_page, QObject* parent)
    : QObject(parent),
      binding_(binding),
      well_page_(well_page),
      seismic_page_(seismic_page),
      link_(new WellSeismicLinkController(this)) {
    setObjectName(QStringLiteral("PredictionWorkflowController"));
    if (well_page_ != nullptr && seismic_page_ != nullptr) {
        link_->attach(well_page_, seismic_page_);
    }
    connect(link_, &WellSeismicLinkController::link_status_message, this,
            &PredictionWorkflowController::status_message);
    // Seismic selection on the page updates the SAME spec (no second
    // seismic selection state anywhere).
    if (seismic_page_ != nullptr) {
        connect(seismic_page_,
                &SeismicPredictionPage::seismic_selection_changed, this,
                [this](const QString& resource_id) {
                    apply_seismic_selection(resource_id.toStdString());
                });
        if (const auto current =
                seismic_page_->selected_seismic_resource_id();
            current.has_value()) {
            apply_seismic_selection(*current);
        }
    }
}

PredictionWorkflowController::~PredictionWorkflowController() = default;

void PredictionWorkflowController::set_project_seams(ProjectSeams seams) {
    seams_ = std::move(seams);
}

void PredictionWorkflowController::set_dialog_parent(QWidget* parent) {
    dialog_parent_ = parent;
}

bool PredictionWorkflowController::restore_persisted_spec() {
    // No cross-project leakage: the draft resets to defaults FIRST, then
    // the newly opened project's section (when valid) replaces it.
    spec_ = pwb::prediction::PredictionRunSpec{};
    if (well_page_ != nullptr) {
        if (const auto current = well_page_->selected_well_resource_id();
            current.has_value()) {
            spec_.well_resource_ids.assign(1, *current);
        }
    }
    if (!seams_.read_run_spec) return false;
    const domain::Json stored = seams_.read_run_spec();
    if (!stored.is_object()) return false;
    std::vector<std::string> errors;
    const auto parsed = pwb::prediction::PredictionRunSpec::from_json(
        stored, errors, /*require_model=*/false);
    if (!parsed.has_value()) {
        QString joined;
        for (const auto& error : errors) {
            if (!joined.isEmpty()) joined += QStringLiteral("; ");
            joined += qs(error);
        }
        emit status_message(
            QStringLiteral("已忽略无法解析的预测运行配置: %1").arg(joined));
        return false;
    }
    spec_ = *parsed;
    // Resolved identity never survives a reload — preflight re-resolves.
    spec_.resolved = domain::Json::object();
    emit spec_changed();
    return true;
}

void PredictionWorkflowController::open_well_selection() {
    if (binding_ == nullptr) {
        emit status_message(QStringLiteral("预测后端未装配（closure-science 构建切片未接入）"));
        return;
    }
    std::string error;
    const std::vector<WellCandidate> wells =
        binding_->well_candidates(spec_.model_version_id, &error);
    if (!error.empty()) {
        QMessageBox::warning(dialog_parent_,
                             QStringLiteral("选择井数据"), qs(error));
        return;
    }
    if (wells.empty()) {
        QMessageBox::information(
            dialog_parent_, QStringLiteral("选择井数据"),
            QStringLiteral("工程中没有已登记的测井资源（先在数据管理工作区"
                           "导入并纳管测井数据）"));
        return;
    }
    WellSelectionDialog dialog(wells, spec_.well_resource_ids,
                               dialog_parent_);
    if (dialog.exec() != QDialog::Accepted) return;
    spec_.well_resource_ids = dialog.selected_resource_ids();
    // Pane refresh: the first selected well becomes the page's shown
    // source (canvas + evidence rebind; the page emits its selection
    // change — the RunSpec keeps the FULL stable-id set).
    if (!spec_.well_resource_ids.empty() && well_page_ != nullptr) {
        well_page_->select_well_resource(spec_.well_resource_ids.front());
    }
    persist_spec();
    emit spec_changed();
    emit status_message(
        QStringLiteral("已选择 %1 口井参与预测")
            .arg(static_cast<int>(spec_.well_resource_ids.size())));
}

void PredictionWorkflowController::open_model_selection() {
    if (binding_ == nullptr) {
        emit status_message(QStringLiteral("预测后端未装配（closure-science 构建切片未接入）"));
        return;
    }
    std::string error;
    const std::vector<ModelCandidate> models =
        binding_->model_candidates(&error);
    if (!error.empty()) {
        QMessageBox::warning(dialog_parent_,
                             QStringLiteral("选择预测模型"), qs(error));
        return;
    }
    if (models.empty()) {
        QMessageBox::information(
            dialog_parent_, QStringLiteral("选择预测模型"),
            QStringLiteral("模型注册表中没有已登记的模型（先注册模型包）"));
        return;
    }
    // Pre-inspect the packages (few rows; the digest is the run's own
    // validation, so selection time is the right place to pay it).
    std::map<std::string, ModelPackageSummary> summaries;
    for (const auto& model : models) {
        if (model.provider != "tiled_onnx") continue;
        summaries.emplace(model.model_version_id,
                          inspect_model_package(model.artifact_uri));
    }
    ModelSelectionDialog dialog(models, summaries, spec_.model_version_id,
                                dialog_parent_);
    if (dialog.exec() != QDialog::Accepted) return;
    const std::string selected = dialog.selected_model_version_id();
    if (selected.empty()) return;
    spec_.model_version_id = selected;
    spec_.resolved = domain::Json::object();
    persist_spec();
    emit spec_changed();
    for (const auto& model : models) {
        if (model.model_version_id == selected) {
            emit status_message(QStringLiteral("已选择模型 %1 v%2（%3）")
                                    .arg(qs(model.model_id),
                                         qs(model.model_version),
                                         qs(model.provider)));
            break;
        }
    }
}

void PredictionWorkflowController::open_params() {
    PredictionParamsDialog dialog(spec_.params, dialog_parent_);
    if (dialog.exec() != QDialog::Accepted) return;
    spec_.params = dialog.params();
    persist_spec();
    emit spec_changed();
    emit status_message(
        dialog.params_changed()
            ? QStringLiteral("预测参数已更新")
            : QStringLiteral("预测参数未变化"));
}

bool PredictionWorkflowController::run() {
    if (binding_ == nullptr || seismic_page_ == nullptr) {
        emit status_message(QStringLiteral("预测后端未装配（closure-science 构建切片未接入）"));
        return false;
    }
    if (binding_->is_running()) {
        emit status_message(
            QStringLiteral("已有推断在运行（重复触发不会并发运行同一 "
                           "RunSpec）"));
        return false;
    }
    const SciencePageBinding::SpecRunResult result =
        binding_->start_spec_run(spec_, seismic_page_);
    if (!result.started) {
        QString joined;
        for (const auto& error : result.errors) {
            if (!joined.isEmpty()) joined += QStringLiteral("\n");
            joined += qs(error);
        }
        QMessageBox::warning(dialog_parent_, QStringLiteral("运行预测"),
                             QStringLiteral("预检未通过：\n%1").arg(joined));
        return false;
    }
    emit status_message(QStringLiteral("预测运行已启动（run %1）")
                            .arg(qs(result.run_id)));
    return true;
}

bool PredictionWorkflowController::cancel() {
    if (binding_ == nullptr) return false;
    if (!binding_->request_cancel()) {
        emit status_message(QStringLiteral("当前没有运行中的推断"));
        return false;
    }
    emit status_message(
        QStringLiteral("已请求取消：推断将在当前分块组完成后停止"));
    return true;
}

bool PredictionWorkflowController::is_running() const {
    return binding_ != nullptr && binding_->is_running();
}

void PredictionWorkflowController::persist_spec() {
    if (!seams_.write_run_spec) return;
    const domain::DataError error = seams_.write_run_spec(spec_.to_json());
    if (error.code != domain::ErrorCode::Ok) {
        emit status_message(QStringLiteral("预测运行配置保存失败: %1")
                                .arg(qs(error.message)));
    }
}

void PredictionWorkflowController::apply_seismic_selection(
    const std::string& resource_id) {
    if (spec_.seismic_resource_id.has_value() &&
        *spec_.seismic_resource_id == resource_id) {
        return;
    }
    spec_.seismic_resource_id = resource_id;
    persist_spec();
    emit spec_changed();
}

PredictionWorkflowController* install_prediction_workflow(
    SciencePageBinding* binding, WellLogPredictionPage* well_page,
    SeismicPredictionPage* seismic_page, QObject* parent) {
    return new PredictionWorkflowController(binding, well_page,
                                            seismic_page, parent);
}

}  // namespace pwb::closure_science::qt
