// UI-14 — Qt-free core smoke test: exercises the six root-controller
// cores end-to-end against injected fakes (no Qt, no scheduler). Covers
// the contracts the Python modules froze:
//   * SelectionBus patch/source-sentinel/explicit-clear semantics;
//   * ViewCoordinationCore well index + publish routing + the
//     calibration-gated depth cursor refusal;
//   * map_actions vocabularies + availability text + toolbar grouping;
//   * ProjectSaveTaskState outcome bookkeeping + drained-save commit;
//   * ProjectControllerCore new/save/save-async/drain lifecycle;
//   * DataLifecycleCore remove/tag/register orchestration;
//   * WorkflowCore recompute commit + generation supersede + the
//     non-spatial send-to-mapping block.

#include <cstdio>
#include <functional>
#include <set>
#include <string>
#include <vector>

#include <pwb/ui_controllers/data_lifecycle.hpp>
#include <pwb/ui_controllers/map_actions.hpp>
#include <pwb/ui_controllers/project_controller.hpp>
#include <pwb/ui_controllers/project_save.hpp>
#include <pwb/ui_controllers/selection_bus.hpp>
#include <pwb/ui_controllers/view_coordination.hpp>
#include <pwb/ui_controllers/workflow_controller.hpp>

using namespace pwb;
using namespace pwb::ui_controllers;

namespace {

int g_failures = 0;

void check(bool condition, const char* expr, int line) {
    if (!condition) {
        ++g_failures;
        std::fprintf(stderr, "FAIL %d: %s\n", line, expr);
    }
}
#define CHECK(expr) check((expr), #expr, __LINE__)
#define CHECK_EQ(a, b) check((a) == (b), #a " == " #b, __LINE__)

// ---------------------------------------------------------------- fakes --

class FakeHub final : public CoordinateHubApi {
public:
    struct WellCall {
        std::string id;
        double x = 0, y = 0, kb = 0, td = 0;
    };
    std::vector<WellCall> wells;
    int clear_count = 0;
    int seismic_grid_calls = 0;
    std::vector<TimeDepthCalibrationSlice> calibrations;
    std::optional<std::tuple<double, double, double>> md_cursor;

    void register_well(
        const std::string& well_id, double x, double y, double elevation,
        double total_depth_m,
        const std::optional<WellStations>& stations) override {
        (void)stations;
        wells.push_back({well_id, x, y, elevation, total_depth_m});
    }
    int clear_all_wells() override {
        ++clear_count;
        const int n = static_cast<int>(wells.size());
        wells.clear();
        return n;
    }
    void reset_seismic_grid() override {}
    void configure_seismic_grid(std::pair<double, double>,
                                std::pair<double, double>,
                                std::pair<double, double>, int,
                                int) override {
        ++seismic_grid_calls;
    }
    void set_time_depth_calibration(
        const TimeDepthCalibrationSlice& calibration) override {
        calibrations.push_back(calibration);
    }
    std::pair<std::string, std::optional<double>> seismic_to_well(
        int, int, double) override {
        return {"", std::nullopt};
    }
    std::optional<CalibratedMd> calibrated_md(const std::string&,
                                            double) override {
        return std::nullopt;
    }
    double velocity_assumption() const override { return 2000.0; }
    std::tuple<double, double, double> well_depth_to_map(
        const std::string&, double) override {
        return {0.0, 0.0, 0.0};
    }
    std::pair<double, double> map_to_seismic_xy(double, double) override {
        return {0.0, 0.0};
    }
    std::pair<double, double> seismic_to_map_xy(int, int) override {
        return {0.0, 0.0};
    }
    std::optional<std::tuple<double, double, double>>
    well_md_to_seismic_cursor(const std::string&, double) override {
        return md_cursor;
    }
};

// Fake three-phase save manager (call order + payload capture).
class FakeSaveApi final : public ProjectSaveApi {
public:
    explicit FakeSaveApi(fs::path path, std::vector<std::string>* calls)
        : path_(std::move(path)), calls_(calls) {}
    const fs::path& project_path() const override { return path_; }
    domain::Result<project::PreparedSave> prepare_save(
        project::ProjectDocument&) override {
        calls_->push_back("prepare");
        project::PreparedSave prepared;
        prepared.payload_text = "{}";
        return domain::Result<project::PreparedSave>(prepared);
    }
    domain::Result<project::SaveStats> execute_save(
        const project::PreparedSave&) override {
        calls_->push_back("execute");
        project::SaveStats stats;
        stats.bytes_written = 42;
        return domain::Result<project::SaveStats>(stats);
    }
    void commit_save(project::ProjectDocument&,
                     const project::PreparedSave&,
                     const project::SaveStats&) override {
        calls_->push_back("commit");
    }

private:
    fs::path path_;
    std::vector<std::string>* calls_;
};

domain::Json make_wells_root() {
    return domain::Json::parse(R"json({
        "wells": [
            {"id": "w1", "name": "W-1", "surface_x": 10.0, "surface_y": 20.0,
             "kb": 100.0, "td": 3000.0},
            {"id": "w2", "name": "W-2", "surface_x": 30.0, "surface_y": 40.0}
        ],
        "seismic_surveys": [
            {"id": "s1", "extent": [[0,0],[100,0],[100,100]],
             "inline_range": [1, 50, 1], "crossline_range": [2, 60, 1]}
        ]
    })json");
}

// ---------------------------------------------------------------- tests --

void test_selection_bus() {
    double now = 100.0;
    SelectionBus bus([&now] { return now; });
    std::vector<SelectionState> seen;
    bus.subscribe([&](const SelectionState& s) { seen.push_back(s); });

    SelectionPatch patch;
    patch.active_well_id = std::optional<std::string>("w1");
    patch.selected_well_ids = std::set<std::string>{"w1", "w2"};
    bus.update(patch, std::optional<std::optional<std::string>>(
                          std::optional<std::string>("map")));
    CHECK_EQ(seen.size(), 1);
    CHECK(seen[0].active_well_id && *seen[0].active_well_id == "w1");
    CHECK(seen[0].source_widget_id && *seen[0].source_widget_id == "map");
    CHECK(bus.was_published_by("map"));
    CHECK(!bus.was_published_by("dock"));

    // The _UNSET sentinel: an update without source leaves the tag.
    SelectionPatch patch2;
    patch2.depth_range = std::optional<std::pair<double, double>>{{0, 10}};
    bus.update(patch2);
    CHECK(bus.source_widget_id() && *bus.source_widget_id() == "map");

    // Explicit clear (seismic_cursor = None clears the field).
    bus.publish_seismic_cursor(SeismicCursorState{1.0, 2.0, 3.0}, "seis");
    CHECK(bus.state().seismic_cursor.has_value());
    bus.publish_seismic_cursor(std::nullopt, "seis");
    CHECK(!bus.state().seismic_cursor.has_value());

    // clear() resets every field.
    bus.clear();
    CHECK(!bus.state().active_well_id.has_value());
    CHECK(bus.state().selected_well_ids.empty());
    CHECK(!bus.state().depth_cursor.has_value());
    CHECK(bus.state().custom_attributes.empty());
}

void test_view_coordination() {
    double now = 0.0;
    SelectionBus bus([&now] { return now; });
    FakeHub hub;
    ViewCoordinationCore core(bus, &hub, [&now] { return now; });
    core.attach_to_bus();

    core.bind_project(make_wells_root());
    CHECK_EQ(hub.wells.size(), 2);
    CHECK_EQ(hub.seismic_grid_calls, 1);
    CHECK_EQ(core.bound_well_ids().count("W-1"), 1);

    // Both directions resolve to the (canonical name, entity id) pair.
    const auto [name, entity] = core.resolve_well_key("w1");
    CHECK(name && *name == "W-1");
    CHECK(entity && *entity == "w1");
    const auto [name2, entity2] = core.resolve_well_key("W-1");
    CHECK(name2 && *name2 == "W-1");
    CHECK(entity2 && *entity2 == "w1");

    // Well selection routes the canonical name to the dock + select sinks.
    std::string dock_well, log_well;
    core.set_well_dock_sink([&](std::string w) { dock_well = w; });
    core.set_well_log_select_sink([&](std::string w) { log_well = w; });
    core.publish_well_selection("w1", ViewCoordinationCore::SOURCE_MAP);
    CHECK_EQ(dock_well, "W-1");
    CHECK_EQ(log_well, "W-1");

    // The depth cursor refuses without a calibration (never guesses).
    CHECK(!core.publish_depth_cursor("W-1", 150.0,
                                     ViewCoordinationCore::SOURCE_WELL_LOG));
    hub.md_cursor = std::make_tuple(10.0, 20.0, 500.0);
    int focus_il = -1;
    core.set_seismic_focus_sink(
        [&](int il, int, double) { focus_il = il; });
    CHECK(core.publish_depth_cursor("W-1", 150.0,
                                    ViewCoordinationCore::SOURCE_WELL_LOG));
    CHECK_EQ(focus_il, 10);
    CHECK(bus.state().depth_cursor.has_value());
    CHECK_EQ(bus.state().depth_cursor->first, "W-1");

    // bind_project ran its own clear first; the explicit one is #2.
    core.clear_project();
    CHECK_EQ(hub.clear_count, 2);
    CHECK(core.bound_well_ids().empty());
}

void test_map_actions() {
    CHECK(!map_tool_ids().empty());
    CHECK(!map_command_ids().empty());
    CHECK(!map_surface_extension_ids().empty());
    const auto& specs = action_specs();
    CHECK(specs.count("pan") == 1);
    const auto& pan = specs.at("pan");
    CHECK(pan.canvas_interaction);
    CHECK_EQ(pan.group, tool_policy::group_of("pan"));

    tool_policy::ToolAvailability verdict;
    verdict.enabled = false;
    verdict.visible = true;
    verdict.checked = false;
    verdict.disabled_reason = "需要编图页";
    const auto plan = availability_text("pan", verdict, std::nullopt);
    CHECK(!plan.enabled);
    CHECK(plan.tooltip == pan.label + "\n需要编图页");
    CHECK(plan.status_tip == pan.label + "（需要编图页）");

    const auto entries = toolbar_plan(
        {{"pan", "zoom_in"}, {"full_extent"}, {"select", "vertex"}});
    // group, lone id (no separator), separator before the second group.
    CHECK_EQ(entries.size(), 6);
    CHECK(entries[0].action_id == "pan");
    CHECK(!entries[2].separator && entries[2].action_id == "full_extent");
    CHECK(entries[3].separator);
    CHECK(entries[4].action_id == "select");
}

void test_project_save() {
    std::vector<std::string> calls;
    auto api = std::make_shared<FakeSaveApi>("/tmp/demo.paleo.json", &calls);
    auto task = std::make_shared<ProjectSaveTaskState>();
    task->generation = 3;
    task->api = api;

    auto spec = make_project_save_job_spec(api, task->prepared, task);
    InlineJobRunner runner;
    UiJobOutcome outcome;
    runner.start(std::move(spec),
                 [&](const UiJobOutcome& o) { outcome = o; });
    CHECK_EQ(calls.size(), 1);  // only execute ran (prepare is host-side)
    CHECK_EQ(calls[0], "execute");
    CHECK(outcome.state == job::JobState::done);
    CHECK(task->outcome_stats.has_value());
    CHECK_EQ(task->outcome_stats->bytes_written, 42);

    CHECK(may_commit_drained_save(*task, "/tmp/demo.paleo.json"));
    CHECK(!may_commit_drained_save(*task, "/tmp/other.paleo.json"));
    task->committed.store(true);
    CHECK(!may_commit_drained_save(*task, "/tmp/demo.paleo.json"));
}

void test_project_controller() {
    project::ProjectDocument doc =
        project::ProjectDocument::create_new("demo", "");
    auto* doc_ptr = &doc;
    std::optional<fs::path> path;
    int shell_refreshes = 0;
    std::vector<std::string> errors;

    ProjectHostApi host;
    host.document = [&] { return doc_ptr; };
    host.replace_document = [&](project::ProjectDocument&& next) {
        doc = std::move(next);
        doc_ptr = &doc;
    };
    host.project_path = [&] { return path; };
    host.set_project_path = [&](const std::optional<fs::path>& p) {
        path = p;
    };
    host.refresh_shell = [&](bool) { ++shell_refreshes; };
    host.show_error = [&](const std::string& t, const std::string& m) {
        errors.push_back(t + ":" + m);
    };

    // Unsaved project → choose_save_project drives save-as (the real
    // ProjectManager writes the payload; /tmp is fine for a smoke test).
    // The seam bag is captured BY VALUE at construction — set it here.
    host.choose_save_project = [] {
        return std::optional<fs::path>("/tmp/ui14_smoke.paleo.json");
    };

    std::vector<std::string> save_calls;
    ProjectSaveApiFactory factory = [&](const fs::path& p) {
        return std::make_unique<FakeSaveApi>(p, &save_calls);
    };
    InlineJobRunner runner;

    ProjectControllerCore core(host, CatalogRuntimeApi{},
                               ProjectServiceApi{}, factory, &runner);
    core.new_project("fresh");
    CHECK_EQ(shell_refreshes, 1);
    CHECK(!path.has_value());

    const auto saved = core.save_project();
    if (!saved || !path) {
        for (const auto& e : errors)
            std::fprintf(stderr, "save error: %s\n", e.c_str());
    }
    CHECK(saved && *saved == "/tmp/ui14_smoke.paleo.json");
    CHECK(path && *path == "/tmp/ui14_smoke.paleo.json");

    // Bound path → prepare/execute/commit in order through the runner.
    save_calls.clear();
    CHECK(core.save_project_async());
    CHECK_EQ(save_calls.size(), 3);
    if (save_calls.size() == 3) {
        CHECK_EQ(save_calls[0], "prepare");
        CHECK_EQ(save_calls[1], "execute");
        CHECK_EQ(save_calls[2], "commit");
    }
    CHECK(errors.empty());
}

void test_data_lifecycle() {
    // resources[] Json rows are the document of truth.
    project::ProjectDocument doc =
        project::ProjectDocument::create_new("demo", "");
    doc.root() = domain::Json::parse(R"json({
        "resources": [
            {"id": "r1", "name": "well-a.las", "type": "well_log",
             "path": "data/well-a.las", "status": "indexed", "tags": []},
            {"id": "r2", "name": "cube.sgy", "type": "seismic_3d",
             "path": "data/cube.sgy", "status": "indexed", "tags": ["旧"]}
        ]
    })json");

    std::string status;
    DataPageApi page;
    page.document = [&] { return &doc; };
    page.set_status = [&](const std::string& text) { status = text; };

    int prune_calls = 0;
    DataLifecycleServiceApi services;
    services.prune_asset_links = [&](domain::Json&,
                                     const std::set<std::string>& ids) {
        ++prune_calls;
        CHECK(ids.count("r1") == 1);
        return std::make_pair(2, 0);
    };

    DataLifecycleCore core(page, CatalogRuntimeApi{}, services,
                           LifecycleDialogApi{}, nullptr, nullptr, nullptr);

    // remove_assets: legacy rows leave resources[] + the prune seam runs.
    ResourceItem item;
    item.id = "r1";
    item.name = "well-a.las";
    item.path = "data/well-a.las";
    CHECK(core.remove_assets({ui_data_core::make_asset_handle(item)}));
    CHECK_EQ(prune_calls, 1);
    CHECK_EQ(doc.root()["resources"].size(), 1);

    // bulk_apply_tag writes the legacy row tags (catalog absent → still
    // mirrors honestly into the row).
    ResourceItem item2;
    item2.id = "r2";
    item2.name = "cube.sgy";
    const int tagged = core.bulk_apply_tag(
        {ui_data_core::make_asset_handle(item2)}, "重点", true);
    CHECK_EQ(tagged, 1);
    const auto& row = doc.root()["resources"][0];
    CHECK_EQ(row["tags"].size(), 2);
    CHECK_EQ(row["tags"][1].get<std::string>(), "重点");

    // register_imported_resources without the catalog seam → honest
    // failure surface (empty receipt + recorded failure).
    const auto receipt = core.register_imported_resources({item2});
    CHECK(receipt.empty());
    CHECK(!core.last_registration_failures.empty());
}

void test_workflow() {
    project::ProjectDocument doc =
        project::ProjectDocument::create_new("demo", "");
    doc.root()["factor_map_tasks"] = domain::Json::parse(R"json([
        {"id": "t1", "status": "stale", "factor_type": "砂地比"}
    ])json");
    doc.root()["prediction_tasks"] = domain::Json::parse(R"json([
        {"id": "p1", "result_summary": {"depth_intervals": []},
         "model_metadata": {}}
    ])json");

    std::vector<std::string> infos, warnings, navigations;
    std::map<std::string, std::any> stored_grids;
    int generation = 0;

    WorkflowPageApi pages;
    pages.document = [&] { return &doc; };
    pages.navigate_to = [&](int hub, const std::string& sub) {
        navigations.push_back(std::to_string(hub) + ":" + sub);
    };
    WorkflowDialogApi dialogs;
    dialogs.info = [&](const std::string&, const std::string& text) {
        infos.push_back(text);
    };
    dialogs.warning = [&](const std::string&, const std::string& text) {
        warnings.push_back(text);
    };
    WorkflowServiceApi services;
    services.build_affected_plan = [](const domain::Json&) {
        workflow_runtime::RecomputePlan plan;
        workflow_runtime::RecomputeStep step;
        step.operation = "factor_map";
        step.domain_task_id = "t1";
        step.label = "单因素图";
        plan.steps.push_back(step);
        return plan;
    };
    // Demo compiler seam (set before construction — the bag is captured
    // by value).
    services.compile_map_draft = [](domain::Json& root, int seed) {
        CHECK_EQ(seed, 0);
        root["paleomap_documents"] = domain::Json::array(
            {domain::Json::object({{"id", "demo"}})});
    };
    FactorRecomputeSeams factor_seams;
    factor_seams.interpolate_fn = [](domain::Json& staged,
                                     const domain::Json&) {
        staged["status"] = "complete";
    };
    factor_seams.grid_peek_fn = [](const std::string&) {
        return std::any(7);
    };
    PrepareGenerationApi gen;
    gen.next = [&] { return ++generation; };
    gen.current = [&] { return generation; };
    LiveFactorGridApi grids;
    grids.store = [&](const std::string& id, std::any grid) {
        stored_grids[id] = std::move(grid);
    };
    grids.fingerprint = [](const std::any&) {
        return std::optional<std::string>("fp");
    };
    grids.clear_if_fingerprint = [](const std::string&,
                                    const std::string&) { return true; };

    InlineJobRunner recompute_job, prepare_job;
    WorkflowCore core(pages, dialogs, services, CatalogRuntimeApi{}, gen,
                      grids, factor_seams, ui_workers::FactorPrepareSeams{},
                      &recompute_job, &prepare_job);

    core.request_recompute();
    // The staged task committed onto the live document + grid stored.
    CHECK_EQ(doc.root()["factor_map_tasks"][0]["status"]
                 .get<std::string>(),
             "complete");
    CHECK(stored_grids.count("t1") == 1);
    CHECK(!infos.empty());

    // Non-spatial scientific result → honest block (never fake squares).
    core.on_seismic_send_to_mapping();
    CHECK(!warnings.empty());
    CHECK(warnings.back().find("无可编绘") != std::string::npos);

    // Demo task → the demo compiler seam runs.
    doc.root()["prediction_tasks"][0]["result_summary"]["demo"] = true;
    warnings.clear();
    core.on_seismic_send_to_mapping();
    CHECK(warnings.empty());
    CHECK_EQ(doc.root()["paleomap_documents"].size(), 1);
    CHECK(!navigations.empty());
}

}  // namespace

int main() {
    struct Case {
        const char* name;
        void (*fn)();
    };
    const Case cases[] = {
        {"selection_bus", test_selection_bus},
        {"view_coordination", test_view_coordination},
        {"map_actions", test_map_actions},
        {"project_save", test_project_save},
        {"project_controller", test_project_controller},
        {"data_lifecycle", test_data_lifecycle},
        {"workflow", test_workflow},
    };
    for (const auto& test : cases) {
        const int before = g_failures;
        test.fn();
        std::fprintf(stderr, "%s %s\n",
                     g_failures == before ? "PASS" : "FAILED", test.name);
    }
    if (g_failures != 0) {
        std::fprintf(stderr, "ui_controllers.core_smoke: %d failure(s)\n",
                     g_failures);
        return 1;
    }
    return 0;
}
