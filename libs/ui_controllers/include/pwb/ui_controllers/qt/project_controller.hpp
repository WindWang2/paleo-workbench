#pragma once

// UI-14 — ProjectController Qt shell (project_controller.py QObject
// surface parity).
//
// Owns ProjectControllerCore + the save JobOwnerRunner and binds the
// host seams onto real Qt surfaces: QFileDialog/QMessageBox for the
// dialog seams, QTimer::singleShot(0) for the next-turn marshal; the
// save job runs on the QGIS task bridge (JobOwnerRunner). The
// window/app_shell attributes
// (document, project_path, page refresh hooks) stay injected — the
// integration adapter binds them through the *_api() accessors before
// first core() use; rebind() re-creates the core for late binds.

#include <QObject>

#include <filesystem>
#include <functional>
#include <memory>
#include <optional>
#include <string>

#include <pwb/ui_controllers/project_controller.hpp>

class QWidget;

namespace pwb::ui_controllers::qt {

class JobOwnerRunner;

class ProjectController : public QObject {
    Q_OBJECT
public:
    // The save job runs through a JobOwnerRunner over the QGIS task
    // bridge (process-shared gate when installed, else straight to
    // QgsTaskManager).
    explicit ProjectController(QObject* parent = nullptr);
    ~ProjectController() override;

    // The seam bags the integration adapter fills (bind before first
    // core() use — the core takes them by value).
    ProjectHostApi& host_api() { return host_; }
    CatalogRuntimeApi& catalog_api() { return catalog_; }
    ProjectServiceApi& services() { return services_; }
    ProjectSaveApiFactory& save_factory() { return save_factory_; }

    // Lazily materializes the core. rebind() drops the current one — its
    // session bookkeeping (generation, drained-save state) resets, so
    // callers rebind only between sessions.
    ProjectControllerCore& core();
    void rebind() { core_.reset(); }

    // Bind the Qt dialog seams (QFileDialog/QMessageBox) against `parent`.
    void bind_dialogs(QWidget* parent);

    // ---- operations (project_controller.py method parity) --------------
    bool end_current_session() { return core().end_current_session(); }
    bool shutdown_current_session() {
        return core().shutdown_current_session();
    }
    void new_project(const QString& name = QStringLiteral("Untitled Project")) {
        core().new_project(name.toStdString());
    }
    bool open_project_path(const std::filesystem::path& path) {
        return core().open_project_path(path);
    }
    bool open_sample_project(
        const std::optional<std::filesystem::path>& data_root =
            std::nullopt) {
        return core().open_sample_project(data_root);
    }
    std::optional<std::filesystem::path> save_project() {
        return core().save_project();
    }
    bool save_project_async() { return core().save_project_async(); }
    std::optional<std::filesystem::path> save_project_as(
        const std::optional<std::filesystem::path>& path) {
        return core().save_project_as(path);
    }
    bool save_job_running() { return core().save_job_running(); }
    bool drain_save_job(int wait_ms = 2000) {
        return core().drain_save_job(wait_ms);
    }

private:
    std::unique_ptr<JobOwnerRunner> save_runner_;
    std::unique_ptr<ProjectControllerCore> core_;
    ProjectHostApi host_;
    ProjectServiceApi services_;
    CatalogRuntimeApi catalog_;
    ProjectSaveApiFactory save_factory_;
};

}  // namespace pwb::ui_controllers::qt
