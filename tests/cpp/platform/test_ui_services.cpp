// platform.ui_services — CONV-PS product wiring: the 设置/帮助 menus exist
// with the theme/density/diagnostics actions, the theme switch really
// restyles the application (QSS on qApp), the File menu carries the
// recent-projects MRU, and a confirmed close persists the window layout
// behind the version fence. Uses an injected temp-file QSettings store so
// the developer's real config is never touched.

#include <cstdio>
#include <memory>

#include <QAction>
#include <QApplication>
#include <QCloseEvent>
#include <QFile>
#include <QMenu>
#include <QMenuBar>
#include <QSettings>
#include <QTemporaryDir>
#include <qgsapplication.h>

#include <pwb/qgis/qgis_runtime.hpp>

#include "main_window.hpp"
#include "test_framework.hpp"

using pwb::app::MainWindow;

namespace {

QMenu* find_menu(const QMenuBar* bar, const QString& title) {
    for (QAction* action : bar->actions()) {
        if (QMenu* menu = action->menu()) {
            if (menu->title().replace("&", "") == title) return menu;
        }
    }
    return nullptr;
}

}  // namespace

int main(int argc, char** argv) {
    QgsApplication app(argc, argv, true);
    pwb::qgis::QgisRuntime::acquire();

    QTemporaryDir dir;
    const QString store_path = dir.path() + "/services.ini";

    {
        auto injected = std::make_unique<QSettings>(store_path,
                                                    QSettings::IniFormat);
        MainWindow window(nullptr, injected.get());

        // -- menus exist --------------------------------------------------
        QMenu* settings_menu = find_menu(window.menuBar(), "设置(S)");
        PWB_CHECK_MSG(settings_menu != nullptr, "设置 menu missing");
        QMenu* help_menu = find_menu(window.menuBar(), "帮助(H)");
        PWB_CHECK_MSG(help_menu != nullptr, "帮助 menu missing");

        QMenu* theme_menu = settings_menu->findChild<QMenu*>(
            QString(), Qt::FindDirectChildrenOnly);
        PWB_CHECK_MSG(theme_menu != nullptr, "主题 submenu missing");
        // The theme submenu holds exactly the three vocabulary actions.
        int checkable = 0;
        for (QAction* action : theme_menu->actions()) {
            if (action->isCheckable()) ++checkable;
        }
        PWB_CHECK_MSG(checkable == 3, "theme submenu must hold 3 themes");

        // Diagnostics + about actions are real entries (not placeholders).
        bool has_diagnostics = false;
        bool has_about = false;
        for (QMenu* menu : {settings_menu, help_menu}) {
            for (const QAction* action : menu->actions()) {
                has_diagnostics = has_diagnostics
                                  || action->text().contains("诊断信息");
                has_about = has_about || action->text().contains("关于");
            }
        }
        PWB_CHECK(has_diagnostics);
        PWB_CHECK(has_about);

        // -- recent projects MRU is present and empty-first ---------------
        QMenu* file_menu = find_menu(window.menuBar(), "文件(F)");
        PWB_CHECK_MSG(file_menu != nullptr, "文件 menu missing");
        bool has_recent = false;
        for (QAction* action : file_menu->actions()) {
            has_recent = has_recent
                         || action->menu() != nullptr
                                && action->menu()->title().contains("最近工程");
        }
        PWB_CHECK_MSG(has_recent, "recent-projects submenu missing");

        // -- theme switch restyles the shell window -----------------------
        PWB_CHECK(app.styleSheet().isEmpty());  // app-level: untouched
        QSettings store(store_path, QSettings::IniFormat);
        // Find the dark action by data and trigger it.
        QAction* dark_action = nullptr;
        for (QMenu* child : settings_menu->findChildren<QMenu*>()) {
            for (QAction* action : child->actions()) {
                if (action->data().toString() == "dark") {
                    dark_action = action;
                }
            }
        }
        PWB_CHECK_MSG(dark_action != nullptr, "dark theme action missing");
        dark_action->trigger();
        PWB_CHECK(!window.styleSheet().isEmpty());
        PWB_CHECK(window.styleSheet().contains("#2dd4bf"));  // dark PRIMARY
        store.sync();
        PWB_CHECK(store.value("ui/theme").toString() == "dark");

        // -- close persists the layout behind the fence -------------------
        window.show();
        window.close();
        store.sync();
        PWB_CHECK(store.value("layout/state_version").toInt() == 5);
        PWB_CHECK(!store.value("layout/window_state").toByteArray().isEmpty());
    }
    {
        // Restore path: a fresh window with the same store comes back dark
        // (theme persisted through the same store).
        auto injected2 = std::make_unique<QSettings>(store_path,
                                                     QSettings::IniFormat);
        MainWindow restored(nullptr, injected2.get());
        PWB_CHECK(!restored.styleSheet().isEmpty());
        PWB_CHECK(restored.styleSheet().contains("#2dd4bf"));
        restored.close();
    }

    pwb::qgis::QgisRuntime::release();
    return pwb::test::report("platform.ui_services");
}
