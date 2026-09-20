// platform.closure_data — V14-DATA-LINEAGE (P4) wiring battery:
//   * nav-tree population from a synthetic project document (well group,
//     role-grouped children with REAL registry display labels, geological
//     entities, coordinate flags);
//   * the Qt-free ingest-plan review model (decisions / roles / primary
//     recomputation / validation issues / summary);
//   * EntityDataView → WellDataViewSlice conversion fidelity;
//   * the review dialog offscreen (stub callbacks, run_execute);
//   * the folder-ingest production body E2E over a temp project (build →
//     rows → execute → links saved) + lineage/impact read helpers.

#include <QApplication>
#include <QString>

#include <pwb/application/adapters/data_store.hpp>
#include <pwb/catalog/models.hpp>
#include <pwb/catalog/repository.hpp>
#include <pwb/data/entity_identity.hpp>
#include <pwb/data/entity_workspace.hpp>
#include <pwb/data/ingest_exec.hpp>
#include <pwb/data/ingest_plan.hpp>
#include <pwb/data/role_registry.hpp>
#include <pwb/domain/json.hpp>
#include <pwb/project/manager.hpp>
#include <pwb/project/paths.hpp>
#include <pwb/ui_pages_data/ingest_plan_model.hpp>
#include <pwb/ui_pages_data/ingest_plan_rows.hpp>
#include <pwb/ui_pages_data/nav_tree_model.hpp>
#include <pwb/ui_pages_data/qt/ingest_plan_dialog.hpp>
#include <pwb/ui_wellseis/qt/well_detail_panel.hpp>

#include "closure_data_workspace.hpp"
#include "test_framework.hpp"

#include <chrono>
#include <filesystem>
#include <fstream>
#include <functional>
#include <optional>
#include <string>
#include <vector>

namespace fs = std::filesystem;
using Json = pwb::domain::Json;
using namespace pwb::app::v14_lineage;
using pwb::ui_pages_data::PlanItemRow;

namespace {

bool contains(const std::string& haystack, const std::string& needle) {
    return haystack.find(needle) != std::string::npos;
}

// ---------------------------------------------------------------------------
// 1. ingest-plan review model (pure DTOs — no Qt, no Pwb::Data here)
// ---------------------------------------------------------------------------

PlanItemRow make_row(const std::string& filename, const std::string& role,
                     const std::string& entity_id,
                     bool primary_required = false) {
    PlanItemRow row;
    row.path = "C:/import/" + filename;
    row.filename = filename;
    row.type = "well_log";
    row.role = role;
    row.allowed_roles = {"well_head", "well_log", "trajectory", "tops",
                         "other"};
    row.entity_type = "well";
    row.entity_id = entity_id;
    row.entity_name = "W1";
    row.strategy = "directory_hint";
    row.decision = pwb::ui_pages_data::kPlanDecisionPending;
    row.include = true;
    row.primary_required = primary_required;
    return row;
}

void test_ingest_plan_model() {
    using pwb::ui_pages_data::IngestPlanModel;
    using pwb::ui_pages_data::kPlanDecisionAccept;
    using pwb::ui_pages_data::kPlanDecisionSkip;

    // Nothing accepted → honest refusal.
    {
        IngestPlanModel model({make_row("a.las", "well_log", "w1"),
                               make_row("b.las", "well_log", "w1")});
        PWB_CHECK(!model.validation().empty());
        PWB_CHECK(contains(pwb::ui_pages_data::IngestPlanModel(
                               {make_row("a.las", "well_log", "w1")})
                               .validation()
                               .front(),
                           "没有接受"));
        auto summary = model.summary();
        PWB_CHECK(summary.total == 2);
        PWB_CHECK(summary.pending == 2);
        PWB_CHECK(summary.accepted == 0);
    }

    // Single-primary invariant preview: two well_head items compete while
    // both accepted; skipping one promotes the survivor.
    {
        IngestPlanModel model(
            {make_row("head1.dat", "well_head", "w1", /*primary=*/true),
             make_row("head2.dat", "well_head", "w1", /*primary=*/true),
             make_row("log.las", "well_log", "w1")});
        model.set_all_decisions(kPlanDecisionAccept);
        {
            const auto issues = model.validation();
            bool competition = false;
            for (const auto& issue : issues)
                competition = competition || contains(issue, "竞争主件");
            PWB_CHECK_MSG(competition, "expected primary competition issue");
        }
        // Recompute: exactly one accepted well_head remains → primary.
        model.set_decision(1, kPlanDecisionSkip);  // head2 skipped
        PWB_CHECK(model.row(0)->decision == kPlanDecisionAccept);
        PWB_CHECK(model.row(0)->primary);
        PWB_CHECK(!model.row(1)->primary);
        bool competition = false;
        for (const auto& issue : model.validation())
            competition = competition || contains(issue, "竞争主件");
        PWB_CHECK(!competition);
        // Role vocabulary violation surfaces as an issue (never coerced).
        model.set_role(2, "not_a_role");
        bool vocab = false;
        for (const auto& issue : model.validation())
            vocab = vocab || contains(issue, "角色词汇表");
        PWB_CHECK_MSG(vocab, "expected role vocabulary issue");
        model.set_role(2, "well_log");
        // include=false on the sole primary demotes the slot; log.las
        // (index 2) is still accepted, so the plan stays executable and
        // validation reports nothing.
        model.toggle_include(0);
        PWB_CHECK(!model.row(0)->primary);
        PWB_CHECK(model.validation().empty());
        // Excluding the last accepted row leaves nothing to execute.
        model.toggle_include(2);
        {
            bool empty_plan = false;
            for (const auto& issue : model.validation())
                empty_plan = empty_plan || contains(issue, "没有接受任何条目");
            PWB_CHECK_MSG(empty_plan, "expected no-accepted-items issue");
        }
        model.toggle_include(2);
        model.toggle_include(0);
        PWB_CHECK(model.validation().empty());
    }

    // Entity resolution failure: unresolved id + not-new → issue.
    {
        auto row = make_row("orphan.las", "well_log", "");
        row.strategy = "none";
        IngestPlanModel model({row});
        model.set_all_decisions(kPlanDecisionAccept);
        bool unresolved = false;
        for (const auto& issue : model.validation())
            unresolved = unresolved || contains(issue, "未解析");
        PWB_CHECK_MSG(unresolved, "expected unresolved-entity issue");
    }
}

// ---------------------------------------------------------------------------
// 2. nav-tree population
// ---------------------------------------------------------------------------

void test_nav_tree_population() {
    const std::string text = R"({
        "wells": [
            {"id": "w1", "name": "Well-1", "uwi": "1001",
             "coordinate_status": "ok", "spatial_scope": "workarea"},
            {"id": "w2", "name": "Well-2", "uwi": "1002"}
        ],
        "seismic_surveys": [{"id": "s1", "name": "Survey-1"}],
        "geological_entities": [{"id": "g1", "kind": "geological",
                                 "name": "Horizon-H2"}],
        "entity_asset_links": [
            {"id": "l1", "entity_type": "well", "entity_id": "w1",
             "asset_id": "ast1", "role": "well_log"},
            {"id": "l2", "entity_type": "well", "entity_id": "w1",
             "asset_id": "ast2", "role": "well_log"},
            {"id": "l3", "entity_type": "well", "entity_id": "w1",
             "asset_id": "ast3", "role": "well_head"}
        ]
    })";
    const auto root = Json::parse(text);

    pwb::ui_pages_data::NavTreeModel model;
    model.build();
    populate_nav_tree(model, root);

    // Well rows exist and are findable.
    PWB_CHECK(model.find_entity_row("w1").has_value());
    PWB_CHECK(model.find_entity_row("w2").has_value());
    PWB_CHECK(model.find_entity_row("s1").has_value());
    PWB_CHECK(model.find_entity_row("g1").has_value());
    PWB_CHECK(!model.find_entity_row("nope").has_value());

    // w2 lacks coordinate_status → schema default "missing" → ⚠坐标 flag.
    const auto w2_row = model.find_entity_row("w2");
    PWB_CHECK(w2_row.has_value());
    PWB_CHECK(contains(model.rows()[*w2_row].text, "⚠坐标"));

    // Role-grouped children under w1 use the REAL registry display
    // (测井曲线) with the link count, then per-asset leaves.
    const auto w1_row = model.find_entity_row("w1");
    PWB_CHECK(w1_row.has_value());
    bool log_role_row = false;
    bool head_role_row = false;
    bool asset_leaf = false;
    for (const auto& row : model.rows()) {
        if (row.parent == *w1_row && contains(row.text, "测井曲线") &&
            contains(row.text, "(2)")) {
            log_role_row = true;
        }
        if (row.parent == *w1_row && contains(row.text, "井身/井位")) {
            head_role_row = true;
        }
        if (row.key == "asset:ast1") asset_leaf = true;
    }
    PWB_CHECK_MSG(log_role_row, "well_log role group (registry display)");
    PWB_CHECK_MSG(head_role_row, "well_head role group (registry display)");
    PWB_CHECK_MSG(asset_leaf, "linked asset leaf row");

    // Registry sanity from the domain side the seams bind to.
    PWB_CHECK(pwb::data::role_display("well_log") == std::string("测井曲线"));
    PWB_CHECK(pwb::data::primary_required("well_head"));
    PWB_CHECK(!pwb::data::primary_required("well_log"));

    // build_nav_project_view mirrors the schema defaults.
    const auto view = build_nav_project_view(root);
    PWB_CHECK(view.wells.size() == 2);
    PWB_CHECK(view.wells[1].coordinate_status == "missing");
    PWB_CHECK(view.wells[1].spatial_scope == "workarea");
    PWB_CHECK(view.seismic_surveys.size() == 1);
    PWB_CHECK(view.geological_entities.size() == 1);
    PWB_CHECK(view.entity_asset_links.size() == 3);
    PWB_CHECK(view.entity_asset_links[0].role == "well_log");
}

// ---------------------------------------------------------------------------
// 3. well-detail slice conversion
// ---------------------------------------------------------------------------

void test_well_detail_slice() {
    pwb::data::EntityDataView view;
    view.entity_type = "well";
    view.entity_id = "w1";
    view.name = "Well-1";
    view.uwi = "1001";

    pwb::data::RoleSlot slot;
    slot.role = "well_log";
    slot.display = "测井曲线";
    pwb::data::AssetSummary member;
    member.asset_id = "ast1";
    member.name = "log1.las";
    member.is_primary = true;
    member.version_count = 2;
    member.current_version_id = "ver-9";
    slot.members.push_back(member);
    pwb::data::AssetSummary unresolved_member;
    unresolved_member.asset_id = "astX";
    unresolved_member.name = "<未注册资产>";
    unresolved_member.unresolved = true;
    slot.unresolved.push_back(unresolved_member);
    view.role_slots.push_back(slot);

    pwb::data::StaleLite stale;
    stale.version_id = "ver-3";
    stale.reason = "ancestor evolved";
    stale.pinned = true;
    view.stale_items.push_back(stale);

    pwb::data::WorkingCopyLite edit;
    edit.working_id = "wc-1";
    edit.source_version_id = "ver-9";
    edit.state = "open";
    view.uncommitted_edits.push_back(edit);
    view.missing_source_asset_ids = {"ast7"};

    const auto slice = well_detail_slice(view);
    PWB_CHECK(slice.well_name == "Well-1");
    PWB_CHECK(slice.uwi == "1001");
    PWB_CHECK(slice.role_slots.size() == 1);
    PWB_CHECK(slice.role_slots[0].role == "well_log");
    PWB_CHECK(slice.role_slots[0].unresolved);  // unresolved member present
    PWB_CHECK(slice.role_slots[0].members.size() == 1);
    PWB_CHECK(slice.role_slots[0].members[0].name == "log1.las");
    PWB_CHECK(slice.role_slots[0].members[0].is_primary);
    PWB_CHECK(slice.role_slots[0].members[0].version_count == 2);
    PWB_CHECK(slice.role_slots[0].members[0].current_version_id == "ver-9");
    PWB_CHECK(slice.stale_items.size() == 1);
    PWB_CHECK(slice.stale_items[0].version_id == "ver-3");
    PWB_CHECK(slice.stale_items[0].pinned);
    PWB_CHECK(slice.uncommitted_edits.size() == 1);
    PWB_CHECK(slice.uncommitted_edits[0].state == "open");
    PWB_CHECK(slice.uncommitted_edits[0].source_version_id == "ver-9");
    PWB_CHECK(slice.missing_source_asset_ids == view.missing_source_asset_ids);

    // Host over a panel: unknown well clears, known well fills.
    pwb::ui_wellseis::qt::WellDetailPanel panel;
    WellDetailHost host(&panel);
    const auto project_json = Json::parse(R"({"wells": []})");
    host.reconfigure(&project_json, fs::path(), fs::path());
    PWB_CHECK(host.bound());
    PWB_CHECK(!host.update("missing-well"));
}

// ---------------------------------------------------------------------------
// 4. review dialog offscreen (stub callbacks)
// ---------------------------------------------------------------------------

void test_ingest_dialog_offscreen() {
    std::vector<PlanItemRow> received;
    QString executed_summary;
    bool cancelled = false;

    pwb::ui_pages_data::qt::IngestPlanDialog dialog(
        {make_row("a.las", "well_log", "w1"),
         make_row("b.las", "well_log", "w1")},
        [&received](const std::vector<PlanItemRow>& rows) -> std::string {
            received = rows;
            return "stub 导入 2";
        },
        [&cancelled]() { cancelled = true; });

    // Blocked while nothing is accepted; 全部接受 clears the way.
    PWB_CHECK(!dialog.run_execute());
    PWB_CHECK(received.empty());
    dialog.accept_all();
    PWB_CHECK(dialog.rows().size() == 2);
    PWB_CHECK(dialog.rows()[0].decision ==
              pwb::ui_pages_data::kPlanDecisionAccept);
    QObject::connect(&dialog,
                     &pwb::ui_pages_data::qt::IngestPlanDialog::executed,
                     &dialog,
                     [&executed_summary](const QString& summary) {
                         executed_summary = summary;
                     });
    PWB_CHECK(dialog.run_execute());
    PWB_CHECK(received.size() == 2);
    PWB_CHECK(executed_summary == QStringLiteral("stub 导入 2"));
    PWB_CHECK(dialog.result() == QDialog::Accepted);  // closed, no exec()
    PWB_CHECK(!cancelled);
}

// ---------------------------------------------------------------------------
// 5. folder ingest E2E + lineage/impact helpers (temp project)
// ---------------------------------------------------------------------------

fs::path make_temp_project(fs::path dir) {
    auto document = pwb::project::ProjectDocument::create_new(
        "v14-lineage-test", "test-region");
    auto well = Json::object();
    well["id"] = "w1";
    well["name"] = "Well-1";
    well["uwi"] = "1001";
    well["coordinate_status"] = "ok";
    well["spatial_scope"] = "workarea";
    document.root()["wells"] = Json::array({well});

    const fs::path project_file = dir / "v14-demo.paleo.json";
    pwb::project::ProjectManager manager(project_file);
    const auto save = manager.save(document);
    PWB_CHECK_MSG(save.is_ok(), "temp project save failed");
    return project_file;
}

void write_las(const fs::path& path) {
    std::ofstream out(path, std::ios::binary);
    out << "~VERSION INFORMATION\n"
        << "VERS.                  2.0 : CWLS LOG ASCII STANDARD\n"
        << "~WELL\n"
        << "#MNEM.MEASURE UNIT     DATA\n"
        << "STRT.M              100.0 : First index\n"
        << "~CURVE INFORMATION\n"
        << "#MNEM.UNIT           API CODE\n"
        << "DEPT.M               :\n"
        << "~ASCII LOG DATA\n"
        << "100.0\n"
        << "101.0\n";
}

void test_folder_ingest_e2e() {
    const auto stamp = std::to_string(
        std::chrono::steady_clock::now().time_since_epoch().count());
    const fs::path dir =
        fs::temp_directory_path() / ("pwb-v14-lineage-" + stamp);
    fs::create_directories(dir / "Well-1");
    write_las(dir / "Well-1" / "log1.las");
    write_las(dir / "Well-1" / "log2.las");
    const fs::path project_file = make_temp_project(dir);

    // Phase 1 (build, pure) over a fresh read of the project document.
    pwb::project::ProjectManager manager(project_file);
    auto loaded = manager.load();
    PWB_CHECK_MSG(loaded.is_ok(), "temp project load failed");
    pwb::project::ProjectDocument document =
        std::move(loaded.value().document);

    pwb::data::IngestPlanOptions options;
    pwb::catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(project_file));
    auto catalog_document = repository.open_read_only();
    if (catalog_document.is_ok()) {
        options.catalog = &catalog_document.value();
    }
    const auto plan = pwb::data::build_ingest_plan(dir / "Well-1", document,
                                                   options);
    PWB_CHECK_MSG(plan.items.size() == 2,
                  "expected 2 planned LAS items for the well folder");

    // Adapter: rows carry the registry vocabulary + primary policy.
    auto rows = pwb::ui_pages_data::ingest_plan_rows(plan);
    PWB_CHECK(rows.size() == 2);
    PWB_CHECK(rows[0].entity_type == "well");
    PWB_CHECK(rows[0].entity_id == "w1");
    PWB_CHECK(rows[0].role == "well_log");
    bool vocabulary = false;
    for (const auto& role : rows[0].allowed_roles)
        vocabulary = vocabulary || role == "well_log";
    PWB_CHECK(vocabulary);
    for (auto& row : rows)
        row.decision = pwb::ui_pages_data::kPlanDecisionAccept;

    // Phase 2 (production execute body): import + bind + save.
    const std::string summary =
        execute_folder_ingest(project_file, plan, rows);
    PWB_CHECK_MSG(contains(summary, "导入 2"),
                  ("unexpected summary: " + summary).c_str());
    PWB_CHECK(contains(summary, "绑定"));

    // The saved document carries the entity↔asset links (single-primary
    // semantics live in the domain; two optional well_log links are legal).
    {
        std::ifstream in(project_file);
        Json saved = Json::parse(in);
        const auto links = saved.find("entity_asset_links");
        PWB_CHECK_MSG(links != saved.end() && links->is_array(),
                      "entity_asset_links missing from saved project");
        PWB_CHECK_MSG(links->size() == 2, "expected 2 bound links");
    }

    // Lineage helper over the imported RAW versions.
    {
        auto reopened = repository.open_read_only();
        PWB_CHECK_MSG(reopened.is_ok(), "catalog reopen failed");
        PWB_CHECK(!reopened.value().versions.empty());
        const std::string version_id =
            reopened.value().versions.front().id.str();
        const auto lineage = lineage_rows(project_file, version_id);
        PWB_CHECK_MSG(lineage.ok,
                      ("lineage failed: " + lineage.error).c_str());
        PWB_CHECK(lineage.node_count >= 1);
        PWB_CHECK(!lineage.rows.empty());
        PWB_CHECK(lineage.rows.front().version_id == version_id);
        PWB_CHECK(lineage.rows.front().stage == "raw");

        const auto impact =
            delete_impact_summary(project_file, version_id, {});
        PWB_CHECK_MSG(impact.ok, ("impact failed: " + impact.error).c_str());
        bool counted = false;
        for (const auto& line : impact.lines)
            counted = counted || contains(line, "受影响版本");
        PWB_CHECK(counted);
        PWB_CHECK(impact.linked_entities >= 0);
        PWB_CHECK(impact.live_descendants >= 0);
    }

    std::error_code cleanup;
    fs::remove_all(dir, cleanup);
}

}  // namespace

int main(int argc, char** argv) {
    QApplication app(argc, argv);

    test_ingest_plan_model();
    test_nav_tree_population();
    test_well_detail_slice();
    test_ingest_dialog_offscreen();
    test_folder_ingest_e2e();

    return ::pwb::test::report("platform.closure_data");
}
