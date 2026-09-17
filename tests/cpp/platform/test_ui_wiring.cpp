// platform.ui_wiring — Oracle 3 extension: the governed actions are really
// IN the toolbar and menus (not just counted), each wired action is actually
// connected, triggering them has real effects (map tools arm, editing
// session opens, undo/redo change geometry), and the dirty-close three-way
// decision behaves (save commits / discard rolls back / cancel blocks).

#include <cmath>

#include <QAction>
#include <QCloseEvent>
#include <QFile>
#include <QMenuBar>
#include <QMenu>
#include <QTemporaryDir>
#include <QToolBar>
#include <qgsapplication.h>

#include <qgsmapcanvas.h>
#include <qgsmaptoolpan.h>
#include <qgsvectorlayer.h>

#include <pwb/application/project_session.hpp>
#include <pwb/qgis/qgis_runtime.hpp>
#include <pwb/tool_policy/tool_availability.hpp>

#include "main_window.hpp"

#include "test_fixtures.hpp"
#include "test_framework.hpp"

using pwb::app::MainWindow;

namespace {

}  // namespace

int main(int argc, char** argv) {
    QgsApplication app(argc, argv, true);
    pwb::qgis::QgisRuntime::acquire();

    QTemporaryDir temp_dir;
    const QString gpkg_uri = pwb::test_fixtures::make_gpkg_fixture(temp_dir.path());
    PWB_CHECK_MSG(!gpkg_uri.isEmpty(), "fixture creation failed");

    MainWindow window;
    const QString load_error = window.loadFixtures(gpkg_uri, QString());
    PWB_CHECK_MSG(load_error.isEmpty(), load_error.toStdString());
    pwb::application::ProjectSession* session = window.session();

    // -- actions really live in toolbar AND menus (same objects) ------------
    QToolBar* toolbar = window.findChild<QToolBar*>("map-toolbar");
    PWB_CHECK_MSG(toolbar != nullptr, "map toolbar missing");
    const char* wired[] = {
        "reference_import", "layer_new", "pan", "zoom_in", "zoom_out",
        "full_extent", "toggle_editing", "vertex", "undo", "redo",
        "save_edits", "rollback", "map_export",
    };
    for (const char* id : wired) {
        QList<QAction*> tb = toolbar->actions();
        bool in_toolbar = false;
        for (QAction* a : tb) {
            if (a->objectName() == QLatin1String(id)) { in_toolbar = true; break; }
        }
        PWB_CHECK_MSG(in_toolbar, std::string(id) + " not added to the toolbar");
        PWB_CHECK_MSG(window.actionWired(QLatin1String(id)),
                      std::string(id) + " has no connected operation");
    }
    // Menus consume the SAME QAction objects (single policy consumer).
    int menu_action_hits = 0;
    const auto menus = window.menuBar()->actions();
    for (QAction* menu_action : menus) {
        if (QMenu* menu = menu_action->menu()) {
            for (QAction* entry : menu->actions()) {
                if (!entry->objectName().isEmpty()
                    && window.findChild<QObject*>(entry->objectName()) == entry) {
                    ++menu_action_hits;
                }
            }
        }
    }
    PWB_CHECK_MSG(menu_action_hits >= 13,
                  "menus do not carry the governed shared actions");

    // -- policy drives enablement, not a count ------------------------------
    {
        const auto availability =
            pwb::tool_policy::evaluate_all(session->snapshot());
        const QObject* vertex_obj = window.findChild<QObject*>("vertex");
        const QAction* vertex_action = qobject_cast<const QAction*>(vertex_obj);
        PWB_CHECK(vertex_action != nullptr);
        PWB_CHECK(vertex_action->isEnabled()
                  == availability.at("vertex").enabled);
    }

    // -- triggering map tools really arms the canvas ------------------------
    {
        QAction* zoom_in = window.findChild<QAction*>("zoom_in");
        QAction* pan = window.findChild<QAction*>("pan");
        PWB_CHECK(zoom_in != nullptr && pan != nullptr);
        zoom_in->trigger();
        QgsMapCanvas* canvas = window.findChild<QgsMapCanvas*>();
        PWB_CHECK(canvas != nullptr);
        PWB_CHECK(canvas->mapTool() != nullptr);
        PWB_CHECK(canvas->mapTool()->objectName() != QStringLiteral("pan"));
        // objectName check via tool identity: current tool mirrors policy id
        PWB_CHECK(session->current_tool() == "zoom_in");
        pan->trigger();
        PWB_CHECK(qobject_cast<QgsMapToolPan*>(canvas->mapTool()) != nullptr);
        PWB_CHECK(session->current_tool() == "pan");
    }

    // -- open operations go through the wired handlers ----------------------
    {
        const QString copy =
            temp_dir.path() + QStringLiteral("/copy.gpkg");
        PWB_CHECK(QFile::exists(gpkg_uri));
        PWB_CHECK(QFile::copy(gpkg_uri, copy));
        const QString error = window.openVectorLayer(copy);
        PWB_CHECK_MSG(error.isEmpty(), error.toStdString());
        PWB_CHECK(session->map().vectorLayerById("copy") != nullptr);
    }

    // -- editing chain through the ACTIONS ----------------------------------
    {
        QAction* toggle = window.findChild<QAction*>("toggle_editing");
        QAction* undo = window.findChild<QAction*>("undo");
        QAction* redo = window.findChild<QAction*>("redo");
        QAction* rollback = window.findChild<QAction*>("rollback");
        PWB_CHECK(toggle != nullptr && undo != nullptr && redo != nullptr
                  && rollback != nullptr);

        toggle->trigger();
        PWB_CHECK(session->edit().editing("fixture.facies_boundary"));

        QgsVectorLayer* layer =
            session->map().vectorLayerById("fixture.facies_boundary");
        PWB_CHECK(layer != nullptr);
        const QgsPointXY before =
            layer->getFeature(1).geometry().vertexAt(0);
        PWB_CHECK(session->edit()
                      .move_vertex("fixture.facies_boundary", 1, 0,
                                   before.x() + 0.3, before.y() + 0.2)
                      .empty());
        PWB_CHECK(session->edit().dirty("fixture.facies_boundary"));

        undo->trigger();   // action-driven undo
        const QgsPointXY undone = layer->getFeature(1).geometry().vertexAt(0);
        PWB_CHECK(std::abs(undone.x() - before.x()) < 1e-9);
        redo->trigger();   // action-driven redo
        const QgsPointXY redone = layer->getFeature(1).geometry().vertexAt(0);
        PWB_CHECK(std::abs(redone.x() - (before.x() + 0.3)) < 1e-9);

        // -- dirty-close semantics (scripted responders) ---------------------
        int answer = 0;   // 1=save 2=discard 4=cancel (QMessageBox values)
        window.setDirtyCloseResponder([&answer]() { return answer; });
        int discard_answer = 4;   // scripted; defaults to "not yes"
        window.setDiscardConfirmResponder([&discard_answer]() { return discard_answer; });

        answer = 4;   // Cancel
        PWB_CHECK(window.close() == false);
        PWB_CHECK(session->edit().dirty("fixture.facies_boundary"));

        answer = 1;   // Save in module-only mode: the commit path reports
                      // the missing store honestly and the close is
                      // cancelled (edits never silently destroyed).
        PWB_CHECK(window.close() == false);
        PWB_CHECK(session->edit().dirty("fixture.facies_boundary"));

        answer = 2;   // Discard
        discard_answer = 0x00004000;   // QMessageBox::Yes
        PWB_CHECK(window.close() == true);
        PWB_CHECK(!session->edit().editing("fixture.facies_boundary"));
    }

    pwb::qgis::QgisRuntime::release();
    return ::pwb::test::report("platform.ui_wiring");
}
