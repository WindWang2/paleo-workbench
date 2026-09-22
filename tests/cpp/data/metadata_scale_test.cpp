// data.metadata_scale — deterministic perf sanity at the "few hundred
// thousand metadata records" scale (conv-26; the task's 十几万条 target).
// NOT a benchmark: seeds one direct-SQL metadata store (Python
// benchmarks/catalog_scale_v6.py --direct-seed parity — no payload bytes),
// then asserts the SQL read path stays correct and bounded: paged queries,
// keyset deep pages, counts and the document load all complete under
// generous ceilings on this machine class.
#include "pwb_test.hpp"

#include "pwb/catalog/paged_sql.hpp"
#include "pwb/catalog/repository.hpp"
#include "pwb/catalog/sqlite.hpp"
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

constexpr int kAssetCount = 120000;  // 十几万级

struct Scale {
    fs::path root;
    fs::path project_file;

    Scale() {
        root = fs::temp_directory_path() / "pwb_metadata_scale";
        std::error_code ec;
        fs::remove_all(root, ec);
        fs::create_directories(root, ec);
        project_file = root / "scale.paleo.json";
        auto document = pwb::project::ProjectDocument::create_new("scale", "");
        pwb::project::ProjectManager manager(project_file);
        PWB_CHECK(manager.save(document).is_ok());
    }

    ~Scale() {
        std::error_code ec;
        fs::remove_all(root, ec);
    }
};

double seconds_since(std::chrono::steady_clock::time_point start) {
    return std::chrono::duration<double>(
               std::chrono::steady_clock::now() - start)
        .count();
}

}  // namespace

PWB_TEST(sql_read_path_is_bounded_at_scale) {
    Scale scale;
    const fs::path sqlite_path =
        pwb::project::catalog_sqlite_for(scale.project_file);

    // ---- seed (metadata only, one transaction) -----------------------------
    {
        std::error_code mkdir_ec;
        fs::create_directories(sqlite_path.parent_path(), mkdir_ec);
        auto opened = pwb::catalog::Database::open(
            sqlite_path, pwb::catalog::SqliteOpenMode::Create);
        PWB_CHECK(opened.is_ok());
        auto schema_error = opened.value().ensure_schema();
        PWB_CHECK(schema_error.code == pwb::domain::ErrorCode::Ok);
        pwb::catalog::Database& db = opened.value();
        db.execute("BEGIN IMMEDIATE");
        {
            pwb::catalog::Statement asset = db.prepare(
                "INSERT INTO assets (id, name, name_search, type, metadata,"
                " created_at, updated_at, current_version_id) VALUES "
                "(?, ?, ?, ?, '{}', '2026-01-01T00:00:00', "
                "'2026-01-01T00:00:00', ?)");
            pwb::catalog::Statement version = db.prepare(
                "INSERT INTO versions (id, asset_id, version_number, stage,"
                " managed, path, format, size_bytes, sha256, created_at)"
                " VALUES (?, ?, 1, 'raw', 1, '', 'las', ?, ?, "
                "'2026-01-01T00:00:00')");
            for (int i = 0; i < kAssetCount; ++i) {
                const std::string asset_id =
                    "asset_s" + std::to_string(1000000 + i);
                const std::string version_id =
                    "ver_s" + std::to_string(1000000 + i);
                const std::string name = "scale asset " +
                                         std::to_string(i);
                asset.bind(1, asset_id);
                asset.bind(2, name);
                asset.bind(3, name);  // already-lowercase name_search
                asset.bind(4, i % 3 == 0 ? "well_log" : "tabular");
                asset.bind(5, version_id);
                PWB_CHECK(asset.step_done().ok());
                asset.reset();
                version.bind(1, version_id);
                version.bind(2, asset_id);
                version.bind(3, static_cast<std::int64_t>(i));
                version.bind(4, "sha_s" + std::to_string(i));
                PWB_CHECK(version.step_done().ok());
                version.reset();
            }
        }
        db.execute(
            "INSERT INTO sync_state (key, value) VALUES ('index_schema_version',"
            " '5') ON CONFLICT(key) DO UPDATE SET value = '5'");
        db.execute("COMMIT");
    }

    // ---- bounded reads ------------------------------------------------------
    auto opened = pwb::catalog::Database::open(
        sqlite_path, pwb::catalog::SqliteOpenMode::ReadOnly);
    PWB_CHECK(opened.is_ok());

    auto budget = [](double seconds, const char* what, double ceiling) {
        std::cout << "  " << what << ": " << seconds << "s (ceiling "
                  << ceiling << "s)\n";
        PWB_CHECK(seconds < ceiling);
    };

    pwb::catalog::EntityPageQuery first;
    first.limit = 50;
    auto t0 = std::chrono::steady_clock::now();
    const std::vector<Json> page0 =
        pwb::catalog::search_assets_page_sql(opened.value(), first);
    budget(seconds_since(t0), "first page (50)", 5.0);
    PWB_CHECK(page0.size() == 50);
    PWB_CHECK(page0.front()["name"].get<std::string>() == "scale asset 0");

    // Deep offset page.
    pwb::catalog::EntityPageQuery deep;
    deep.limit = 50;
    deep.offset = kAssetCount - 60;
    auto t1 = std::chrono::steady_clock::now();
    const std::vector<Json> deep_page =
        pwb::catalog::search_assets_page_sql(opened.value(), deep);
    budget(seconds_since(t1), "deep offset page", 5.0);
    PWB_CHECK(deep_page.size() == 50);

    // Keyset walk to the very end — O(log n) per page, no offset scan.
    pwb::catalog::EntityPageQuery cursor;
    cursor.limit = 100;
    int pages = 0;
    std::int64_t walked = 0;
    auto t2 = std::chrono::steady_clock::now();
    while (true) {
        const std::vector<Json> rows =
            pwb::catalog::search_assets_page_sql(opened.value(), cursor);
        if (rows.empty()) break;
        walked += static_cast<std::int64_t>(rows.size());
        cursor.after = {rows.back()["name"].get<std::string>(),
                        rows.back()["id"].get<std::string>()};
        PWB_CHECK(++pages < kAssetCount / 90);
    }
    budget(seconds_since(t2), "keyset full walk", 60.0);
    PWB_CHECK(walked == kAssetCount);

    // Counts with predicates.
    pwb::catalog::EntityPageQuery count_all;
    auto t3 = std::chrono::steady_clock::now();
    PWB_CHECK(pwb::catalog::count_assets_sql(opened.value(), count_all) ==
              kAssetCount);
    budget(seconds_since(t3), "count all", 5.0);

    pwb::catalog::EntityPageQuery count_text;
    count_text.text = "scale asset 9999";
    PWB_CHECK(pwb::catalog::count_assets_sql(opened.value(), count_text) ==
              11);  // 9999, 19999, …, 109999 — prefix substring semantics

    pwb::catalog::EntityPageQuery count_type;
    count_type.type = "well_log";
    PWB_CHECK(pwb::catalog::count_assets_sql(opened.value(), count_type) ==
              kAssetCount / 3);

    pwb::catalog::EntityPageQuery count_stage;
    count_stage.stage = "raw";
    PWB_CHECK(pwb::catalog::count_assets_sql(opened.value(), count_stage) ==
              kAssetCount);

    // Text-filtered page stays correct at depth: names whose decimal part
    // starts with "42" — 42, 420-429, 4200-4299, 42000-42999 = 1111; the
    // page itself is capped by limit, the count is not.
    pwb::catalog::EntityPageQuery text_page;
    text_page.text = "scale asset 42";
    text_page.limit = 500;
    const std::vector<Json> hits =
        pwb::catalog::search_assets_page_sql(opened.value(), text_page);
    PWB_CHECK(hits.size() == 500);
    PWB_CHECK(pwb::catalog::count_assets_sql(opened.value(), text_page) ==
              1111);

    // ---- document load sanity (full open stays possible) -------------------
    pwb::catalog::CatalogRepository repository(sqlite_path);
    auto t4 = std::chrono::steady_clock::now();
    auto document = repository.open_read_only();
    budget(seconds_since(t4), "full document load", 120.0);
    PWB_CHECK(document.is_ok());
    PWB_CHECK(document.value().assets.size() ==
              static_cast<std::size_t>(kAssetCount));
}
