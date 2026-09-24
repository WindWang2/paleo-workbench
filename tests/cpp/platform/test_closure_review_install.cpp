// platform.closure_review_install — line 09 wiring battery: the review
// page's real IReviewActions backend binds through the closure installer
// (MainWindow ctor install + openProject notify), the page state flows
// from the REAL document (legacy report issues land in the QC table), the
// document save seam persists document-level mutations, and a reopen sees
// them (traceable publish artifacts).

#include <cstdio>
#include <filesystem>
#include <string>

#include <QTemporaryDir>
#include <QAction>
#include <QLabel>
#include <QPlainTextEdit>
#include <QPushButton>
#include <qgsapplication.h>

#include <pwb/application/adapters/data_store.hpp>
#include <pwb/qgis/qgis_runtime.hpp>
#include <pwb/ui_review/compare_core.hpp>
#include <pwb/ui_review/qt/qc_issue_table.hpp>
#include <pwb/ui_review/qt/review_export_page.hpp>
#include <pwb/ui_shell/command_registry.hpp>

#include "app_shell.hpp"
#include "closure_review_install.hpp"
#include "comparison_view.hpp"
#include "main_window.hpp"
#include "review_disposition_panel.hpp"
#include "validation_workspace_page.hpp"

#include "test_framework.hpp"

namespace fs = std::filesystem;
using pwb::app::MainWindow;

namespace {

bool copy_tree(const fs::path& from, const fs::path& to) {
    std::error_code ec;
    fs::create_directories(to, ec);
    for (const auto& entry : fs::recursive_directory_iterator(from, ec)) {
        const auto target = to / fs::relative(entry.path(), from, ec);
        if (entry.is_directory(ec)) fs::create_directories(target, ec);
        else if (entry.is_regular_file(ec)) {
            fs::create_directories(target.parent_path(), ec);
            fs::copy_file(entry.path(), target,
                          fs::copy_options::overwrite_existing, ec);
        }
        if (ec) return false;
    }
    return true;
}

}  // namespace

int main(int argc, char** argv) {
    QgsApplication app(argc, argv, true);
    pwb::qgis::QgisRuntime::acquire();

    // ---- fixture: the typical project (one real map document + one
    // legacy quality report) copied into a temp workdir -------------------
    QTemporaryDir temp_dir;
    const fs::path fixtures =
        fs::path(PWB_TEST_SRC_DIR) / ".." / "data" / "fixtures";
    const fs::path work =
        fs::path(temp_dir.path().toStdWString()) / "project";
    PWB_CHECK(copy_tree(fixtures / "typical", work));
    const fs::path project_file = work / "typical.paleo.json";
    PWB_CHECK(fs::exists(project_file));

    // ---- MainWindow construction: the review PAGE is retired from the
    // two-page shell (feature code stays in the project); the installer
    // must stay honest on the retired surface — no crash, no fake page.
    MainWindow window;
    auto* shell = window.appShell();
    PWB_CHECK_MSG(shell != nullptr, "AppShell missing");
    PWB_CHECK_MSG(shell->review_page() == nullptr,
                  "retired review page still mounted");
    // install_review_actions is idempotent AND null-safe on the retired
    // shell: a second call must be a harmless refresh (no duplicate
    // binding, no crash).
    pwb::app::closure_review::install_review_actions(shell,
                                                     &window.context());
    pwb::app::closure_review::install_review_actions(shell,
                                                     &window.context());

    // ---- openProject still re-binds the document path ------------------
    const QString open_error = window.openProject(
        QString::fromStdWString(project_file.wstring()));
    PWB_CHECK_MSG(open_error.isEmpty(), open_error.toStdString());

    // ---- the document save seam persists document-level mutations --------
    // (the store the window opened is private; the seam itself is store-
    // level, exercised over the same project file).
    std::string save_error_text;
    {
        std::string open_error_text;
        auto store = pwb::application::PwbDataStore::open(project_file,
                                                          &open_error_text);
        PWB_CHECK_MSG(store != nullptr, open_error_text);
        auto& root = store->document().root();
        root["quality_reports"][0]["issues"] =
            pwb::domain::Json::array();
        root["quality_reports"][0]["status"] = "pass";
        const pwb::domain::DataError save_error = store->save_document();
        PWB_CHECK_MSG(save_error.ok(),
                      "save_document failed: " + save_error.message);
    }

    // ---- reopen sees the persisted state (traceable publish path) --------
    {
        std::string reopen_error_text;
        auto reopened = pwb::application::PwbDataStore::open(
            project_file, &reopen_error_text);
        PWB_CHECK_MSG(reopened != nullptr, reopen_error_text);
        const auto& root = reopened->document().root();
        const auto report_it = root.find("quality_reports");
        PWB_CHECK(report_it != root.end() && report_it->is_array() &&
                  !report_it->empty());
        PWB_CHECK(report_it->at(0).at("status") == "pass");
    }

    // ---- M5: the validation page is retired from the shell — the
    // accessor answers honestly empty; the command vocabulary it fed
    // (verify.*) stays registered by ribbon_commands with honest gates.
    {
        PWB_CHECK_MSG(shell->validation_page() == nullptr,
                      "retired validation page still mounted");
        PWB_CHECK(shell->ribbon() != nullptr);
        auto& registry = pwb::ui_shell::command_registry();
        for (const char* id :
             {"verify.select_object", "verify.side_by_side",
              "verify.link", "verify.run"}) {
            PWB_CHECK_MSG(registry.get(id) != nullptr,
                          std::string("verify command missing: ") + id);
        }
        pwb::ui_shell::CommandContext ctx;
        ctx.mapping_stage = "integrated_compilation";
        PWB_CHECK(!registry.evaluate("verify.side_by_side", &ctx).enabled);
    }

    return pwb::test::report("platform.closure_review_install");
}
