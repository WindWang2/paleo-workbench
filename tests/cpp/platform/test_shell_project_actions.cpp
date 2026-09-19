// platform.shell_project_actions — cpp-close-12 battery: the UI-17
// deferred request surfaces against a real store-backed session.
//   * save/reopen roundtrip through the three-phase ProjectManager save;
//   * sample bootstrap through the real newProject lifecycle + the builtin
//     wells publish (catalog version + persisted workspace binding);
//   * the one-project-session contract guard;
//   * the properties summary and the shared preview-settings dialog on the
//     unified platform settings store.

#include <QDialog>
#include <QPushButton>
#include <QSettings>
#include <QTemporaryDir>
#include <qgsapplication.h>

#include <filesystem>
#include <fstream>
#include <system_error>

#include <pwb/application/adapters/data_store.hpp>
#include <pwb/application/project_session.hpp>
#include <pwb/qgis/qgis_runtime.hpp>
#ifdef PWB_WITH_UI_PAGES_PREVIEW_QT
#include <pwb/ui_pages_preview/preview_settings.hpp>
#include <pwb/ui_pages_preview/qt/preview_settings_panel.hpp>
#endif

#include "app_context.hpp"
#include "main_window.hpp"
#include "shell_project_actions.hpp"

#include "test_framework.hpp"

using pwb::app::MainWindow;

namespace {

std::string slurp(const std::filesystem::path& path) {
    std::ifstream in(path, std::ios::binary);
    return std::string((std::istreambuf_iterator<char>(in)),
                       std::istreambuf_iterator<char>());
}

}  // namespace

int main(int argc, char** argv) {
    QgsApplication app(argc, argv, true);
    pwb::qgis::QgisRuntime::acquire();

    QTemporaryDir temp_dir;
    PWB_CHECK_MSG(temp_dir.isValid(), "temp dir invalid");

    // -------------------------------------------------- no-project state --
    {
        MainWindow window;
        QString captured;
        window.setPropertiesResponder(
            [&captured](const QString& text) { captured = text; });
        window.showProjectProperties();
        PWB_CHECK_MSG(captured.contains(QString::fromUtf8("没有打开的工程")),
                      "properties on an empty window must answer honestly");

        const QString save_error =
            pwb::app::shell_project_actions::save_open_project(window);
        PWB_CHECK_MSG(!save_error.isEmpty(),
                      "save without a project must refuse, not fake success");
    }

    // ------------------------------- sample bootstrap + save roundtrip ---
    QString project_file_text;
    {
        MainWindow window;
        const QString sample_dir =
            temp_dir.path() + QStringLiteral("/sample");
        const QString error =
            pwb::app::shell_project_actions::bootstrap_sample_project(
                window, sample_dir);
        PWB_CHECK_MSG(error.isEmpty(), error.toStdString());

        auto* store = window.context().projectStore().get();
        PWB_CHECK_MSG(store != nullptr, "sample bootstrap left no store");
        const std::filesystem::path project_file = store->project_file();
        PWB_CHECK(std::filesystem::exists(project_file));

        // The wells version is in the catalog and the workspace binding
        // survived the save (close/reopen materialization contract).
        auto snapshot = store->snapshot();
        PWB_CHECK_MSG(snapshot.is_ok(), snapshot.error().message);
        bool wells_version = false;
        for (const auto& version : snapshot.value().catalog_versions) {
            if (version.format == "GeoJSON") wells_version = true;
        }
        PWB_CHECK(wells_version);
        project_file_text = QString::fromStdString(slurp(project_file));
        PWB_CHECK_MSG(project_file_text.contains("sample.wells"),
                      "workspace binding missing from the saved project");
        PWB_CHECK_MSG(project_file_text.contains(
                          QString::fromUtf8("惠西南样例工程")),
                      "sample project name missing");

        // One project session per window: a second bootstrap refuses.
        const QString again =
            pwb::app::shell_project_actions::bootstrap_sample_project(
                window, temp_dir.path() + QStringLiteral("/sample-2"));
        PWB_CHECK_MSG(again.contains(QString::fromUtf8("已有工程打开")),
                      "second bootstrap must honour the session contract");

        // Document-level edit reaches the disk through the save path.
        auto meta = store->document().meta();
        PWB_CHECK(meta.has_value());
        store->document().root()["meta"]["region"] = "惠西南测试区";
        QString saved_to;
        const QString save_error =
            pwb::app::shell_project_actions::save_open_project(window,
                                                               &saved_to);
        PWB_CHECK_MSG(save_error.isEmpty(), save_error.toStdString());
        PWB_CHECK(saved_to == QString::fromStdString(project_file.string()));
        const QString after_save =
            QString::fromStdString(slurp(project_file));
        PWB_CHECK_MSG(after_save.contains(QString::fromUtf8("惠西南测试区")),
                      "saved file missing the document mutation");
    }

    // Reopen: the sample project comes back with its binding.
    {
        const std::filesystem::path sample_dir =
            std::filesystem::path(temp_dir.path().toStdWString()) / "sample";
        std::filesystem::path project_file;
        std::error_code ec;
        for (const auto& entry :
             std::filesystem::directory_iterator(sample_dir, ec)) {
            if (entry.path().extension() == ".json" &&
                entry.path().string().ends_with(".paleo.json")) {
                project_file = entry.path();
                break;
            }
        }
        PWB_CHECK_MSG(!project_file.empty(),
                      "sample project file not found for reopen");

        MainWindow window;
        const QString error =
            window.openProject(QString::fromStdString(project_file.string()));
        PWB_CHECK_MSG(error.isEmpty(), error.toStdString());
        auto* store = window.context().projectStore().get();
        PWB_CHECK_MSG(store != nullptr, "reopen left no store");
        auto snapshot = store->snapshot();
        PWB_CHECK_MSG(snapshot.is_ok(), snapshot.error().message);
        bool wells_binding = false;
        for (const auto& binding : snapshot.value().layer_bindings) {
            if (binding.layer_id == "sample.wells") wells_binding = true;
        }
        PWB_CHECK_MSG(wells_binding,
                      "sample.wells binding lost across reopen");
    }

#ifdef PWB_WITH_UI_PAGES_PREVIEW_QT
    // ------------------------------------ preview settings (UI-07 tie) ---
    {
        const QString settings_path =
            temp_dir.path() + QStringLiteral("/preview-settings.ini");
        QSettings services(settings_path, QSettings::IniFormat);
        MainWindow window(nullptr, &services);
        window.showPreviewSettingsRequested();
        auto* dialog = window.findChild<QDialog*>(
            QStringLiteral("PreviewSettingsDialog"));
        PWB_CHECK_MSG(dialog != nullptr, "preview settings dialog missing");
        auto* panel = dialog->findChild<
            pwb::ui_pages_preview::PreviewSettingsPanel*>();
        PWB_CHECK_MSG(panel != nullptr, "settings panel missing");
        auto settings = pwb::ui_pages_preview::PreviewSettings::defaults();
        settings.font_size = 15;
        settings.wrap_text = true;
        panel->set_settings(settings);
        // Apply persists through the panel's store and accepts the dialog.
        panel->apply_button()->click();
        services.sync();
        QSettings verify(settings_path, QSettings::IniFormat);
        verify.beginGroup(
            pwb::ui_pages_preview::PreviewSettingsStore::group_key());
        PWB_CHECK(verify.value("font_size", 0).toInt() == 15);
        PWB_CHECK(verify.value("wrap_text", false).toBool());
        verify.endGroup();
    }
#endif

    pwb::qgis::QgisRuntime::release();
    return ::pwb::test::report("platform.shell_project_actions");
}
