// platform.ui_closure — CONV-27 integration test: the three-stage workflow
// surface, domain layer tree, edit tool lifecycle, enablement matrix,
// layout persistence and the offscreen screenshot, all through the real
// MainWindow (same code the menus/toolbars drive).

#include <cstdio>
#include <filesystem>

#include <QAction>
#include <QFile>
#include <QMessageBox>
#include <QSettings>
#include <QTemporaryDir>
#include <QTimer>
#include <qgsapplication.h>

#include <qgsgeometry.h>
#include <qgslayertreeview.h>
#include <qgsrectangle.h>
#include <qgslayertree.h>
#include <qgsmapcanvas.h>
#include <qgsmaptooldigitizefeature.h>
#include <qgsvectorlayer.h>

#include <pwb/application/project_session.hpp>
#include <pwb/tool_policy/stages.hpp>
#include <pwb/qgis/qgis_runtime.hpp>
#include <pwb/ui/edit_tool_controller.hpp>
#include <pwb/ui/workbench_layout.hpp>

#include "main_window.hpp"

#include "test_fixtures.hpp"
#include "test_framework.hpp"

using pwb::app::MainWindow;

int main(int argc, char** argv) {
    QgsApplication app(argc, argv, true);
    pwb::qgis::QgisRuntime::acquire();

    QTemporaryDir temp_dir;
    const QString gpkg_uri = pwb::test_fixtures::make_gpkg_fixture(
        temp_dir.path());
    PWB_CHECK_MSG(!gpkg_uri.isEmpty(), "fixture creation failed");

    MainWindow window;
    const QString load_error = window.loadFixtures(gpkg_uri, QString());
    PWB_CHECK_MSG(load_error.isEmpty(), load_error.toStdString());
    window.show();
    pwb::application::ProjectSession* session = window.session();

    // ---- surface presence ------------------------------------------------
    PWB_CHECK(window.stageDock() != nullptr);
    PWB_CHECK(window.layerPanel() != nullptr);
    PWB_CHECK(window.editTools() != nullptr);
    PWB_CHECK(window.constraintPanel() != nullptr);

    // Default stage is the Python default (facies_calibration).
    PWB_CHECK(session->mapping_stage().has_value());
    PWB_CHECK(*session->mapping_stage() == "facies_calibration");
    PWB_CHECK(window.stageDock()->current_stage()
              == pwb::tool_policy::MappingStage::FaciesCalibration);

    // ---- readiness reflects the unconfigured truth ------------------------
    {
        const QStringList rows = window.stageDock()->readiness_rows();
        PWB_CHECK(!rows.isEmpty());
        bool horizon_error = false;
        for (const QString& row : rows) {
            if (row.contains(QStringLiteral("未设定编图层位"))
                && row.startsWith(QStringLiteral("✕"))) {
                horizon_error = true;
            }
        }
        PWB_CHECK_MSG(horizon_error,
                      "stage-1 readiness must flag the missing horizon");
    }

    // ---- stage-driven enablement matrix (the evaluator is the one gate) ---
    // facies_boundary is a LINE role: add_polygon is kind/role-blocked on
    // it regardless of stage; map_export is stage-3 only.
    {
        QAction* export_action = window.governedAction("map_export");
        QAction* add_line = window.governedAction("add_line");
        QAction* add_polygon = window.governedAction("add_polygon");
        PWB_CHECK(export_action != nullptr && add_line != nullptr
                  && add_polygon != nullptr);

        window.applyStageValue("facies_calibration");
        PWB_CHECK(!export_action->isEnabled());   // stage whitelist

        window.applyStageValue("constraint_factor");
        PWB_CHECK(!export_action->isEnabled());

        window.applyStageValue("integrated_compilation");
        PWB_CHECK(export_action->isEnabled());

        // With the polygon fixture active (line-role facts), add_polygon
        // stays blocked by the role gate; add_line by the kind gate.
        PWB_CHECK(!add_polygon->isEnabled());
        PWB_CHECK(!add_line->isEnabled());

        // A polygon-role draft layer unlocks add_polygon in stage 1.
        pwb::application::DomainLayerFacts draft;
        draft.layer_id = "fixture.facies_boundary";
        draft.role = "initial_facies_draft";
        draft.role_label = "相图草稿";
        draft.write_granted = true;
        draft.artifact_maturity = "draft";
        session->set_active_layer(draft);
        window.applyStageValue("facies_calibration");
        // Capture tools additionally require an open edit session.
        window.governedAction("toggle_editing")->trigger();
        PWB_CHECK(session->edit().editing("fixture.facies_boundary"));
        window.refreshActionStates();
        PWB_CHECK_MSG(add_polygon->isEnabled(),
                      "add_polygon must be enabled on a polygon-role "
                      "editable draft layer in stage 1");
        PWB_CHECK(!add_line->isEnabled());   // kind gate still applies
    }

    // ---- layer tree panel: join-key active sync ---------------------------
    {
        bool signal_seen = false;
        QString signaled_id;
        QObject::connect(window.layerPanel(),
                         &pwb::ui::LayerTreePanel::active_layer_changed,
                         &window, [&](const QString& id) {
                             signal_seen = true;
                             signaled_id = id;
                         });
        window.layerPanel()->set_active_layer("fixture.facies_boundary");
        PWB_CHECK(signal_seen);
        PWB_CHECK(signaled_id == QStringLiteral("fixture.facies_boundary"));
        PWB_CHECK(window.layerPanel()->view()->currentLayer() != nullptr);

        // Group add + reorder must not corrupt the join-key resolution:
        // the domain id still resolves through the adapter.
        session->map().project()->layerTreeRoot()->addGroup(
            QStringLiteral("分组A"));
        window.layerPanel()->refresh_indicators();
        window.layerPanel()->set_active_layer("fixture.facies_boundary");
        PWB_CHECK(window.layerPanel()->view()->currentLayer() != nullptr);

        // Edit indicator appears while editing (QGIS edit buffer authority).
        PWB_CHECK(window.layerPanel()->editing_indicated_layer_ids()
                      .size() == 1);
        window.governedAction("toggle_editing")->trigger();   // stop
        window.refreshActionStates();
        PWB_CHECK(window.layerPanel()->editing_indicated_layer_ids()
                      .empty());
        // Restart for the digitize section below. The CONV-27 roll_back
        // fix makes this real: the domain capture ends with the QGIS
        // buffer, so start_editing re-arms instead of returning early.
        window.governedAction("toggle_editing")->trigger();
        PWB_CHECK(session->edit().editing("fixture.facies_boundary"));
    }

    // ---- edit tool lifecycle ------------------------------------------------
    {
        QgsMapCanvas* canvas = window.findChild<QgsMapCanvas*>();
        PWB_CHECK(canvas != nullptr);

        window.governedAction("select")->trigger();
        PWB_CHECK(session->current_tool() == "select");

        // The tree-panel activation reverted the facts role to the
        // facies_boundary (line) entry; capture tools need the polygon-role
        // draft facts, same as a user picking the draft layer to digitize.
        pwb::application::DomainLayerFacts draft2;
        draft2.layer_id = "fixture.facies_boundary";
        draft2.role = "initial_facies_draft";
        draft2.role_label = "相图草稿";
        draft2.write_granted = true;
        draft2.artifact_maturity = "draft";
        session->set_active_layer(draft2);
        window.refreshActionStates();
        window.governedAction("add_polygon")->trigger();
        PWB_CHECK(session->current_tool() == "add_polygon");
        PWB_CHECK(qobject_cast<QgsMapToolDigitizeFeature*>(
                      canvas->mapTool())
                  != nullptr);

        // Digitize completion flows through the edit authority: emit the
        // same signal the canvas tool emits (public Qt signal).
        QgsVectorLayer* layer =
            session->map().vectorLayerById("fixture.facies_boundary");
        PWB_CHECK(layer != nullptr);
        const long long before = layer->featureCount();
        QgsFeature feature(layer->fields());
        feature.setGeometry(QgsGeometry::fromWkt(
            QStringLiteral("POLYGON((112 31, 113 31, 113 32, 112 32, 112 31))")));
        pwb::ui::EditToolController* tools = window.editTools();
        emit tools->digitize_tool("add_polygon")->digitizingCompleted(feature);
        PWB_CHECK(layer->featureCount() == before + 1);
        PWB_CHECK(session->edit().dirty("fixture.facies_boundary"));

        // Undo removes the digitized feature (single undo authority).
        window.governedAction("undo")->trigger();
        PWB_CHECK(layer->featureCount() == before);

        // Selection -> delete_selected through the governed action.
        layer->selectByRect(QgsRectangle(110.0, 30.0, 116.5, 34.5),
                            Qgis::SelectBehavior::SetSelection);
        window.refreshActionStates();
        QAction* delete_action = window.governedAction("delete_selected");
        PWB_CHECK_MSG(delete_action->isEnabled(),
                      "delete_selected must follow the live selection");
        const long long selected = layer->selectedFeatureCount();
        PWB_CHECK(selected > 0);
        delete_action->trigger();
        PWB_CHECK(layer->featureCount() == before - selected);

        // Rollback discards the whole session round.
        int discard_answer = QMessageBox::Yes;   // scripted confirm
        window.setDiscardConfirmResponder(
            [&discard_answer]() { return discard_answer; });
        window.governedAction("rollback")->trigger();
        PWB_CHECK(layer->featureCount() == before);
        PWB_CHECK(!session->edit().editing("fixture.facies_boundary"));
    }

    // ---- constraint panel reflects constraint-role layers ----------------
    {
        window.refreshActionStates();
        const QStringList rows = window.constraintPanel()->constraint_rows();
        PWB_CHECK(!rows.isEmpty());
        // The fixture layer counts 3 polygons under the constraint-role
        // fallback (facies_boundary is in the constraint role set).
        bool found = false;
        for (const QString& row : rows) {
            if (row.endsWith(QStringLiteral("|3"))) found = true;
        }
        PWB_CHECK_MSG(found, "constraint panel must list the 3-feature layer");
    }

    // ---- layout persistence: save/restore/corrupt/reset -------------------
    {
        const QString ini = temp_dir.path() + "/layout.ini";
        QSettings store(ini, QSettings::IniFormat);
        pwb::ui::WorkbenchLayout layout(&store);
        PWB_CHECK(!layout.has_stored_layout());
        PWB_CHECK(!layout.restore(window));

        layout.save(window);
        PWB_CHECK(layout.has_stored_layout());

        // Corrupt the state blob: version still matches, bytes do not.
        store.setValue("layout/window_state", QByteArray("junk"));
        store.sync();
        PWB_CHECK(!layout.restore(window));   // refuse, default stands

        // Unknown schema version: dropped without touching the window.
        layout.save(window);
        store.setValue("layout/state_version", 99);
        store.sync();
        PWB_CHECK(!layout.restore(window));

        // Round-trip after reset.
        store.setValue("layout/state_version", 1);
        store.sync();
        PWB_CHECK(layout.restore(window));
        layout.reset();
        PWB_CHECK(!layout.has_stored_layout());
    }

    // ---- offscreen screenshot smoke ---------------------------------------
    {
        window.applyStageValue("constraint_factor");
        window.refreshActionStates();
        const QString png = temp_dir.path() + "/workbench.png";
        PWB_CHECK(window.grab().save(png, "PNG"));
        PWB_CHECK(QFile(png).size() > 20 * 1024);
    }

    pwb::qgis::QgisRuntime::release();
    return ::pwb::test::report("platform.ui_closure");
}
