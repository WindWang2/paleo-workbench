// data.governance_ops — ws0 数据治理闭环 headless 核心：link/role 写入
// 与重开一致性、tags 增删/正规化/重开、trash 保留关联 + 恢复、impact
// 直接下游计数、负路径（未知实体/空角色/未知 id/角色冲突）。
#include "pwb_test.hpp"

// data 框架只有裸 PWB_CHECK；本文件用带消息的本地 shim（失败先打印
// 上下文再走统一计数）。
#define PWB_CHECK_MSG(condition, message)                             \
    do {                                                              \
        if (!(condition)) {                                           \
            std::cout << "  CHECK failed (" << message << "): "       \
                      << #condition << " @" << __FILE__ << ":"        \
                      << __LINE__ << "\n";                            \
        }                                                             \
        PWB_CHECK(condition);                                         \
    } while (false)

#include "pwb/catalog/models.hpp"
#include "pwb/catalog/repository.hpp"
#include "pwb/data/governance.hpp"
#include "pwb/data/ingest_exec.hpp"
#include "pwb/data/ingest_plan.hpp"
#include "pwb/data/session.hpp"
#include "pwb/domain/json.hpp"
#include "pwb/project/document.hpp"
#include "pwb/project/manager.hpp"
#include "pwb/project/paths.hpp"

#include <chrono>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

namespace {

namespace fs = std::filesystem;
using pwb::domain::Json;
namespace gov = pwb::data::governance;

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

struct Fixture {
    fs::path dir;
    fs::path project_file;
    std::string raw_asset_id;
    std::string raw_version_id;
};

// 临时工程：well w1 + 一个经真实 ingest plan 落库的 RAW 资产。
Fixture make_fixture(const std::string& tag) {
    Fixture fixture;
    fixture.dir = fs::temp_directory_path() / ("pwb-governance-" + tag + "-" +
                                               stamp());
    fs::create_directories(fixture.dir / "Well-1");
    write_las(fixture.dir / "Well-1" / "log1.las");

    auto document = pwb::project::ProjectDocument::create_new(
        "governance-test", "test-region");
    Json well = Json::object();
    well["id"] = "w1";
    well["name"] = "Well-1";
    well["uwi"] = "1001";
    well["coordinate_status"] = "ok";
    well["spatial_scope"] = "workarea";
    document.root()["wells"] = Json::array({well});
    fixture.project_file = fixture.dir / "governance.paleo.json";
    pwb::project::ProjectManager manager(fixture.project_file);
    const auto save = manager.save(document);
    PWB_CHECK(save.is_ok());

    // 真实两阶段导入（build → execute on WritableSession → save）。
    auto loaded = manager.load();
    PWB_CHECK(loaded.is_ok());
    pwb::data::IngestPlanOptions options;
    auto plan = pwb::data::build_ingest_plan(
        fixture.dir / "Well-1", loaded.value().document, options);
    PWB_CHECK(!plan.items.empty());
    for (auto& item : plan.items) item.decision = "accept";
    auto session = pwb::data::WritableSession::open(fixture.project_file);
    PWB_CHECK(session.is_ok());
    const auto report =
        pwb::data::execute_ingest_plan(plan, session.value());
    PWB_CHECK(report.imported_version_ids.size() == 1);
    const auto saved = session.value().manager().save(
        session.value().document());
    PWB_CHECK(saved.is_ok());
    fixture.raw_version_id = report.imported_version_ids.front();

    // 资产 id 从目录读回（链接键是 asset_id，不是 version_id）。
    pwb::catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(fixture.project_file));
    auto catalog = repository.open_read_only();
    PWB_CHECK(catalog.is_ok());
    for (const auto& version : catalog.value().versions) {
        if (version.id.str() == fixture.raw_version_id) {
            fixture.raw_asset_id = version.asset_id.str();
        }
    }
    PWB_CHECK(!fixture.raw_asset_id.empty());
    return fixture;
}

// 派生子资产（新 asset + parent_version_ids → 真实 lineage 边），给
// impact/lineage 查询一个下游。
std::pair<std::string, std::string> add_derived_child(
    const Fixture& fixture, const std::string& parent_version_id) {
    auto session = pwb::data::WritableSession::open(fixture.project_file);
    PWB_CHECK(session.is_ok());
    // 先打开读写句柄（ingest_exec 同款顺序——事务族在 open 之后才可用）。
    auto opened_doc = session.value().repository().open_read_write();
    PWB_CHECK(opened_doc.is_ok());
    pwb::catalog::DataAsset asset;
    asset.id = pwb::domain::AssetId("asset_derived_" + stamp());
    asset.name = "derived-child";
    asset.type = "well_log";
    asset.created_at = "2026-09-24T00:00:00Z";
    asset.updated_at = asset.created_at;
    pwb::catalog::DataVersion version;
    version.id = pwb::domain::VersionId("vers_derived_" + stamp());
    version.asset_id = asset.id;
    version.version_number = 1;
    version.stage = pwb::domain::DataStage::Derived;
    version.path = "derived/" + asset.id.str() + "/" + version.id.str() +
                   "/derived.csv";
    version.format = "csv";
    version.created_at = asset.created_at;
    version.parent_version_ids = {
        pwb::domain::VersionId(parent_version_id)};
    const auto error =
        session.value().repository().import_raw_transaction(asset, version);
    PWB_CHECK_MSG(error.code == pwb::domain::ErrorCode::Ok,
                  ("derived transaction failed: " + error.message).c_str());
    return {asset.id.str(), version.id.str()};
}

PWB_TEST(link_unlink_and_role_roundtrip) {
    const auto fixture = make_fixture("link");

    // 关联到井（主数据），落库后重开读取仍然在。
    const auto linked = gov::link_asset(fixture.project_file, "well", "w1",
                                        fixture.raw_asset_id, "well_log",
                                        true, "手动关联");
    PWB_CHECK_MSG(linked.ok, ("link failed: " + linked.error).c_str());
    {
        auto links = gov::links_for_asset(fixture.project_file,
                                          fixture.raw_asset_id);
        PWB_CHECK(links.size() == 1);
        PWB_CHECK(links[0].entity_id == "w1");
        PWB_CHECK(links[0].role == "well_log");
        PWB_CHECK(links[0].is_primary);
    }

    // 幂等：同一 upsert 不产生第二条。
    const auto again = gov::link_asset(fixture.project_file, "well", "w1",
                                       fixture.raw_asset_id, "well_log",
                                       true, "");
    PWB_CHECK(again.ok);
    PWB_CHECK(gov::links_for_asset(fixture.project_file,
                                   fixture.raw_asset_id)
                  .size() == 1);

    // 角色编辑：保留主数据位。
    const auto edited = gov::set_asset_link_role(
        fixture.project_file, "well", "w1", fixture.raw_asset_id,
        "well_log", "interpretation");
    PWB_CHECK_MSG(edited.ok, ("role edit failed: " + edited.error).c_str());
    {
        auto links = gov::links_for_asset(fixture.project_file,
                                          fixture.raw_asset_id);
        PWB_CHECK(links.size() == 1);
        PWB_CHECK(links[0].role == "interpretation");
        PWB_CHECK(links[0].is_primary);  // identity fields preserved
    }

    // 角色冲突：先补一条 well_log 链接，再把 interpretation 改回
    // well_log 必须拒绝（upsert-key 重复，绝不静默合并）。
    const auto second_link = gov::link_asset(
        fixture.project_file, "well", "w1", fixture.raw_asset_id,
        "well_log", false, "");
    PWB_CHECK(second_link.ok);
    const auto conflict = gov::set_asset_link_role(
        fixture.project_file, "well", "w1", fixture.raw_asset_id,
        "interpretation", "well_log");
    PWB_CHECK(!conflict.ok);

    // 单链接删除（按角色精确删）。
    const auto unlinked = gov::unlink_asset(fixture.project_file, "well",
                                            "w1", fixture.raw_asset_id,
                                            "well_log");
    PWB_CHECK_MSG(unlinked.ok,
                  ("unlink failed: " + unlinked.error).c_str());
    PWB_CHECK(gov::links_for_asset(fixture.project_file,
                                   fixture.raw_asset_id)
                  .size() == 1);  // interpretation 仍在

    // 重开一致性：磁盘 JSON 是唯一权威，读的是新解析。
    {
        pwb::project::ProjectManager manager(fixture.project_file);
        auto loaded = manager.load();
        PWB_CHECK(loaded.is_ok());
        const auto links = pwb::data::links_for_asset(
            loaded.value().document.root(), fixture.raw_asset_id);
        PWB_CHECK(links.size() == 1);
        PWB_CHECK(links[0].role == "interpretation");
    }

    std::error_code cleanup;
    fs::remove_all(fixture.dir, cleanup);
}

PWB_TEST(link_validation_negatives) {
    const auto fixture = make_fixture("neg");

    // 未知井拒绝。
    const auto unknown_well =
        gov::link_asset(fixture.project_file, "well", "no-such-well",
                        fixture.raw_asset_id, "well_log", false, "");
    PWB_CHECK(!unknown_well.ok);
    // 空角色拒绝。
    const auto blank_role = gov::link_asset(fixture.project_file, "well",
                                            "w1", fixture.raw_asset_id,
                                            "   ", false, "");
    PWB_CHECK(!blank_role.ok);
    // 未知资产拒绝。
    const auto unknown_asset = gov::link_asset(
        fixture.project_file, "well", "w1", "asset-nobody", "well_log",
        false, "");
    PWB_CHECK(!unknown_asset.ok);
    // 未知实体类型拒绝。
    const auto bad_type = gov::link_asset(fixture.project_file, "ufo",
                                          "w1", fixture.raw_asset_id,
                                          "well_log", false, "");
    PWB_CHECK(!bad_type.ok);
    // 解除不存在的链接拒绝。
    const auto missing = gov::unlink_asset(fixture.project_file, "well",
                                           "w1", fixture.raw_asset_id,
                                           "tops");
    PWB_CHECK(!missing.ok);

    std::error_code cleanup;
    fs::remove_all(fixture.dir, cleanup);
}

PWB_TEST(tags_add_remove_and_reopen) {
    const auto fixture = make_fixture("tags");

    // 添加（多标签一次写入）+ 正规化（大小写折叠/空白合并）。
    const auto added = gov::add_tags(
        fixture.project_file, {fixture.raw_asset_id},
        {"  QC-通过  ", "final", "final"});
    PWB_CHECK_MSG(added.ok, ("add tags failed: " + added.error).c_str());
    {
        const auto tags = gov::tags_for_assets(fixture.project_file,
                                               {fixture.raw_asset_id});
        PWB_CHECK(tags.size() == 1);
        PWB_CHECK(tags[0].tags.size() == 2);  // final 去重
        bool folded = false;
        bool final_kept = false;
        for (const auto& tag : tags[0].tags) {
            // 返回 display 名（原样大小写、空白折叠）；正规化键在库里
            // 去重（"final"×2 → 一条）。
            folded = folded || tag == "QC-通过";
            final_kept = final_kept || tag == "final";
        }
        PWB_CHECK(folded);
        PWB_CHECK(final_kept);
    }

    // 空标签名拒绝。
    const auto blank = gov::add_tags(fixture.project_file,
                                     {fixture.raw_asset_id}, {"  "});
    PWB_CHECK(!blank.ok);

    // 移除 + 重开一致。
    const auto removed = gov::remove_tags(fixture.project_file,
                                          {fixture.raw_asset_id}, "final");
    PWB_CHECK_MSG(removed.ok,
                  ("remove tags failed: " + removed.error).c_str());
    {
        pwb::catalog::CatalogRepository repository(
            pwb::project::catalog_sqlite_for(fixture.project_file));
        auto catalog = repository.open_read_only();
        PWB_CHECK(catalog.is_ok());
        std::size_t tag_count = 0;
        for (const auto& [asset_id, tag_id] :
             catalog.value().asset_tags) {
            if (asset_id == fixture.raw_asset_id) ++tag_count;
        }
        PWB_CHECK(tag_count == 1);  // 只剩 qc-通过
        bool vocabulary = false;
        for (const auto& tag : catalog.value().tags) {
            vocabulary = vocabulary || tag.name == "qc-通过";
        }
        PWB_CHECK(vocabulary);
    }

    // all_tag_names 覆盖词汇表读取。
    const auto names = gov::all_tag_names(fixture.project_file);
    PWB_CHECK(names.size() >= 1);

    std::error_code cleanup;
    fs::remove_all(fixture.dir, cleanup);
}

PWB_TEST(trash_preserves_links_and_restore) {
    const auto fixture = make_fixture("trash");
    PWB_CHECK(gov::link_asset(fixture.project_file, "well", "w1",
                              fixture.raw_asset_id, "well_log", true, "")
                  .ok);

    // 软删：资产进回收站，链接保留（历史可解释）。
    const auto trashed = gov::trash_assets(fixture.project_file,
                                           {fixture.raw_asset_id}, "测试移除");
    PWB_CHECK_MSG(trashed.ok, ("trash failed: " + trashed.error).c_str());
    {
        const auto entries = gov::trashed_assets(fixture.project_file);
        PWB_CHECK(entries.size() == 1);
        PWB_CHECK(entries[0].asset_id == fixture.raw_asset_id);
        PWB_CHECK(entries[0].reason == "测试移除");
        PWB_CHECK(entries[0].version_count >= 1);
        // links 不因软删消失。
        PWB_CHECK(gov::links_for_asset(fixture.project_file,
                                       fixture.raw_asset_id)
                      .size() == 1);
        // trashed 资产不可再关联。
        const auto rejected = gov::link_asset(
            fixture.project_file, "well", "w1", fixture.raw_asset_id,
            "tops", false, "");
        PWB_CHECK(!rejected.ok);
    }

    // 恢复：资产回 live，链接原样可用。
    const auto restored = gov::restore_assets(fixture.project_file,
                                              {fixture.raw_asset_id});
    PWB_CHECK_MSG(restored.ok,
                  ("restore failed: " + restored.error).c_str());
    PWB_CHECK(gov::asset_is_live(fixture.project_file,
                                 fixture.raw_asset_id));
    PWB_CHECK(gov::links_for_asset(fixture.project_file,
                                   fixture.raw_asset_id)
                  .size() == 1);

    std::error_code cleanup;
    fs::remove_all(fixture.dir, cleanup);
}

PWB_TEST(trash_unknown_ids_refused) {
    const auto fixture = make_fixture("trash-unknown");
    const auto trashed =
        gov::trash_assets(fixture.project_file, {"asset-nobody"}, "x");
    PWB_CHECK(!trashed.ok);
    const auto restored =
        gov::restore_assets(fixture.project_file, {"asset-nobody"});
    PWB_CHECK(!restored.ok);
    std::error_code cleanup;
    fs::remove_all(fixture.dir, cleanup);
}

PWB_TEST(trash_partial_success_reports_both) {
    const auto fixture = make_fixture("trash-partial");
    // 好 id 在前、坏 id 在后：ok=true（部分落库）且 error 非空——UI 必须
    // 同时看到两者（P1 修复的行为锚点）。
    const auto outcome = gov::trash_assets(
        fixture.project_file, {fixture.raw_asset_id, "asset-nobody"}, "批量");
    PWB_CHECK(outcome.ok);
    PWB_CHECK(!outcome.error.empty());
    PWB_CHECK(!gov::asset_is_live(fixture.project_file,
                                  fixture.raw_asset_id));
    const auto entries = gov::trashed_assets(fixture.project_file);
    PWB_CHECK(entries.size() == 1);
    std::error_code cleanup;
    fs::remove_all(fixture.dir, cleanup);
}

PWB_TEST(role_edit_demotes_sibling_primaries) {
    const auto fixture = make_fixture("role-demote");
    // 第二个资产（直接事务落库），构造双资产组间语义。
    auto session = pwb::data::WritableSession::open(fixture.project_file);
    PWB_CHECK(session.is_ok());
    PWB_CHECK(session.value().repository().open_read_write().is_ok());
    pwb::catalog::DataAsset asset_b;
    asset_b.id = pwb::domain::AssetId("asset_b_" + stamp());
    asset_b.name = "asset-b";
    asset_b.type = "well_log";
    asset_b.created_at = "2026-09-24T00:00:00Z";
    pwb::catalog::DataVersion version_b;
    version_b.id = pwb::domain::VersionId("vers_b_" + stamp());
    version_b.asset_id = asset_b.id;
    version_b.version_number = 1;
    version_b.path = "raw/b/b.csv";
    version_b.format = "csv";
    version_b.created_at = asset_b.created_at;
    PWB_CHECK(session.value()
                  .repository()
                  .import_raw_transaction(asset_b, version_b)
                  .code == pwb::domain::ErrorCode::Ok);
    const std::string asset_b_id = asset_b.id.str();

    // A（导入资产）qc 主；B tops 主。
    PWB_CHECK(gov::link_asset(fixture.project_file, "well", "w1",
                              fixture.raw_asset_id, "qc", true, "")
                  .ok);
    PWB_CHECK(gov::link_asset(fixture.project_file, "well", "w1", asset_b_id,
                              "tops", true, "")
                  .ok);
    // 同资产同角色重复键由 upsert 吸收；但角色编辑撞已有角色必须拒绝
    //（upsert-key 不变量，绝不静默合并）——A 已有 qc 行，再把 well_log
    // 改到 qc 同理拒绝；这里直接验证 A 无 tops 行时的 NotFound。
    const auto not_found = gov::set_asset_link_role(
        fixture.project_file, "well", "w1", fixture.raw_asset_id, "tops",
        "interpretation");
    PWB_CHECK(!not_found.ok);

    // B: tops(主) → qc：qc 组已有 A 的 primary——B 迁移主位后必须把
    // A 的 qc primary 降级（demote_sibling_primaries），组内只留一个。
    PWB_CHECK(gov::set_asset_link_role(fixture.project_file, "well", "w1",
                                       asset_b_id, "tops", "qc")
                  .ok);
    bool a_qc_primary = false;
    bool b_qc_primary = false;
    for (const auto& link :
         gov::links_for_asset(fixture.project_file, asset_b_id)) {
        if (link.role == "qc") b_qc_primary = link.is_primary;
    }
    for (const auto& link :
         gov::links_for_asset(fixture.project_file, fixture.raw_asset_id)) {
        if (link.role == "qc") a_qc_primary = link.is_primary;
    }
    PWB_CHECK(b_qc_primary);
    PWB_CHECK(!a_qc_primary);  // 被降级
    std::error_code cleanup;
    fs::remove_all(fixture.dir, cleanup);
}

PWB_TEST(unlink_last_link_empties) {
    const auto fixture = make_fixture("unlink-last");
    // 导入已建一条 well_log 链接——逐条解除直到清空，重开读取一致。
    PWB_CHECK(gov::unlink_asset(fixture.project_file, "well", "w1",
                                fixture.raw_asset_id, "well_log")
                  .ok);
    {
        pwb::project::ProjectManager manager(fixture.project_file);
        auto loaded = manager.load();
        PWB_CHECK(loaded.is_ok());
        PWB_CHECK(pwb::data::links_for_asset(
                      loaded.value().document.root(), fixture.raw_asset_id)
                      .empty());
    }
    // 再解除一次 → 如实报“链接不存在”。
    const auto again = gov::unlink_asset(fixture.project_file, "well", "w1",
                                         fixture.raw_asset_id, "well_log");
    PWB_CHECK(!again.ok);
    std::error_code cleanup;
    fs::remove_all(fixture.dir, cleanup);
}


PWB_TEST(impact_counts_direct_descendants) {
    const auto fixture = make_fixture("impact");
    const auto [child_asset, child_version] =
        add_derived_child(fixture, fixture.raw_version_id);

    // 有下游：raw 版本的影响分析必须看到派生子版本。
    {
        const auto facts = gov::delete_impact_facts(
            fixture.project_file, fixture.raw_version_id, std::nullopt);
        PWB_CHECK_MSG(facts.ok, ("impact failed: " + facts.error).c_str());
        PWB_CHECK(facts.live_descendants >= 1);
        PWB_CHECK(facts.affected_versions >= 1);
    }
    // 叶子版本：无下游（孩子不是别人的父）。
    {
        const auto facts = gov::delete_impact_facts(
            fixture.project_file, child_version, std::nullopt);
        PWB_CHECK(facts.ok);
        PWB_CHECK(facts.live_descendants == 0);
    }
    (void)child_asset;

    std::error_code cleanup;
    fs::remove_all(fixture.dir, cleanup);
}

PWB_TEST(full_lifecycle_save_close_reopen) {
    const auto fixture = make_fixture("lifecycle");
    const auto [child_asset, child_version] =
        add_derived_child(fixture, fixture.raw_version_id);

    // 一整套治理动作：link + role + tags + trash(child)。
    PWB_CHECK(gov::link_asset(fixture.project_file, "well", "w1",
                              fixture.raw_asset_id, "well_log", true, "")
                  .ok);
    PWB_CHECK(gov::set_asset_link_role(fixture.project_file, "well", "w1",
                                       fixture.raw_asset_id, "well_log",
                                       "qc")
                  .ok);
    PWB_CHECK(gov::add_tags(fixture.project_file,
                            {fixture.raw_asset_id, child_asset},
                            {"批次A"})
                  .ok);
    PWB_CHECK(gov::trash_assets(fixture.project_file, {child_asset},
                                "成果清理")
                  .ok);

    // save→close→reopen：三权威（JSON links / sqlite tags / trash 墓碑）
    // 全部一致。
    {
        pwb::project::ProjectManager manager(fixture.project_file);
        auto loaded = manager.load();
        PWB_CHECK(loaded.is_ok());
        const auto links = pwb::data::links_for_asset(
            loaded.value().document.root(), fixture.raw_asset_id);
        PWB_CHECK(links.size() == 1);
        PWB_CHECK(links[0].role == "qc");

        const auto tags = gov::tags_for_assets(fixture.project_file,
                                                {fixture.raw_asset_id});
        PWB_CHECK(tags.size() == 1);
        PWB_CHECK(!tags[0].tags.empty());

        // trashed child：live=false，但在回收站视图可见；RAW 版本
        // lineage（parent 指向它）仍自洽——ancestors 查询不悬空。
        PWB_CHECK(!gov::asset_is_live(fixture.project_file, child_asset));
        const auto entries = gov::trashed_assets(fixture.project_file);
        bool child_listed = false;
        for (const auto& entry : entries) {
            child_listed = child_listed || entry.asset_id == child_asset;
        }
        PWB_CHECK(child_listed);
        const auto facts = gov::delete_impact_facts(
            fixture.project_file, fixture.raw_version_id, std::nullopt);
        PWB_CHECK(facts.ok);  // 子版本已 trashed → 不再计入 live 下游
        // （child 是 raw 的下游；trashed 后 live_descendants 降为 0。）
        PWB_CHECK(facts.live_descendants == 0);
    }
    (void)child_version;

    std::error_code cleanup;
    fs::remove_all(fixture.dir, cleanup);
}

}  // namespace
