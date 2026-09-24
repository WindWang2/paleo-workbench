#include "prediction_workflow_install.hpp"

#include "app_context.hpp"
#include "app_shell.hpp"
#include "main_window.hpp"

#include <pwb/application/adapters/data_store.hpp>
#include <pwb/closure_science/qt/page_binding.hpp>
#include <pwb/closure_science/qt/prediction_workflow.hpp>
#include <pwb/closure_science/qt/well_seismic_link.hpp>
#include <pwb/domain/json.hpp>
#include <pwb/ui_ribbon/qt/ribbon_bar.hpp>
#include <pwb/ui_wellseis/qt/seismic_prediction_page.hpp>
#include <pwb/ui_wellseis/qt/well_log_prediction_page.hpp>

#include <QAction>
#include <QMainWindow>
#include <QObject>
#include <QSignalBlocker>
#include <QString>

#include <cmath>
#include <vector>

namespace pwb::app::prediction_workflow {

namespace {

using pwb::domain::Json;

std::vector<double> number_array(const Json& value) {
    std::vector<double> out;
    if (!value.is_array()) return out;
    for (const auto& item : value) {
        if (item.is_number()) {
            const double number = item.get<double>();
            if (std::isfinite(number)) out.push_back(number);
        }
    }
    return out;
}

// Recorded time-depth calibrations live in the project document
// coordinate.time_depth_calibrations array. Entry shape (the read side the
// ws1 link consumes; producers land with the calibration line):
//   { "well_resource_id": "...", "depth_m": [...], "twt_ms": [...] }
// Parallel arrays, >= 2 finite pairs. Anything else is not a calibration
// and the link stays honestly disabled for that well.
pwb::closure_science::qt::WellTimeDepthCalibration parse_calibration(
    const Json& entry) {
    pwb::closure_science::qt::WellTimeDepthCalibration table;
    const auto text = [&entry](const char* key) -> std::string {
        return entry.is_object() && entry.contains(key) &&
                       entry[key].is_string()
                   ? entry[key].get<std::string>()
                   : std::string();
    };
    table.well_resource_id = text("well_resource_id");
    if (table.well_resource_id.empty()) {
        table.well_resource_id = text("well_id");
    }
    table.well_name = text("well_name");
    if (entry.is_object()) {
        if (const auto depths = entry.find("depth_m");
            depths != entry.end()) {
            table.depths_m = number_array(*depths);
        }
        if (const auto twt = entry.find("twt_ms"); twt != entry.end()) {
            table.twt_ms = number_array(*twt);
        }
    }
    return table;
}

}  // namespace

void install(const Install& install) {
    auto* shell = install.shell;
    auto* window = install.window;
    auto* context = install.context;
    if (shell == nullptr || window == nullptr) return;

    // The binding main_window assembled (parent = shell): find it, never
    // rebuild a second inference stack.
    auto* binding =
        shell->findChild<pwb::closure_science::qt::SciencePageBinding*>();
    if (binding == nullptr || shell->well_log_page() == nullptr ||
        shell->seismic_page() == nullptr) {
        return;
    }

    auto* controller = shell->findChild<
        pwb::closure_science::qt::PredictionWorkflowController*>();
    if (controller != nullptr) return;  // idempotent install

    controller = pwb::closure_science::qt::install_prediction_workflow(
        binding, shell->well_log_page(), shell->seismic_page(), shell);
    controller->set_dialog_parent(window);

    // ---- project-document seams (RunSpec persistence) ------------------
    pwb::closure_science::qt::PredictionWorkflowController::ProjectSeams
        seams;
    seams.read_run_spec = [context]() -> Json {
        const auto store =
            context != nullptr ? context->projectStore() : nullptr;
        if (store == nullptr) return Json(nullptr);
        return store->coordinator().document_section(
            "prediction_run_spec", store->document());
    };
    seams.write_run_spec = [context](const Json& spec) {
        const auto store =
            context != nullptr ? context->projectStore() : nullptr;
        if (store == nullptr) {
            return pwb::domain::DataError(
                pwb::domain::ErrorCode::NotFound, "没有已打开的工程");
        }
        store->coordinator().set_document_section(
            "prediction_run_spec", spec, store->document());
        return store->save_document();
    };
    controller->set_project_seams(std::move(seams));

    // ---- time-depth calibration provider (predict.link gate) -----------
    controller->link()->set_calibration_provider(
        [context](const std::string& well_resource_id)
        -> std::optional<pwb::closure_science::qt::WellTimeDepthCalibration> {
            const auto store =
                context != nullptr ? context->projectStore() : nullptr;
            if (store == nullptr) return std::nullopt;
            const Json section = store->coordinator().document_section(
                "coordinate", store->document());
            if (!section.is_object()) return std::nullopt;
            const auto it = section.find("time_depth_calibrations");
            if (it == section.end() || !it->is_array()) return std::nullopt;
            for (const auto& entry : *it) {
                auto table = parse_calibration(entry);
                if (table.well_resource_id == well_resource_id &&
                    table.valid()) {
                    return table;
                }
            }
            return std::nullopt;
        });

    QObject::connect(
        controller, &pwb::closure_science::qt::PredictionWorkflowController::
                        status_message,
        shell, &AppShell::status_message);

    // ---- predict.link ribbon toggle (the same QAction the command
    // callback triggers — one state owner: the link controller) ---------
    if (shell->ribbon() != nullptr) {
        auto* link_action = new QAction(QStringLiteral("联动"), shell);
        link_action->setObjectName(QStringLiteral("PredictLinkToggle"));
        link_action->setCheckable(true);
        link_action->setEnabled(
            controller->link()->is_available());
        QObject::connect(
            link_action, &QAction::triggered, controller->link(),
            [controller]() {
                controller->link()->set_enabled(
                    !controller->link()->is_enabled());
            });
        QObject::connect(
            controller->link(),
            &pwb::closure_science::qt::WellSeismicLinkController::
                link_enabled_changed,
            link_action, [link_action](bool on) {
                const QSignalBlocker block(link_action);
                link_action->setChecked(on);
            });
        QObject::connect(
            controller->link(),
            &pwb::closure_science::qt::WellSeismicLinkController::
                link_availability_changed,
            link_action, &QAction::setEnabled);
        shell->ribbon()->set_command_action(QStringLiteral("predict.link"),
                                            link_action);
    }

    // ---- prediction_tasks project-document publish ----------------------
    // The run already lands DERIVED versions + DataRun rows in the catalog;
    // this publishes the materialized TASK into the project document so
    // ws2/ws3 overlays, the m5 comparison and the pages' own update_state
    // (all readers of root "prediction_tasks") see finished runs — and
    // reopen keeps them (the section persists with the project).
    binding->set_publish_task([context](const Json& task) {
        const auto store =
            context != nullptr ? context->projectStore() : nullptr;
        if (store == nullptr) {
            return pwb::domain::DataError(
                pwb::domain::ErrorCode::NotFound, "没有已打开的工程");
        }
        Json section = store->coordinator().document_section(
            "prediction_tasks", store->document());
        if (!section.is_array()) section = Json::array();
        const std::string task_id =
            task.is_object() && task.contains("id") && task["id"].is_string()
                ? task["id"].get<std::string>()
                : std::string();
        // Replace-by-id (never duplicate on a re-publish).
        bool replaced = false;
        for (auto& row : section) {
            if (row.is_object() && row.contains("id") &&
                row["id"].is_string() &&
                row["id"].get<std::string>() == task_id) {
                row = task;
                replaced = true;
                break;
            }
        }
        if (!replaced) section.push_back(task);
        store->coordinator().set_document_section(
            "prediction_tasks", section, store->document());
        return store->save_document();
    });

    // Restore the spec persisted for the currently open project (a later
    // project switch re-runs via notify_project_changed).
    controller->restore_persisted_spec();
}

void notify_project_changed(QMainWindow* window) {
    if (window == nullptr) return;
    if (auto* controller = window->findChild<
            pwb::closure_science::qt::PredictionWorkflowController*>();
        controller != nullptr) {
        // No cross-project spec leakage: the draft resets to whatever the
        // new project recorded (or defaults)...
        controller->restore_persisted_spec();
        // ...and the well-seismic link re-anchors: the previous project's
        // calibration table must never keep a live link converting.
        controller->link()->refresh();
    }
}

}  // namespace pwb::app::prediction_workflow
