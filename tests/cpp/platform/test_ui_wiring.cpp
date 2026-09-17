// platform.ui_wiring — Oracle 3 extension: the governed actions are really
// IN the toolbar and menus (not just counted), each wired action is actually
// connected, triggering them has real effects (map tools arm, editing
// session opens, undo/redo change geometry), and the dirty-close three-way
// decision behaves (save commits / discard rolls back / cancel blocks).

#include <cmath>
#include <cstdio>

#include <QAction>
#include <QCloseEvent>
#include <QFile>
#include <QDir>
#include <QMenuBar>
#include <QMessageBox>
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
    // Show the window: QWidget::close() only carries the documented
    // closeEvent semantics for visible windows, and this test asserts them.
    window.show();
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
                    && window.governedAction(entry->objectName()) == entry) {
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
        const QAction* vertex_action = window.governedAction("vertex");
        PWB_CHECK(vertex_action != nullptr);
        PWB_CHECK(vertex_action->isEnabled()
                  == availability.at("vertex").enabled);
    }

    // -- triggering map tools really arms the canvas ------------------------
    QgsMapCanvas* canvas = window.findChild<QgsMapCanvas*>();
    {
        QAction* zoom_in = window.governedAction("zoom_in");
        QAction* pan = window.governedAction("pan");
        PWB_CHECK(zoom_in != nullptr && pan != nullptr);
        PWB_CHECK(canvas != nullptr);
        zoom_in->trigger();
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
        QDir().mkpath(temp_dir.path() + "/second");
        const QString second =
            pwb::test_fixtures::make_gpkg_fixture(temp_dir.path()
                                                  + "/second");
        PWB_CHECK(!second.isEmpty());
        const QString error = window.openVectorLayer(second);
        PWB_CHECK_MSG(error.isEmpty(), error.toStdString());
        // Layer id = completeBaseName of the fixture file ("fixture.gpkg").
        PWB_CHECK(session->map().vectorLayerById("fixture") != nullptr);
        PWB_CHECK(session->active_layer()->layer_id == "fixture");
    }

    // -- editing chain through the ACTIONS ----------------------------------
    // The open switched the active layer; the edit chain targets the first
    // fixture — restore it through the session's unified setter.
    {
        pwb::application::DomainLayerFacts facts;
        facts.layer_id = "fixture.facies_boundary";
        facts.role = "facies_boundary";
        facts.write_granted = true;
        facts.artifact_maturity = "draft";
        session->set_active_layer(facts);
        PWB_CHECK(session->active_layer()->layer_id
                  == "fixture.facies_boundary");
    }
    {
        QAction* toggle = window.governedAction("toggle_editing");
        QAction* undo = window.governedAction("undo");
        QAction* redo = window.governedAction("redo");
        QAction* rollback = window.governedAction("rollback");
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
        // Direct API edits skip the vertex tool's refresh; mirror it here
        // (the action states must track the edit buffer).
        window.refreshActionStates();
        PWB_CHECK(undo->isEnabled());

        undo->trigger();   // action-driven undo
        const QgsPointXY undone = layer->getFeature(1).geometry().vertexAt(0);
        PWB_CHECK(std::abs(undone.x() - before.x()) < 1e-9);
        redo->trigger();   // action-driven redo
        const QgsPointXY redone = layer->getFeature(1).geometry().vertexAt(0);
        PWB_CHECK(std::abs(redone.x() - (before.x() + 0.3)) < 1e-9);

        // -- dirty-close semantics (scripted responders) ---------------------
        // StandardButton values are bit flags — script them symbolically.
        int answer = 0;
        window.setDirtyCloseResponder([&answer]() { return answer; });
        int discard_answer = 0;   // scripted; defaults to "not yes"
        window.setDiscardConfirmResponder([&discard_answer]() { return discard_answer; });

        // Cancel: nothing changes, the close is refused.
        answer = QMessageBox::Cancel;
        PWB_CHECK(window.close() == false);
        PWB_CHECK(session->edit().dirty("fixture.facies_boundary"));

        // Module-only Save: the platform commit (working copy + staged
        // GeoJSON) succeeds and the missing catalog store is reported
        // honestly — the close is cancelled, the staged asset survives on
        // disk (edits never silently destroyed), the edit session ended
        // with the commit.
        answer = QMessageBox::Save;
        PWB_CHECK(window.close() == false);
        PWB_CHECK(!session->edit().editing("fixture.facies_boundary"));
        const std::filesystem::path staged_probe =
            std::filesystem::temp_directory_path() / "pwb-platform" / "staged"
            / "fixture.facies_boundary.geojson";
        PWB_CHECK(std::filesystem::exists(staged_probe));

        // Discard goes last: it terminates the session (contract teardown),
        // so only window-level state is asserted afterwards.
        PWB_CHECK(session->edit().start_editing("fixture.facies_boundary").empty());
        const QgsPointXY again = layer->getFeature(1).geometry().vertexAt(0);
        PWB_CHECK(session->edit()
                      .move_vertex("fixture.facies_boundary", 1, 0,
                                   again.x() + 0.05, again.y() + 0.05)
                      .empty());
        window.refreshActionStates();
        answer = QMessageBox::Discard;
        discard_answer = QMessageBox::Yes;
        PWB_CHECK(window.close() == true);
        PWB_CHECK(!window.anyDirtyEditSession());
    }

    pwb::qgis::QgisRuntime::release();
    return ::pwb::test::report("platform.ui_wiring");
}
