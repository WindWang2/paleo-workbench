// UI-09 — Qt widget smoke (offscreen, no QGIS): every shell constructs
// and responds — task panels, seismic panels, well panels, dialogs, the
// prediction pages, the joint page and the 3D page. Engine seams stay
// injected; null engines must render the honest unavailable placeholder.

#include <QApplication>
#include <QDialog>
#include <QListWidget>
#include <QMouseEvent>
#include <QSignalSpy>
#include <QTableView>
#include <QTreeWidget>
#include <QWidget>

#include <map>
#include <optional>
#include <string>
#include <vector>

#include <pwb/ui_wellseis/qt/correlation_link_editor.hpp>
#include <pwb/ui_wellseis/qt/cross_well_export_dialog.hpp>
#include <pwb/ui_wellseis/qt/engine_seams.hpp>
#include <pwb/ui_wellseis/qt/geological_modeling_3d_page.hpp>
#include <pwb/ui_wellseis/qt/object_table_model.hpp>
#include <pwb/ui_wellseis/qt/prediction_evidence_panel.hpp>
#include <pwb/ui_wellseis/qt/project_well_map_page.hpp>
#include <pwb/ui_wellseis/qt/seismic_attribute_panel.hpp>
#include <pwb/ui_wellseis/qt/seismic_context_toolbar.hpp>
#include <pwb/ui_wellseis/qt/seismic_control_panel.hpp>
#include <pwb/ui_wellseis/qt/seismic_prediction_page.hpp>
#include <pwb/ui_wellseis/qt/seismic_view_panel.hpp>
#include <pwb/ui_wellseis/qt/task_panel_base.hpp>
#include <pwb/ui_wellseis/qt/well_detail_panel.hpp>
#include <pwb/ui_wellseis/qt/well_log_canvas_panel.hpp>
#include <pwb/ui_wellseis/qt/well_log_prediction_page.hpp>
#include <pwb/ui_wellseis/qt/well_log_track_settings.hpp>
#include <pwb/ui_wellseis/qt/well_map_canvas.hpp>
#include <pwb/ui_wellseis/qt/well_map_panel.hpp>
#include <pwb/ui_wellseis/qt/well_seismic_joint_page.hpp>
#include <pwb/ui_wellseis/qt/well_table_panel.hpp>
#include <pwb/ui_wellseis/slices.hpp>
#include <pwb/ui_wellseis/task_state.hpp>

#include "ui_wellseis_test.hpp"

using namespace pwb::ui_wellseis;
using namespace pwb::ui_wellseis::qt;

namespace {

PredictionTaskSlice task(const std::string& id, const std::string& name,
                         const std::string& status) {
    PredictionTaskSlice t;
    t.id = id;
    t.name = name;
    t.status = status;
    return t;
}

// Minimal JointHostController fake — records calls, reports no scene.
class FakeJointHost : public JointHostController {
public:
    bool shutdown(int) override {
        shutdown_called = true;
        return true;
    }
    void reload() override { reload_count += 1; }
    // 06: settable snapshot (default stays the honest no-scene state) so
    // the page's multi-fence tree sync can be exercised without an
    // engine.
    JointSceneSnapshot scene_snapshot() const override { return snapshot_; }
    bool has_scene() const override { return snapshot_.has_scene; }
    void activate_fence(const std::string& fence_id) override {
        activated_fence = fence_id;
    }
    void set_fence_visible(const std::string& fence_id, bool visible)
        override {
        fence_visibility[fence_id] = visible;
    }
    JointSceneSnapshot snapshot_;
    std::string activated_fence;
    std::map<std::string, bool> fence_visibility;
    std::string engine_error() const override { return engine_error_; }
    std::vector<std::pair<std::string, std::string>> well_options()
        const override {
        return {{"w1", "井A"}, {"w2", "井B"}};
    }
    bool set_vertical_domain(const std::string& domain) override {
        last_domain = domain;
        return true;
    }
    void add_well_to_well_fence(const std::string& a, const std::string& b,
                                const std::string&) override {
        fences.emplace_back(a, b);
    }
    void delete_active_fence() override { delete_fence_count += 1; }
    void set_orthogonal_slice_indices(std::optional<int>,
                                      std::optional<int>) override {}
    void restore_orthogonal_slice_state(
        std::optional<int>, std::optional<int>,
        const std::vector<JointTimeSliceEntry>&, std::optional<double>,
        double) override {}
    bool apply_slice_line_numbers(double, double) override { return true; }
    void add_time_slice(double) override {}
    void remove_time_slice(double) override {}
    void set_time_slice_visible(double, bool) override {}
    void set_active_time_slice(double) override {}
    void set_time_opacity(double) override {}
    void set_3d_mode(const std::string& mode) override {
        last_3d_mode = mode;
    }
    void set_color_scales(const std::string& seismic,
                          const std::string& gr) override {
        last_seismic_scale = seismic;
        last_gr_scale = gr;
    }
    void set_well_width(int px) override { last_well_width = px; }
    void set_well_visibility(const std::string&, bool) override {}
    void set_layer_visibility(const std::string&, bool) override {}
    void apply_camera_preset(const std::string&) override {}
    std::string well_identity_asset_id() const override { return {}; }
    std::map<std::string, std::string> well_identity_map() const override {
        return {};
    }
    std::map<std::string, std::string> path_hints() const override {
        return {};
    }
    std::vector<std::string> loaded_data_paths() const override { return {}; }
    bool highlight_well(const std::string&) override { return false; }
    bool focus_position(int, int, std::optional<double>) override {
        return false;
    }
    QWidget* joint_widget(QWidget* parent) override {
        if (widget_null) {
            return nullptr;
        }
        return new QWidget(parent);
    }
    void push_scene_to_widget() override {}

    bool shutdown_called = false;
    int reload_count = 0;
    int delete_fence_count = 0;
    bool widget_null = false;
    std::string engine_error_;
    std::string last_domain;
    std::string last_3d_mode;
    std::string last_seismic_scale;
    std::string last_gr_scale;
    int last_well_width = -1;
    std::vector<std::pair<std::string, std::string>> fences;
};

// Minimal Geo3DController fake.
class FakeGeo3D : public Geo3DController {
public:
    void set_widget(QWidget* widget) override { widget_ = widget; }
    void set_measure_mode(const QString& mode) override {
        last_measure_mode = mode;
    }
    int clear(const QString&) override { return 0; }
    void set_axis_clip(const QString&, bool, double, bool) override {}
    void reset_clip() override {}
    std::map<QString, std::pair<bool, double>> clip_state() const override {
        return {};
    }
    void fit_all() override {}
    std::vector<QString> saved_view_names() const override { return {}; }
    void save_view(const QString&) override {}
    void apply_view(const QString&) override {}
    void rebuild_tree(QTreeWidgetItem*) override {}
    void sync_scene() override {}
    void save_state() override {}
    void set_tree_visibility(const QString&, bool) override {}
    void inspect(const QString&) override {}

    QWidget* widget_ = nullptr;
    QString last_measure_mode;
};

}  // namespace

PWB_TEST(task_panel_update_state) {
    PredictionTaskPanel panel;
    const std::vector<PredictionTaskSlice> tasks = {
        task("t1", "任务甲", "done"), task("t2", "任务乙", "running")};
    QSignalSpy spy(&panel, &TaskPanelBase::task_selected);
    panel.update_state(tasks);
    CHECK_EQ(panel.tasks().size(), 2);
    // Active row follows the last task (active_prediction_task parity).
    CHECK_EQ(panel.current_row(), 1);
    panel.update_state(tasks, 0);
    CHECK_EQ(panel.current_row(), 0);
}

PWB_TEST(seismic_context_toolbar) {
    SeismicContextToolbar toolbar;
    toolbar.set_source_entries({{"三维 · SEGY", "r1"}, {"空", ""}});
    toolbar.set_display_mode(QStringLiteral("vd"));
    toolbar.set_selected_attribute(QStringLiteral("振幅"));
    toolbar.set_status(QStringLiteral("就绪"));
    toolbar.set_inferring(true);
    toolbar.set_inferring(false);
    const auto t = task("t1", "任务甲", "running");
    toolbar.set_context(&t, "T3", "振幅", "变密度",
                        std::array<std::int64_t, 3>{10, 20, 30},
                        "Mock · 固定");
    toolbar.set_context(nullptr, "", "", "", std::nullopt, std::nullopt);
    toolbar.set_display_mode(QStringLiteral("wiggle"));
}

PWB_TEST(seismic_attribute_panel) {
    bool probe_called = false;
    SeismicAttributePanel panel(nullptr,
                                [&](const std::string&) {
                                    probe_called = true;
                                    return true;
                                });
    CHECK(!panel.selected_attribute().isEmpty());
    panel.set_selected_attribute(QStringLiteral("振幅"));
    CHECK_EQ(panel.selected_attribute().toStdString(), "振幅");
}

PWB_TEST(seismic_control_panel) {
    SeismicControlPanel panel;
    panel.set_attribute_label(QStringLiteral("振幅"));
    panel.set_display_mode(QStringLiteral("wiggle"));
    panel.set_controls_enabled(false);
    panel.set_controls_enabled(true);
    panel.set_well_tie_checked(true);
    panel.set_well_tie_checked(false);
}

PWB_TEST(seismic_view_panel_seam) {
    SeismicViewPanel panel;
    // Null seam -> honest placeholder, not ready.
    panel.set_view({nullptr, "no engine"});
    CHECK(!panel.is_view_ready());
    CHECK(panel.view() == nullptr);
    // Real widget -> ready.
    auto* engine = new QWidget;
    panel.set_view({engine, ""});
    CHECK(panel.is_view_ready());
    CHECK(panel.view() == engine);

    panel.set_display_mode(QStringLiteral("wiggle"));
    CHECK_EQ(panel.display_mode().toStdString(), "wiggle");
    panel.set_attribute_label(QStringLiteral("甜点"));
    CHECK_EQ(panel.attribute_label().toStdString(), "甜点");
    panel.set_volume_shape(std::array<std::int64_t, 3>{10, 20, 30});
    CHECK_EQ(panel.volume_shape()->at(2), 30);

    // Cursor gate rides through the panel (30 ms / >1 inline line).
    QSignalSpy cursor_spy(&panel, &SeismicViewPanel::cursor_published);
    panel.offer_cursor(5.0, 7.0, 900.0);
    CHECK_EQ(cursor_spy.count(), 1);
    panel.offer_cursor(5.4, 7.0, 900.0);  // small move, throttled
    CHECK_EQ(cursor_spy.count(), 1);
    panel.offer_cursor(7.0, 7.0, 900.0);  // >1 inline line, publishes
    CHECK_EQ(cursor_spy.count(), 2);
    panel.reset_cursor_gate();
    panel.shutdown();
}

PWB_TEST(well_log_canvas_panel) {
    WellLogCanvasPanel panel;
    // Legacy backend is the default; a null engine seam keeps its
    // placeholder honest.
    panel.set_canvas_seam("engine", {nullptr, false, "wle missing"});
    panel.set_backend("engine");
    CHECK_EQ(panel.backend(), "engine");
    CHECK(panel.is_native_backend());
    CHECK(!panel.is_canvas_ready());
    panel.set_backend("legacy");
    CHECK_EQ(panel.backend(), "legacy");

    panel.set_status(QStringLiteral("status"));
    // Depth-unit gate: meters allow linking; feet/other refuse.
    WellLogCanvasPanel::DepthUnitInfo meters;
    meters.unit = "m";
    meters.declared = true;
    panel.set_depth_unit(meters);
    CHECK(!panel.depth_cursor_unavailable_reason().has_value());
    WellLogCanvasPanel::DepthUnitInfo feet;
    feet.unit = "ft";
    feet.declared = true;
    feet.raw = "FT";
    panel.set_depth_unit(feet);
    CHECK_EQ(panel.depth_cursor_unavailable_reason().value_or(""),
             "depth-unit:ft");
    panel.shutdown();
}

PWB_TEST(well_panels) {
    WellTablePanel table_panel;
    WellTableSlice table;
    table.name = "井参数表";
    table.rows = {{.well_id = "w1", .name = "井A"}};
    table_panel.update_from_well_table(table);
    table_panel.select_well("w1");
    CHECK_EQ(table_panel.selected_well_id().value_or(""), "w1");
    CHECK(table_panel.summary_text().toStdString().find("1 行") != std::string::npos);

    WellDetailPanel detail;
    WellDataViewSlice view;
    view.well_name = "井A";
    detail.set_view(view, true);
    detail.set_view({}, false);

    WellMapPanel map_panel;
    ProjectSlice project;
    project.project_crs = "EPSG:4528";
    project.wells = {{.id = "w1",
                      .name = "井A",
                      .project_x = 1.0,
                      .project_y = 2.0,
                      .coordinate_status = "ok"}};
    map_panel.refresh_domain(project);
    CHECK(map_panel.map_page() != nullptr);
    CHECK(!map_panel.count_text().isEmpty());
    map_panel.set_collapsed(true);
    CHECK(map_panel.is_collapsed());
    map_panel.set_collapsed(false);
    map_panel.expand_and_focus("w1");
}

PWB_TEST(well_map_canvas_surface) {
    WellMapCanvas canvas;
    canvas.resize(400, 300);
    WellMapScene scene;
    scene.ok_points = {{10, 10}, {20, 20}};
    scene.ok_labels = {"井A", "井B"};
    scene.flagged_points = {{30, 30}};
    scene.flagged_labels = {"井C"};
    scene.boundary = {{0, 0}, {40, 0}, {40, 40}, {0, 40}};
    canvas.set_scene(scene);

    std::string hovered_series;
    std::string clicked_series;
    int clicked_index = -1;
    canvas.on_point_hovered = [&](const std::string& s, int, double,
                                  double) { hovered_series = s; };
    canvas.on_point_clicked = [&](const std::string& s, int i, double,
                                  double) {
        clicked_series = s;
        clicked_index = i;
    };
    canvas.show();
    // Synthesize a click on the first well's widget position.
    const QPointF center = canvas.rect().center();
    QMouseEvent press(QEvent::MouseButtonPress, center, center,
                      Qt::LeftButton, Qt::LeftButton, Qt::NoModifier,
                      QPointingDevice::primaryPointingDevice());
    QApplication::sendEvent(&canvas, &press);
    // No assertion on hit here (widget-space mapping is view-dependent) —
    // the surface contract is exercised by ProjectWellMapPage below.
    canvas.autofit();
    canvas.reset_view();
    canvas.set_view_bounds(0, 50, 0, 50);
    canvas.focus_point(10, 10, 2.0);
    (void)hovered_series;
    (void)clicked_series;
    (void)clicked_index;
}

PWB_TEST(project_well_map_page) {
    ProjectWellMapPage page;
    page.resize(500, 400);
    ProjectSlice project;
    project.project_crs = "EPSG:4528";
    project.wells = {
        {.id = "w1",
         .name = "井A",
         .project_x = 100.0,
         .project_y = 200.0,
         .coordinate_status = "ok"},
        {.id = "w2",
         .name = "井B",
         .surface_x = 5.0,
         .surface_y = 6.0,
         .coordinate_status = "untransformed"},
        {.id = "w3",
         .name = "参考",
         .project_x = 1.0,
         .project_y = 1.0,
         .coordinate_status = "ok",
         .spatial_scope = "reference"},
    };
    project.workarea_boundary = {{0, 0}, {300, 0}, {300, 300}};
    QSignalSpy selected_spy(&page, &ProjectWellMapPage::well_selected);
    page.set_project(project);
    CHECK_EQ(page.well_list_count(), 2);  // reference wells stay off-list
    CHECK(page.surface() != nullptr);
    CHECK(page.crs_label_text().toStdString().find("EPSG:4528") != std::string::npos);

    page.select_well("w1", false, true);
    CHECK_EQ(selected_spy.count(), 1);
    CHECK_EQ(page.selected_well_ids().size(), 1);
    page.select_wells({"w1", "w2"});
    CHECK_EQ(page.selected_well_ids().size(), 2);
    page.clear_selection();
    CHECK(page.selected_well_ids().empty());
    page.show_spatial_cursor(50.0, 60.0);
    CHECK(page.spatial_cursor_position().has_value());
    page.clear_spatial_cursor();
    CHECK(!page.spatial_cursor_position().has_value());
    page.clear();
    CHECK_EQ(page.well_list_count(), 0);
}

PWB_TEST(correlation_link_editor_dialog) {
    CorrelationDraftSlice draft;
    draft.tops = {{"t1", "井A", "T3", 1000.0, "MD", "MANUAL", ""},
                  {"t2", "井B", "T3", 1010.0, "MD", "MANUAL", ""}};
    CorrelationEditorHooks hooks;
    // The pick_item seam returns the first choice (top A), then second.
    int pick_count = 0;
    hooks.pick_item = [&](const QString&, const QString&,
                          const QStringList& items, int) {
        const int index =
            std::min(pick_count, static_cast<int>(items.size()) - 1);
        pick_count += 1;
        return std::pair<QString, bool>{items.value(index), true};
    };
    CorrelationLinkEditor editor(draft, nullptr, hooks);
    CHECK_EQ(editor.generation(), 0);
    // Exercise the table rebuild (public surface: generation + models).
    editor.show();
}

PWB_TEST(cross_well_export_dialog) {
    CrossWellExportDialog dialog;
    CrossWellExportOptions options;
    options.fmt = "pdf";
    options.dpi = 300;
    options.page_size = "A4";
    dialog.set_options(options);
    CHECK_EQ(dialog.options().fmt, "pdf");
    CHECK_EQ(dialog.options().dpi, 300);
    CHECK_EQ(dialog.options().page_size.value_or(""), "A4");
}

PWB_TEST(track_settings_dialog) {
    pwb::viz::WellLogTrackLayout layout;
    layout.curve_keys = {"curve:0:GR", "curve:1:RT", "curve:2:SP"};
    layout.visible = {true, true, false};
    layout.groups = {{"curve:0:GR", "curve:1:RT"}, {"curve:2:SP"}};
    layout.scale_mode = {std::nullopt, std::nullopt, std::nullopt};
    layout.color = {"", "", ""};
    CurveTrackSettingsDialog dialog({"GR", "RT", "SP"}, layout, nullptr);
    CHECK_EQ(dialog.layout().groups.size(), 2);
    // Public ops (Python merge/unmerge parity).
    CHECK(dialog.unmerge_curve("curve:1:RT"));
    CHECK_EQ(dialog.layout().groups.size(), 3);
    CHECK(dialog.merge_curve("curve:1:RT", "curve:0:GR"));
    CHECK_EQ(dialog.layout().groups.size(), 2);
}

PWB_TEST(evidence_panel) {
    PredictionEvidencePanel panel;
    const auto t = task("t1", "任务甲", "done");
    panel.update_state(&t, true);
    panel.update_state(nullptr, false);
    panel.set_actions_enabled(true, false);
    panel.set_inferring(true);
    panel.set_inferring(false);
    panel.set_status(QStringLiteral("就绪"));
    CHECK_EQ(panel.status_text().toStdString(), "就绪");
    panel.set_diagnostic_log(QStringLiteral("线上测井预测运行日志\n状态: 失败"));
    QSignalSpy run_spy(&panel, &PredictionEvidencePanel::run_requested);
    panel.run_requested();
    // (signal emitted via button; emit through the signal spy harness —
    //  construction + state coverage is the smoke contract)
}

PWB_TEST(joint_page) {
    FakeJointHost host;
    ProjectSlice project;
    WellSeismicJointPage page(nullptr, &host, &project);
    page.show();
    // First show fires the Python _loaded_once lazy reload already.
    const int after_show = host.reload_count;
    // Null engine widget -> honest placeholder, page stays alive.
    host.widget_null = true;
    page.reload();
    CHECK_EQ(host.reload_count, after_show + 1);
    CHECK(page.shutdown_workers(50));
    CHECK(host.shutdown_called);
}

PWB_TEST(seismic_prediction_page) {
    SeismicPredictionPage page;
    page.resize(800, 500);
    ProjectSlice project;
    project.resources = {
        {.id = "r1",
         .name = "三维",
         .path = "/data/a.segy",
         .type = "seismic",
         .format = "segy"}};
    page.set_project(&project);
    // No hooks -> inference actions no-op; page stays coherent.
    page.shutdown_workers(50);
}

PWB_TEST(well_log_prediction_page) {
    WellLogPredictionPage page;
    page.resize(800, 500);
    ProjectSlice project;
    project.resources = {
        {.id = "r4",
         .name = "井A",
         .path = "/data/a.las",
         .type = "well_log",
         .format = "las"}};
    page.set_project(&project);
    page.set_project_path("/tmp/proj");
    page.shutdown_workers(50);
}

PWB_TEST(geo3d_page) {
    FakeJointHost host;
    FakeGeo3D geo3d;
    GeologicalModeling3DPage page(nullptr, &host, &geo3d);
    page.resize(900, 600);
    ProjectSlice project;
    JointAnalysisSlice state;
    state.vertical_domain = "Depth";
    page.set_project(&project, state);
    page.set_project_path("/tmp/proj");
    page.activate_page();
    // collect_joint_analysis_state never throws, never stores voxels.
    const JointAnalysisSlice collected =
        page.collect_joint_analysis_state();
    CHECK(collected.vertical_domain == "Depth" ||
          collected.vertical_domain == "Time");
    CHECK(page.shutdown_workers(50));
    CHECK(host.shutdown_called);
}

PWB_TEST(geo3d_page_multi_fence_management) {
    FakeJointHost host;
    GeologicalModeling3DPage page(nullptr, &host);
    page.resize(900, 600);

    JointSceneSnapshot snap;
    snap.has_scene = true;
    snap.n_inline = 8;
    snap.n_crossline = 6;
    snap.time_min_ms = 0.0;
    snap.time_max_ms = 100.0;
    snap.active_fence_id = "f2";
    snap.fences = {{"f1", "Fence A", true}, {"f2", "Fence B", true}};
    host.snapshot_ = snap;

    // The page syncs its tree from the host's scene_updated signal.
    emit host.scene_updated();

    QTreeWidget* tree = page.model_tree();
    CHECK(tree != nullptr);
    // Locate the fence group by its persisted key text.
    QTreeWidgetItem* fence_group = nullptr;
    QTreeWidget* top = tree;
    for (int i = 0; i < top->topLevelItemCount() && fence_group == nullptr;
         ++i) {
        QTreeWidgetItem* root = top->topLevelItem(i);
        for (int j = 0; j < root->childCount(); ++j) {
            QTreeWidgetItem* child = root->child(j);
            if (child->text(0).contains(QStringLiteral("fence (geoviz)"))) {
                fence_group = child;
                break;
            }
        }
    }
    CHECK(fence_group != nullptr);
    if (fence_group != nullptr) {
        CHECK_EQ(fence_group->childCount(), 2);
        if (fence_group->childCount() == 2) {
            // Hide the first fence through the tree check state.
            fence_group->child(0)->setCheckState(0, Qt::Unchecked);
            CHECK_EQ(host.fence_visibility.at("f1"), false);
            // The active fence child carries the arrow marker (text
            // unchanged; identity via UserRole data).
            CHECK_EQ(fence_group->child(1)
                         ->data(0, Qt::UserRole)
                         .toString()
                         .toStdString(),
                     "f2");
        }
    }
    // The page stays coherent after the multi-fence sync (no crash on
    // the coordinate/unit note update with a populated scene).
    CHECK(page.shutdown_workers(50));
}

PWB_TEST(string_table_model) {
    StringTableModel model;
    model.set_columns({{QStringLiteral("c1"), QStringLiteral("列一")},
                        {QStringLiteral("c2"), QStringLiteral("列二")}});
    model.set_rows({"k1", "k2"},
                   {{QStringLiteral("a"), QStringLiteral("b")},
                    {QStringLiteral("c"), QStringLiteral("d")}});
    CHECK_EQ(model.rowCount(), 2);
    CHECK_EQ(model.columnCount(), 2);
    CHECK_EQ(model.key_at(1).value_or(""), "k2");
    CHECK_EQ(model.row_for_key("k1"), 0);
    CHECK_EQ(model.row_for_key("missing"), -1);
    CHECK_EQ(model.data(model.index(0, 1)).toString().toStdString(), "b");
}

int main(int argc, char** argv) {
    QApplication app(argc, argv);
    return pwb_test::run_all();
}
