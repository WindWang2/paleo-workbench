// platform.data_governance — ws0 治理闭环 UI 电池（offscreen）：
//   * snapshot 行携带 tags/role/关联对象列（真实 DataFacade 快照 →
//     asset_rows_from_snapshot）；
//   * workspace 过滤语义（标签 and/or、entity_role、回收站空集 guard）——
//     真实 install_data_workspace + install_data_governance 装配后的
//     FilterQuery 路径；
//   * 四个治理对话框驱动真实写路径（无需 exec）；
//   * run_trash_flow 的 impact 预检 decision seam（拒绝/放行两路）；
//   * AssetSelectionBus::republish_current 写后刷新语义；
//   * DataLineagePanel 第三页签（影响分析）存在与诚实降级。
#include <QApplication>
#include <QListWidget>

#include <pwb/application/adapters/data_store.hpp>
#include <pwb/catalog/models.hpp>
#include <pwb/catalog/repository.hpp>
#include <pwb/data/facade.hpp>
#include <pwb/data/governance.hpp>
#include <pwb/data/ingest_exec.hpp>
#include <pwb/data/ingest_plan.hpp>
#include <pwb/data/session.hpp>
#include <pwb/domain/json.hpp>
#include <pwb/project/manager.hpp>
#include <pwb/project/paths.hpp>
#include <pwb/ui_pages_data/asset_view.hpp>
#include <pwb/ui_pages_data/filter_query.hpp>
#include <pwb/ui_pages_data/qt/asset_selection_bus.hpp>
#include <pwb/ui_pages_data/qt/data_workspace.hpp>
#include <pwb/ui_pages_data/qt/data_asset_table.hpp>

#include "closure_data_workspace.hpp"
#include "closure_preview_adapters.hpp"
#include "data_governance_dialogs.hpp"
#include "data_governance_workspace.hpp"
#include "data_lineage_panel.hpp"
#include "test_framework.hpp"

#include <chrono>
#include <filesystem>
#include <fstream>
#include <optional>
#include <string>
#include <vector>

namespace fs = std::filesystem;
using Json = pwb::domain::Json;
namespace gov = pwb::data::governance;

namespace {

bool contains(const std::string& haystack, const std::string& needle) {
    return haystack.find(needle) != std::string::npos;
}

std::string stamp() {
    return std::to_string(
        std::chrono::steady_clock::now().time_since_epoch().count());
}

void write_las(const fs::path& path) {
    std::ofstream out(path, std::ios::binary);
    out << "~VERSION INFORMATION\n"
        << "VERS.                  2.0 : CWLS LOG ASCII STANDARD\n"
        << "~WELL\n"
        << "STRT.M              100.0 : First index\n"
        << "~CURVE INFORMATION\n"
        << "DEPT.M               :\n"
        << "~ASCII LOG DATA\n"
        << "100.0\n"
        << "101.0\n";
}

fs::path make_temp_project(fs::path dir) {
    auto document = pwb::project::ProjectDocument::create_new(
        "governance-ui-test", "test-region");
    Json well = Json::object();
    well["id"] = "w1";
    well["name"] = "Well-1";
    well["uwi"] = "1001";
    well["coordinate_status"] = "ok";
    well["spatial_scope"] = "workarea";
    document.root()["wells"] = Json::array({well});
    const fs::path project_file = dir / "governance-ui.paleo.json";
    pwb::project::ProjectManager manager(project_file);
    PWB_CHECK_MSG(manager.save(document).is_ok(), "temp project save failed");
    return project_file;
}

struct Fixture {
    fs::path dir;
    fs::path project_file;
    std::string asset_id;
};

// 真实导入 2 个 LAS（绑定 w1，角色 well_log）。
Fixture make_fixture(const std::string& tag) {
    Fixture fixture;
    fixture.dir = fs::temp_directory_path() /
                  ("pwb-gov-ui-" + tag + "-" + stamp());
    fs::create_directories(fixture.dir / "Well-1");
    write_las(fixture.dir / "Well-1" / "log1.las");
    write_las(fixture.dir / "Well-1" / "log2.las");
    fixture.project_file = make_temp_project(fixture.dir);

    pwb::project::ProjectManager manager(fixture.project_file);
    auto loaded = manager.load();
    PWB_CHECK_MSG(loaded.is_ok(), "project load failed");
    pwb::data::IngestPlanOptions options;
    auto plan = pwb::data::build_ingest_plan(
        fixture.dir / "Well-1", loaded.value().document, options);
    PWB_CHECK(!plan.items.empty());
    for (auto& item : plan.items) item.decision = "accept";
    const std::string summary = pwb::app::v14_lineage::execute_folder_ingest(
        fixture.project_file, plan, {});
    PWB_CHECK_MSG(contains(summary, "导入 2"), "expected 2 imports");

    pwb::catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(fixture.project_file));
    auto catalog = repository.open_read_only();
    PWB_CHECK(catalog.is_ok());
    if (!catalog.value().assets.empty()) {
        fixture.asset_id = catalog.value().assets.front().id.str();
    }
    PWB_CHECK(!fixture.asset_id.empty());
    return fixture;
}

pwb::ui_pages_data::AssetRow row_of(const std::string& id,
                                    const std::string& name,
                                    const std::vector<std::string>& tags,
                                    const std::string& role) {
    pwb::ui_pages_data::AssetRow row;
    row.kind = pwb::ui_pages_data::AssetKind::Resource;
    row.view.id = id;
    row.view.name = name;
    row.view.type = "well_log";
    row.view.status = "indexed";
    row.view.tags = tags;
    row.view.role = role;
    return row;
}

}  // namespace

// ---------------------------------------------------------------------------
// 1. snapshot 行 → tags/role/关联对象列
// ---------------------------------------------------------------------------
void test_rows_carry_governance_fields() {
    const auto fixture = make_fixture("rows");
    PWB_CHECK(gov::add_tags(fixture.project_file, {fixture.asset_id},
                            {"qc-pass"})
                  .ok);
    PWB_CHECK(gov::set_asset_link_role(fixture.project_file, "well", "w1",
                                       fixture.asset_id, "well_log", "tops")
                  .ok);

    pwb::data::DataFacade facade(fixture.project_file);
    const auto snapshot = facade.open_snapshot();
    PWB_CHECK(snapshot.is_ok());
    const auto rows =
        pwb::closure_preview::asset_rows_from_snapshot(snapshot.value());
    PWB_CHECK(rows.size() == 2);
    bool role_checked = false;
    bool tag_checked = false;
    bool link_checked = false;
    for (const auto& row : rows) {
        if (row.view.id != fixture.asset_id) continue;
        PWB_CHECK(row.view.role == "tops");
        PWB_CHECK(!row.view.tags.empty());
        PWB_CHECK(row.view.tags.front() == "qc-pass");
        PWB_CHECK(row.view.linked_label == "Well-1");
        role_checked = true;
        tag_checked = true;
        link_checked = true;
    }
    PWB_CHECK(role_checked);
    PWB_CHECK(tag_checked);
    PWB_CHECK(link_checked);

    std::error_code cleanup;
    fs::remove_all(fixture.dir, cleanup);
}

// ---------------------------------------------------------------------------
// 2. workspace 过滤语义（真实装配）
// ---------------------------------------------------------------------------
void test_workspace_filter_semantics() {
    using pwb::ui_pages_data::FilterQuery;
    pwb::ui_pages_data::qt::DataWorkspace workspace;
    pwb::ui_pages_data::qt::AssetSelectionBus bus;
    workspace.bind_selection_bus(&bus);

    std::vector<pwb::ui_pages_data::AssetRow> rows;
    rows.push_back(row_of("a1", "Asset One", {"qc", "batch-a"}, "well_log"));
    rows.push_back(row_of("a2", "Asset Two", {"qc"}, "tops"));
    rows.push_back(row_of("a3", "Asset Three", {}, "well_log"));
    bus.set_assets(rows, QStringLiteral("p1"));

    // 真实装配（store 空 → 导航树诚实降级，过滤与工具条照常装配）。
    pwb::app::v14_lineage::install_data_workspace(workspace, &bus, nullptr,
                                                  nullptr, {});
    pwb::app::data_governance::Install gov_install;
    gov_install.workspace = &workspace;
    gov_install.bus = &bus;
    pwb::app::data_governance::install_data_governance(gov_install);

    auto* table = workspace.asset_table();
    PWB_CHECK(table != nullptr);

    auto set_query = [&](FilterQuery query) {
        table->set_filter_query(query);
        return table->visible_asset_count();
    };

    // 无过滤：全量 live 行。
    {
        FilterQuery query;
        PWB_CHECK(set_query(query) == 3);
    }
    // 标签 and：qc+batch-a 只命中 a1。
    {
        FilterQuery query;
        query.tags = {"qc", "batch-a"};
        query.tag_operator = "and";
        PWB_CHECK(set_query(query) == 1);
    }
    // 标签 or：qc 或 batch-a → a1+a2。
    {
        FilterQuery query;
        query.tags = {"qc", "batch-a"};
        query.tag_operator = "or";
        PWB_CHECK(set_query(query) == 2);
    }
    // legacy 单选 tag 并入。
    {
        FilterQuery query;
        query.tag = std::optional<std::string>("batch-a");
        PWB_CHECK(set_query(query) == 1);
    }
    // 角色等值。
    {
        FilterQuery query;
        query.entity_role = std::optional<std::string>("tops");
        PWB_CHECK(set_query(query) == 1);
    }
    // 回收站视图：行集 live-only → 诚实空集。
    {
        FilterQuery query;
        query.node_type = "trash";
        PWB_CHECK(set_query(query) == 0);
    }
    // 搜索命中标签/角色字段（真实路径：搜索框 → set_search_text，
    // set_filter_query 会以搜索框状态覆写 search_text）。
    {
        FilterQuery reset;  // 清掉上一轮 node_type=trash 残留
        table->set_filter_query(reset);
        table->set_search_text(QStringLiteral("batch-a"));
        PWB_CHECK(table->visible_asset_count() == 1);
        table->set_search_text(QString());
    }
}

// ---------------------------------------------------------------------------
// 3. LinkWellDialog / SetRoleDialog 真实写路径
// ---------------------------------------------------------------------------
void test_link_and_role_dialogs() {
    const auto fixture = make_fixture("dialogs");
    int refresh_count = 0;
    auto refresh = [&refresh_count] { ++refresh_count; };

    // 关联对话框：换角色 + 解除。
    {
        pwb::app::data_governance::LinkWellDialog dialog(
            fixture.project_file, fixture.asset_id, "Asset One", refresh);
        dialog.select_well("w1");
        dialog.set_role_input("tops");
        dialog.set_primary(false);
        PWB_CHECK(dialog.apply_link());
        auto links = gov::links_for_asset(fixture.project_file,
                                          fixture.asset_id);
        bool has_tops = false;
        for (const auto& link : links) has_tops = has_tops || link.role == "tops";
        PWB_CHECK(has_tops);
        PWB_CHECK(refresh_count >= 1);

        // 解除那条 tops 链接（第 row 行 = 刚建的）。
        int tops_row = -1;
        links = gov::links_for_asset(fixture.project_file, fixture.asset_id);
        for (std::size_t i = 0; i < links.size(); ++i) {
            if (links[i].role == "tops") tops_row = static_cast<int>(i);
        }
        PWB_CHECK(tops_row >= 0);
        PWB_CHECK(dialog.apply_unlink(tops_row));
        links = gov::links_for_asset(fixture.project_file, fixture.asset_id);
        bool still_tops = false;
        for (const auto& link : links) still_tops = still_tops || link.role == "tops";
        PWB_CHECK(!still_tops);
    }

    // 角色对话框：well_log → interpretation。
    {
        pwb::app::data_governance::SetRoleDialog dialog(
            fixture.project_file, fixture.asset_id, "Asset One", refresh);
        dialog.select_link(0);
        dialog.set_role_input("interpretation");
        PWB_CHECK(dialog.apply_role());
        const auto links = gov::links_for_asset(fixture.project_file,
                                                fixture.asset_id);
        PWB_CHECK(!links.empty());
        PWB_CHECK(links.front().role == "interpretation");
    }

    std::error_code cleanup;
    fs::remove_all(fixture.dir, cleanup);
}

// ---------------------------------------------------------------------------
// 4. TagsDialog 真实写路径（正规化 + 重开）
// ---------------------------------------------------------------------------
void test_tags_dialog() {
    const auto fixture = make_fixture("tags-dialog");
    pwb::app::data_governance::TagsDialog dialog(fixture.project_file,
                                                 {fixture.asset_id},
                                                 {"Asset One"}, {});
    PWB_CHECK(dialog.apply_add("QC 通过, batch-b"));
    const auto tags = gov::tags_for_assets(fixture.project_file,
                                            {fixture.asset_id});
    PWB_CHECK(tags.size() == 1);
    PWB_CHECK(tags[0].tags.size() == 2);
    PWB_CHECK(dialog.apply_remove("batch-b"));
    const auto after = gov::tags_for_assets(fixture.project_file,
                                             {fixture.asset_id});
    PWB_CHECK(after.size() == 1);
    PWB_CHECK(after[0].tags.size() == 1);
    std::error_code cleanup;
    fs::remove_all(fixture.dir, cleanup);
}

// ---------------------------------------------------------------------------
// 5. run_trash_flow decision seam + TrashDialog 恢复
// ---------------------------------------------------------------------------
void test_trash_flow_and_dialog() {
    const auto fixture = make_fixture("trash-flow");

    auto store = pwb::application::PwbDataStore::open(fixture.project_file,
                                                      nullptr);
    PWB_CHECK(store != nullptr);

    pwb::ui_pages_data::AssetRow row;
    row.view.id = fixture.asset_id;
    row.view.name = "Asset One";

    pwb::app::data_governance::Install install;
    install.store = [store] { return store; };
    int refresh_count = 0;
    install.refresh_notify = [&refresh_count] { ++refresh_count; };
    bool confirmed = false;
    install.confirm_destructive = [&confirmed](const QString&) {
        return confirmed;
    };

    // 派生子版本（让所选资产产生真实下游）。
    {
        pwb::catalog::CatalogRepository repository(
            pwb::project::catalog_sqlite_for(fixture.project_file));
        auto catalog = repository.open_read_only();
        PWB_CHECK(catalog.is_ok());
        std::string parent_version;
        for (const auto& version : catalog.value().versions) {
            if (version.asset_id.str() == fixture.asset_id &&
                !version.trashed) {
                parent_version = version.id.str();
                break;
            }
        }
        PWB_CHECK(!parent_version.empty());
        auto session = pwb::data::WritableSession::open(fixture.project_file);
        PWB_CHECK(session.is_ok());
        PWB_CHECK(session.value().repository().open_read_write().is_ok());
        pwb::catalog::DataAsset asset;
        asset.id = pwb::domain::AssetId("asset_child_" + stamp());
        asset.name = "child";
        asset.type = "well_log";
        asset.created_at = "2026-09-24T00:00:00Z";
        pwb::catalog::DataVersion version;
        version.id = pwb::domain::VersionId("vers_child_" + stamp());
        version.asset_id = asset.id;
        version.version_number = 1;
        version.stage = pwb::domain::DataStage::Derived;
        version.path = "derived/x/y.csv";
        version.format = "csv";
        version.created_at = asset.created_at;
        version.parent_version_ids = {pwb::domain::VersionId(parent_version)};
        PWB_CHECK(session.value()
                      .repository()
                      .import_raw_transaction(asset, version)
                      .code == pwb::domain::ErrorCode::Ok);
    }

    // 有下游 + 拒绝 → 不动库。
    confirmed = false;
    PWB_CHECK(!pwb::app::data_governance::run_trash_flow(install, {row},
                                                         "UI 测试"));
    PWB_CHECK(gov::asset_is_live(fixture.project_file, fixture.asset_id));

    // 有下游 + 放行 → 软删成功 + 刷新发生。
    confirmed = true;
    PWB_CHECK(pwb::app::data_governance::run_trash_flow(install, {row},
                                                        "UI 测试"));
    PWB_CHECK(!gov::asset_is_live(fixture.project_file, fixture.asset_id));
    PWB_CHECK(refresh_count >= 1);

    // 回收站对话框列出并可恢复。
    {
        pwb::app::data_governance::TrashDialog dialog(fixture.project_file,
                                                      {});
        PWB_CHECK(dialog.table_rows() >= 1);
        dialog.select_row_for(fixture.asset_id);
        PWB_CHECK(dialog.restore_selected());
        PWB_CHECK(gov::asset_is_live(fixture.project_file, fixture.asset_id));
    }

    std::error_code cleanup;
    fs::remove_all(fixture.dir, cleanup);
}

// ---------------------------------------------------------------------------
// 6. bus republish_current 写后刷新语义
// ---------------------------------------------------------------------------
void test_bus_republish_current() {
    pwb::ui_pages_data::qt::AssetSelectionBus bus;
    std::vector<pwb::ui_pages_data::AssetRow> rows;
    rows.push_back(row_of("a1", "One", {}, ""));
    bus.set_assets(rows, QStringLiteral("p1"));
    bus.set_current_asset(rows[0]);

    int current_changes = 0;
    std::string last_tags;
    QObject::connect(
        &bus,
        &pwb::ui_pages_data::qt::AssetSelectionBus::current_asset_changed,
        &bus, [&](const std::optional<pwb::ui_pages_data::AssetRow>& asset) {
            ++current_changes;
            if (asset.has_value() && !asset->view.tags.empty()) {
                last_tags = asset->view.tags.front();
            }
        });
    // set_assets（current 仍在）不重发。
    rows[0].view.tags = {"qc"};
    bus.set_assets(rows, QStringLiteral("p1"));
    PWB_CHECK(current_changes == 0);
    // republish 重发，且携带写后的新字段。
    bus.republish_current();
    PWB_CHECK(current_changes == 1);
    PWB_CHECK(last_tags == "qc");
}

// ---------------------------------------------------------------------------
// 7. DataLineagePanel 第三页签（影响分析）
// ---------------------------------------------------------------------------
void test_lineage_panel_impact_tab() {
    pwb::app::DataLineagePanel panel;
    PWB_CHECK(panel.tabs()->count() == 3);
    PWB_CHECK(panel.tabs()->tabText(2) == QStringLiteral("影响分析"));

    pwb::ui_pages_data::qt::AssetSelectionBus bus;
    std::vector<pwb::ui_pages_data::AssetRow> rows;
    rows.push_back(row_of("a1", "One", {}, ""));
    bus.set_assets(rows, QStringLiteral("p1"));
    bus.set_current_asset(rows[0]);
    panel.bind_selection_bus(&bus);
    // 无 context → 诚实降级文案，不是空白或崩溃。
    PWB_CHECK(panel.impact_list()->count() >= 1);
}

int main(int argc, char** argv) {
    QApplication app(argc, argv);

    test_rows_carry_governance_fields();
    test_workspace_filter_semantics();
    test_link_and_role_dialogs();
    test_tags_dialog();
    test_trash_flow_and_dialog();
    test_bus_republish_current();
    test_lineage_panel_impact_tab();

    return ::pwb::test::report("platform.data_governance");
}
