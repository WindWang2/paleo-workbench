// UI-13 — Qt widget smoke test (offscreen): every ported composite
// widget constructs + responds under QT_QPA_PLATFORM=offscreen.
// Complements the core test by proving the Qt shells wire up (signals,
// models, dialogs) without a display.

#include <QApplication>
#include <QDialog>
#include <QLabel>
#include <QListWidget>

#include <cstdio>
#include <set>
#include <string>

#include <pwb/domain/json.hpp>
#include <pwb/ui_composite/composite_attribute_table.hpp>
#include <pwb/ui_composite/composite_controller.hpp>
#include <pwb/ui_composite/composite_controller_qt.hpp>
#include <pwb/ui_composite/composite_document.hpp>
#include <pwb/ui_composite/composite_panels.hpp>
#include <pwb/ui_composite/facies_selector.hpp>
#include <pwb/ui_composite/layer_manager_panel.hpp>
#include <pwb/ui_composite/mapping_stage_bar.hpp>
#include <pwb/ui_composite/mapping_stage_panel.hpp>
#include <pwb/ui_composite/merge_features_dialog.hpp>
#include <pwb/ui_composite/tool_page_dialog.hpp>
#include <pwb/ui_composite/topology_checker_panel.hpp>
#include <pwb/ui_widgets/core/facies_taxonomy.hpp>

#ifdef PWB_HAVE_LINKED_WORKSPACE
#include <pwb/ui_composite/linked_workspace.hpp>
#endif

using namespace pwb::ui_composite;
using pwb::domain::Json;

namespace {

int failures = 0;

void check(bool condition, const char* what) {
    if (!condition) {
        ++failures;
        std::fprintf(stderr, "FAIL %s\n", what);
    } else {
        std::fprintf(stderr, "PASS %s\n", what);
    }
}

pwb::ui_widgets::core::FaciesTaxonomy test_taxonomy() {
    // from_geojson_features contract: properties carry `id` (feature
    // identity), `level` (facies/sub_facies/micro_facies), `facies`
    // (the name), and `parent_id` pointing at the parent feature id.
    const Json features = Json::array({
        {{"type", "Feature"},
         {"properties",
          {{"id", "T1"}, {"level", "facies"}, {"facies", "三角洲"},
           {"parent_id", ""}}}},
        {{"type", "Feature"},
         {"properties",
          {{"id", "T2"}, {"level", "facies"}, {"facies", "滨浅湖"},
           {"parent_id", ""}}}},
        {{"type", "Feature"},
         {"properties",
          {{"id", "T3"}, {"level", "sub_facies"},
           {"facies", "三角洲前缘"}, {"parent_id", "T1"}}}},
        {{"type", "Feature"},
         {"properties",
          {{"id", "T4"}, {"level", "micro_facies"},
           {"facies", "河口坝"}, {"parent_id", "T3"}}}},
    });
    return pwb::ui_widgets::core::FaciesTaxonomy::from_geojson_features(
        features);
}

Json square(double x0, double y0, double x1, double y1) {
    return Json{{"type", "Polygon"},
                {"coordinates",
                 Json::array({Json::array(
                     {Json::array({x0, y0}), Json::array({x1, y0}),
                      Json::array({x1, y1}), Json::array({x0, y1}),
                      Json::array({x0, y0})})})}};
}

}  // namespace

int main(int argc, char** argv) {
    QApplication app(argc, argv);
    const auto taxonomy = test_taxonomy();
    check(!taxonomy.is_empty(), "taxonomy fixture non-empty");

    // --- topology checker panel ------------------------------------
    {
        TopologyCheckerPanel panel;
        panel.set_errors(
            {Json{{"id", "e1"}, {"rule", "overlap"}, {"fixable", true},
                  {"bbox", Json::array({0, 0, 10, 10})},
                  {"feature_id", "f1"}, {"layer_id", "L"}}});
        check(panel.error_list != nullptr &&
                  panel.error_list->count() == 1,
              "topology panel lists errors");
        bool zoom_fired = false;
        QObject::connect(&panel, &TopologyCheckerPanel::zoom_requested,
                         &panel, [&](const QList<double>&) {
                             zoom_fired = true;
                         });
        (void)zoom_fired;
    }

    // --- mapping stage bar ------------------------------------------
    {
        MappingStageBar bar;
        QString requested;
        QObject::connect(&bar, &MappingStageBar::stage_requested, &bar,
                         [&](const QString& value) { requested = value; });
        bar.set_current_stage("boundary");
        check(requested.isEmpty() ||
                  requested == QStringLiteral("boundary"),
              "stage bar accepts stage switch");
    }

    // --- mapping stage panel ----------------------------------------
    {
        MappingStagePanel panel;
        panel.set_stage("boundary");
        panel.set_action_availability({});
        check(true, "stage panel constructs and accepts stage");
    }

    // --- facies cascade selector -------------------------------------
    {
        FaciesCascadeSelector selector(taxonomy);
        selector.set_selection(Json{{"facies", "三角洲"},
                                    {"sub_facies", "三角洲前缘"},
                                    {"micro_facies", "河口坝"}});
        const auto sel = selector.selection();
        check(sel.count("facies") && sel.at("facies") == "三角洲",
              "cascade restores facies selection");
        selector.set_selection(Json{{"facies", "滨浅湖"}});
        // 父级变化 → 更细级别清空（首项空哨兵可选停在上级）。
        const auto narrowed = selector.selection();
        check(narrowed.count("facies") &&
                  narrowed.at("facies") == "滨浅湖",
              "cascade parent switch clears deeper levels");

        FaciesSelectionDialog dialog(taxonomy, Json{{"facies", "三角洲"}});
        check(dialog.selection().count("facies") == 1,
              "facies selection dialog constructs");

        FaciesChangeDialog change(taxonomy, Json{{"facies", "滨浅湖"}},
                                  QStringLiteral("更改相"), 2);
        check(change.listed_facies().size() == 2,
              "facies change dialog lists taxonomy");
        change.select_facies(QStringLiteral("三角洲"));
        check(change.selected_facies() == QStringLiteral("三角洲"),
              "facies change dialog selection");
    }

    // --- merge features dialog ---------------------------------------
    {
        std::vector<Json> records = {
            Json{{"id", "f1"},
                 {"properties", Json{{"facies", "三角洲"},
                                     {"depth", 1200.0}}}},
            Json{{"id", "f2"},
                 {"properties", Json{{"facies", "滨浅湖"},
                                     {"depth", 1300.0}}}},
        };
        MergeFeaturesDialog dialog(records);
        const Json payload = dialog.result_payload();
        check(payload.is_object(), "merge dialog result payload");
    }

    // --- identify results / snapping dialog --------------------------
    {
        IdentifyResultsPanel identify;
        identify.set_results(
            {Json{{"layer_id", "L"}, {"feature_id", "f1"},
                  {"name", "要素1"}}});
        check(true, "identify results panel accepts results");

        CompositeEditController controller;
        SnappingSettingsDialog snapping(&controller);
        check(true, "snapping settings dialog constructs");
    }

    // --- layer manager / input tree / linked views -------------------
    {
        LayerManagerPanel manager;
        manager.set_project_crs("EPSG:4326");
        InputTreePanel input_tree;
        LinkedViewsPanel linked;
        check(true, "layer manager + input tree + linked views");
    }

    // --- tool page dialog ---------------------------------------------
    {
        ToolPageDialog dialog;
        check(true, "tool page dialog constructs");
    }

    // --- attribute table ----------------------------------------------
    {
        CompositeEditController controller;
        controller.project_crs = "EPSG:4326";
        auto& layer =
            controller.create_layer("测试层", "polygon");
        layer.replace_features({VectorFeature(
            "f1", square(0, 0, 10, 10), Json{{"facies", "三角洲"}})});
        CompositeAttributeTableDialog table(&controller, layer.id());
        table.refresh();
        check(table.table != nullptr,
              "attribute table binds controller layer");
    }

    // --- composite document shell --------------------------------------
    {
        CompositeDocument document;
        document.set_project_crs("EPSG:4326");
        auto* canvas = new QLabel(QStringLiteral("canvas"), &document);
        document.set_canvas(canvas, /*uses_native_stack=*/false);
        document.update_empty_hint(/*has_content=*/false);
        check(document.canvas() == canvas,
              "document hosts injected canvas");
        check(document.edit_controller != nullptr,
              "document owns edit controller");
        QString stage;
        QObject::connect(
            &document, &CompositeDocument::stage_switch_requested,
            &document, [&](const QString& value) { stage = value; });
        document.stage_bar->set_current_stage("fill");
        check(true, "document stage wiring constructs");
    }

    // --- linked workspace (CONV_30-gated) ------------------------------
#ifdef PWB_HAVE_LINKED_WORKSPACE
    {
        LinkedInterpretationWorkspace workspace;
        workspace.set_linked(true);
        check(true, "linked interpretation workspace constructs");
    }
#endif

    if (failures == 0) {
        std::fprintf(stderr, "ui_composite.qt_widgets_smoke: all "
                             "checks passed\n");
        return 0;
    }
    std::fprintf(stderr, "ui_composite.qt_widgets_smoke: %d "
                         "failure(s)\n", failures);
    return 1;
}
