// data.governance_scale — 治理读路径的 10 万级规模烟测（非基准）：
//   * 100k 资产 + 标签关联（直接 SQL 一次事务种子，无载荷字节）；
//   * tags_for_assets / all_tag_names / trashed_assets / delete_impact
//     在该规模下有界完成；
//   * 链接扫描（links_for_asset / asset_ids_for_entity 的 JSON 线性扫）
//     10k → 40k 增长近似线性——抓住意外 O(N²)（嵌套重扫）的回归。
#include "pwb_test.hpp"

// data 框架只有裸 PWB_CHECK；本文件用带消息的本地 shim。
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
#include "pwb/catalog/sqlite.hpp"
#include "pwb/data/entity_identity.hpp"
#include "pwb/data/governance.hpp"
#include "pwb/domain/json.hpp"
#include "pwb/project/document.hpp"
#include "pwb/project/manager.hpp"
#include "pwb/project/paths.hpp"

#include <algorithm>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

namespace {

namespace fs = std::filesystem;
using pwb::domain::Json;
namespace gov = pwb::data::governance;

constexpr int kAssetCount = 100000;

std::string stamp() {
    return std::to_string(
        std::chrono::steady_clock::now().time_since_epoch().count());
}

double seconds_since(std::chrono::steady_clock::time_point start) {
    return std::chrono::duration<double>(
               std::chrono::steady_clock::now() - start)
        .count();
}

struct Scale {
    fs::path root;
    fs::path project_file;

    Scale() {
        root = fs::temp_directory_path() / ("pwb-governance-scale-" +
                                            stamp());
        fs::create_directories(root);
        project_file = root / "scale.paleo.json";
        auto document = pwb::project::ProjectDocument::create_new("scale",
                                                                  "");
        pwb::project::ProjectManager manager(project_file);
        PWB_CHECK(manager.save(document).is_ok());
    }

    ~Scale() {
        std::error_code ec;
        fs::remove_all(root, ec);
    }
};

// 100k 资产 + 版本 + 3 个标签词汇 + 每资产 2 条关联（一次事务）。
// tags/asset_tags 用原生列名直接种（TagStore 读取走同一 catalog 文档）。
void seed_catalog(const fs::path& sqlite_path) {
    std::error_code mkdir_ec;
    fs::create_directories(sqlite_path.parent_path(), mkdir_ec);
    auto opened = pwb::catalog::Database::open(
        sqlite_path, pwb::catalog::SqliteOpenMode::Create);
    PWB_CHECK(opened.is_ok());
    PWB_CHECK(opened.value().ensure_schema().code ==
              pwb::domain::ErrorCode::Ok);
    pwb::catalog::Database& db = opened.value();
    db.execute("BEGIN IMMEDIATE");
    {
        pwb::catalog::Statement asset = db.prepare(
            "INSERT INTO assets (id, name, name_search, type, metadata,"
            " created_at, updated_at, current_version_id, trashed)"
            " VALUES (?, ?, ?, 'well_log', '{}', '2026-01-01T00:00:00',"
            " '2026-01-01T00:00:00', ?, 0)");
        pwb::catalog::Statement version = db.prepare(
            "INSERT INTO versions (id, asset_id, version_number, stage,"
            " managed, path, format, created_at) VALUES "
            "(?, ?, 1, 'raw', 1, '', 'las', '2026-01-01T00:00:00')");
        for (int i = 0; i < kAssetCount; ++i) {
            const std::string asset_id =
                "asset_g" + std::to_string(1000000 + i);
            const std::string version_id =
                "ver_g" + std::to_string(1000000 + i);
            const std::string name = "scale asset " + std::to_string(i);
            asset.bind(1, asset_id);
            asset.bind(2, name);
            asset.bind(3, name);
            asset.bind(4, version_id);
            PWB_CHECK(asset.step_done().ok());
            asset.reset();
            version.bind(1, version_id);
            version.bind(2, asset_id);
            PWB_CHECK(version.step_done().ok());
            version.reset();
        }
        // 标签词汇（3 个）+ 每资产 2 条关联；每第 1000 个资产 trashed。
        pwb::catalog::Statement tag = db.prepare(
            "INSERT INTO tags (id, name, display_name, metadata) VALUES "
            "(?, ?, ?, '{}')");
        const char* tag_names[3] = {"qc-pass", "batch-a", "reviewed"};
        for (int t = 0; t < 3; ++t) {
            const std::string id = "tag_" + std::to_string(t);
            tag.bind(1, id);
            tag.bind(2, tag_names[t]);
            tag.bind(3, tag_names[t]);
            PWB_CHECK(tag.step_done().ok());
            tag.reset();
        }
        pwb::catalog::Statement asset_tag = db.prepare(
            "INSERT OR IGNORE INTO asset_tags (asset_id, tag_id) VALUES "
            "(?, ?)");
        pwb::catalog::Statement trash_asset = db.prepare(
            "UPDATE assets SET trashed = 1, trashed_at = "
            "'2026-01-02T00:00:00' WHERE id = ?");
        for (int i = 0; i < kAssetCount; ++i) {
            const std::string asset_id =
                "asset_g" + std::to_string(1000000 + i);
            asset_tag.bind(1, asset_id);
            asset_tag.bind(2, "tag_0");
            PWB_CHECK(asset_tag.step_done().ok());
            asset_tag.reset();
            if (i % 2 == 0) {
                asset_tag.bind(1, asset_id);
                asset_tag.bind(2, "tag_1");
                PWB_CHECK(asset_tag.step_done().ok());
                asset_tag.reset();
            }
            if (i % 1000 == 0) {
                trash_asset.bind(1, asset_id);
                PWB_CHECK(trash_asset.step_done().ok());
                trash_asset.reset();
            }
        }
    }
    db.execute(
        "INSERT INTO sync_state (key, value) VALUES ('index_schema_version',"
        " '5') ON CONFLICT(key) DO UPDATE SET value = '5'");
    db.execute("COMMIT");
}

// N 条 well 链接（含目标资产）写进项目 JSON。
void seed_links(const fs::path& project_file, int link_count) {
    pwb::project::ProjectManager manager(project_file);
    auto loaded = manager.load();
    PWB_CHECK(loaded.is_ok());
    Json& root = loaded.value().document.root();
    Json wells = Json::array();
    Json well = Json::object();
    well["id"] = "w-scale";
    well["name"] = "Scale Well";
    wells.push_back(std::move(well));
    root["wells"] = std::move(wells);
    root["entity_asset_links"] = Json::array();
    for (int i = 0; i < link_count; ++i) {
        pwb::data::upsert_entity_asset_link(
            root, "well", "w-scale",
            "asset_g" + std::to_string(1000000 + i), "well_log", i == 0,
            false, "", i);
    }
    PWB_CHECK(manager.save(loaded.value().document).is_ok());
}

}  // namespace

PWB_TEST(governance_reads_bounded_at_100k) {
    Scale scale;
    const fs::path sqlite_path =
        pwb::project::catalog_sqlite_for(scale.project_file);
    seed_catalog(sqlite_path);

    // tags_for_assets：100 个资产的标签查询（对话框典型批量）。
    {
        std::vector<std::string> ids;
        for (int i = 0; i < 100; ++i) {
            ids.push_back("asset_g" + std::to_string(1000000 + i));
        }
        const auto start = std::chrono::steady_clock::now();
        const auto tags = gov::tags_for_assets(scale.project_file, ids);
        const double seconds = seconds_since(start);
        std::cout << "  tags_for_assets(100): " << seconds << "s\n";
        PWB_CHECK(tags.size() == 100);
        PWB_CHECK(!tags.front().tags.empty());
        PWB_CHECK(seconds < 10.0);
    }

    // all_tag_names：词汇表读取。
    {
        const auto start = std::chrono::steady_clock::now();
        const auto names = gov::all_tag_names(scale.project_file);
        const double seconds = seconds_since(start);
        std::cout << "  all_tag_names: " << seconds << "s\n";
        PWB_CHECK(names.size() == 3);
        PWB_CHECK(seconds < 10.0);
    }

    // trashed_assets：回收站列表（100 个 trashed 资产）。
    {
        const auto start = std::chrono::steady_clock::now();
        const auto entries = gov::trashed_assets(scale.project_file);
        const double seconds = seconds_since(start);
        std::cout << "  trashed_assets: " << seconds << "s ("
                  << entries.size() << " entries)\n";
        PWB_CHECK(!entries.empty());
        PWB_CHECK(seconds < 10.0);
    }

    // asset_is_live / delete_impact_facts：点查 + 单资产影响分析有界。
    {
        const auto start = std::chrono::steady_clock::now();
        const bool live =
            gov::asset_is_live(scale.project_file, "asset_g1000000");
        const auto facts = gov::delete_impact_facts(
            scale.project_file, std::nullopt, "asset_g1000000");
        const double seconds = seconds_since(start);
        std::cout << "  asset_is_live+impact: " << seconds
                  << "s (live=" << live << ")\n";
        PWB_CHECK(!live);  // i=0 被 trashed
        PWB_CHECK(facts.ok);
        PWB_CHECK(seconds < 30.0);  // 文档加载一次的有界预算（宽松）
    }
}

PWB_TEST(link_scan_grows_linearly) {
    Scale scale;
    const fs::path sqlite_path =
        pwb::project::catalog_sqlite_for(scale.project_file);
    seed_catalog(sqlite_path);

    // 10k vs 40k 链接扫描：links_for_asset 的 JSON 线性扫 + 项目文档
    // 保存。40k 应约 4x（允许 3x 容差的上限），抓住嵌套扫描回归。
    double small = 0.0;
    double large = 0.0;
    {
        seed_links(scale.project_file, 10000);
        pwb::project::ProjectManager manager(scale.project_file);
        auto loaded = manager.load();
        PWB_CHECK(loaded.is_ok());
        const auto start = std::chrono::steady_clock::now();
        const auto ids = pwb::data::asset_ids_for_entity(
            loaded.value().document.root(), "well", "w-scale");
        small = seconds_since(start);
        PWB_CHECK(ids.size() == 10000);
    }
    {
        seed_links(scale.project_file, 40000);
        pwb::project::ProjectManager manager(scale.project_file);
        auto loaded = manager.load();
        PWB_CHECK(loaded.is_ok());
        const auto start = std::chrono::steady_clock::now();
        const auto ids = pwb::data::asset_ids_for_entity(
            loaded.value().document.root(), "well", "w-scale");
        large = seconds_since(start);
        PWB_CHECK(ids.size() == 40000);
    }
    const double ratio = large / std::max(small, 1e-6);
    std::cout << "  link scan 10k: " << small << "s, 40k: " << large
              << "s, ratio " << ratio << "\n";
    PWB_CHECK_MSG(large < 10.0, "40k link scan is not bounded");
    PWB_CHECK_MSG(ratio < 12.0,
                  "link scan scaling looks super-linear (ratio > 12)");
}
