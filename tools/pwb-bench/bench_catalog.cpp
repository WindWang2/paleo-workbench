// pwb-bench — catalog scenarios (cpp-close wave line 14).
//   catalog-load  project-open cost: open_read_only (sqlite index path) and
//                 load_manifest (canonical catalog.json path)
//   catalog-list  100k-asset list cost: document-path search_assets_page
//                 (canonical sort + row materialization) and the SQL paged
//                 path (index-backed, no full materialization)
//
// The fixture is a real v5 catalog store produced by CatalogRepository
// write_all + export_manifest — the same write path the service uses, so
// the measured read side sees production on-disk shape.
#include "bench_common.hpp"

#include <pwb/catalog/entity_view.hpp>
#include <pwb/catalog/paged_sql.hpp>
#include <pwb/catalog/repository.hpp>
#include <pwb/catalog/sqlite.hpp>

#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <string>
#include <system_error>
#include <vector>

namespace pwb::bench {
namespace {

namespace fs = std::filesystem;
using pwb::catalog::CatalogDocument;
using pwb::catalog::CatalogRepository;
using pwb::catalog::DataAsset;
using pwb::catalog::DataVersion;
using pwb::catalog::EntityPageQuery;

CatalogDocument build_fixture(std::size_t assets) {
    CatalogDocument doc;
    doc.catalog_revision = 1;
    doc.assets.reserve(assets);
    doc.versions.reserve(assets);
    for (std::size_t i = 0; i < assets; ++i) {
        char aid[32], vid[32], name[64];
        std::snprintf(aid, sizeof aid, "ast_%012zx", i);
        std::snprintf(vid, sizeof vid, "ver_%012zx", i);
        // Deterministic name mixing so the name sort is a real sort, not a
        // pre-ordered scan: interleave a reversed index into the tail.
        std::snprintf(name, sizeof name, "seis_volume_%06zx_%06zx",
                      i % 4096u, assets - i);

        DataAsset a;
        a.id = pwb::domain::AssetId(std::string(aid));
        a.name = name;
        a.type = (i % 3 == 0) ? "seismic3d" : ((i % 3 == 1) ? "grid" : "log");
        a.current_version_id = pwb::domain::VersionId(std::string(vid));
        a.metadata = Json::object();
        a.metadata["kind"] = "bench";
        a.metadata["survey"] = (i % 7 == 0) ? "north" : "south";
        char ts[32];
        std::snprintf(ts, sizeof ts, "2026-01-%02dT%02d:%02d:%02d",
                      static_cast<int>(i % 28 + 1),
                      static_cast<int>(i % 24),
                      static_cast<int>((i / 24) % 60),
                      static_cast<int>((i / 7) % 60));
        a.created_at = ts;
        a.updated_at = ts;
        doc.assets.push_back(std::move(a));

        DataVersion v;
        v.id = pwb::domain::VersionId(std::string(vid));
        v.asset_id = pwb::domain::AssetId(std::string(aid));
        v.version_number = 1;
        v.managed = true;
        char rel[64];
        std::snprintf(rel, sizeof rel, "bench.artifacts/raw/%012zx.f32", i);
        v.path = rel;
        v.format = "f32";
        v.size_bytes = static_cast<std::int64_t>(4096 + (i % 1024) * 16);
        char sha[80];
        std::snprintf(sha, sizeof sha, "%064zx", i * 2654435761u);
        v.sha256 = std::string(sha);
        v.created_at = ts;
        doc.versions.push_back(std::move(v));
    }
    return doc;
}

// Writes the fixture once; returns the sqlite + manifest paths. Regenerates
// only when the asset count changes (a marker file records the count).
std::pair<fs::path, fs::path> ensure_catalog_fixture(const fs::path& work,
                                                     std::size_t assets) {
    const fs::path db = work / "catalog.sqlite";
    const fs::path manifest = work / "metadata" / "catalog.json";
    const fs::path marker = work / ".fixture-assets";
    {
        std::ifstream in(marker);
        std::size_t recorded = 0;
        if (in >> recorded && recorded == assets && fs::is_regular_file(db)
            && fs::is_regular_file(manifest)) {
            return {db, manifest};
        }
    }
    std::error_code ec;
    fs::remove_all(work / "catalog.sqlite", ec);
    fs::remove_all(work / "metadata", ec);
    fs::create_directories(work / "metadata", ec);
    {
        CatalogRepository repo(db);
        auto opened = repo.open_read_write();
        if (!opened) {
            throw std::runtime_error("catalog fixture: open failed");
        }
        CatalogDocument doc = build_fixture(assets);
        const auto err = repo.write_all(doc);
        if (err.code != pwb::domain::ErrorCode::Ok) {
            throw std::runtime_error("catalog fixture: write_all failed: "
                                     + err.message);
        }
        const auto ex = repo.export_manifest(manifest);
        if (ex.code != pwb::domain::ErrorCode::Ok) {
            throw std::runtime_error("catalog fixture: export_manifest "
                                     "failed: " + ex.message);
        }
        repo.close();
    }
    {
        std::ofstream out(marker, std::ios::trunc);
        out << assets;
    }
    return {db, manifest};
}

Json bench_catalog_load(const Args& args) {
    const std::size_t assets = args.get_size("assets", 100000);
    const int samples = static_cast<int>(args.get_int("samples", 5));
    const fs::path work = args.get("work", "bench-out/catalog");
    std::error_code ec;
    fs::create_directories(work, ec);
    const auto [db, manifest] = ensure_catalog_fixture(work, assets);

    Json out = Json::object();
    out["assets"] = assets;

    // Index path: open_read_only materializes the whole document.
    {
        std::size_t rows = 0;
        const Measured m = measure(samples, [&](int) {
            CatalogRepository repo(db);
            auto doc = repo.open_read_only();
            if (!doc) {
                throw std::runtime_error("catalog-load: open_read_only "
                                         "failed");
            }
            rows = doc.value().assets.size();
            repo.close();
        });
        Json sub = measured_to_json(m);
        sub["rows"] = rows;
        out["load_sqlite"] = std::move(sub);
    }

    // Canonical path: manifest parse + typed rebuild.
    {
        std::size_t rows = 0;
        const Measured m = measure(samples, [&](int) {
            auto loaded = pwb::catalog::load_manifest(manifest);
            if (!loaded) {
                throw std::runtime_error("catalog-load: load_manifest "
                                         "failed");
            }
            rows = loaded.value().document.assets.size();
        });
        Json sub = measured_to_json(m);
        sub["rows"] = rows;
        out["load_manifest"] = std::move(sub);
    }
    return out;
}

Json bench_catalog_list(const Args& args) {
    const std::size_t assets = args.get_size("assets", 100000);
    const int limit = static_cast<int>(args.get_int("limit", 500));
    const int offset = static_cast<int>(args.get_int("offset", 0));
    const int samples = static_cast<int>(args.get_int("samples", 5));
    // The document path materializes every row and does per-asset linear
    // version lookups — O(assets^2). At 100k one call is already tens of
    // seconds, so its sample count is decoupled from the SQL path's
    // (>=5). Default 3 is enough to characterize it; pass
    // --doc-samples N for more.
    const int doc_samples =
        static_cast<int>(args.get_int("doc-samples", 3));
    const fs::path work = args.get("work", "bench-out/catalog");
    const auto [db, manifest] = ensure_catalog_fixture(work, assets);

    // Document loaded once — the paging calls are the measured unit.
    CatalogDocument doc;
    {
        CatalogRepository repo(db);
        auto loaded = repo.open_read_only();
        if (!loaded) {
            throw std::runtime_error("catalog-list: open_read_only failed");
        }
        doc = std::move(loaded.value());
        repo.close();
    }

    Json out = Json::object();
    out["assets"] = assets;
    out["limit"] = limit;
    out["offset"] = offset;

    // Document path (entity_view): full sort + row materialization each
    // call. order_by=name exercises the canonical comparator.
    for (const char* order_by : {"name", "modified"}) {
        std::size_t page_rows = 0;
        std::uint64_t digest = 0;
        const Measured m = measure(doc_samples, [&](int) {
            EntityPageQuery q;
            q.order_by = order_by;
            q.limit = limit;
            q.offset = offset;
            const auto page =
                pwb::catalog::search_assets_page(doc, q);
            page_rows = page.size();
            for (const auto& row : page) {
                const std::string s = row.dump();
                digest ^= fnv1a64(s.data(), s.size());
            }
        });
        Json sub = measured_to_json(m);
        sub["page_rows"] = page_rows;
        sub["digest"] = std::to_string(digest);
        out[std::string("doc_") + order_by] = std::move(sub);
    }

    // SQL path (paged_sql): index-backed page + batched version fetch.
    {
        auto opened =
            pwb::catalog::Database::open(db, pwb::catalog::SqliteOpenMode::ReadOnly);
        if (!opened) {
            throw std::runtime_error("catalog-list: sql open failed");
        }
        pwb::catalog::Database& sql = opened.value();
        std::size_t page_rows = 0;
        std::uint64_t digest = 0;
        const Measured m = measure(samples, [&](int) {
            EntityPageQuery q;
            q.order_by = "name";
            q.limit = limit;
            q.offset = offset;
            const auto page =
                pwb::catalog::search_assets_page_sql(sql, q);
            page_rows = page.size();
            for (const auto& row : page) {
                const std::string s = row.dump();
                digest ^= fnv1a64(s.data(), s.size());
            }
        });
        Json sub = measured_to_json(m);
        sub["page_rows"] = page_rows;
        sub["digest"] = std::to_string(digest);
        out["sql_name"] = std::move(sub);
        sql.close();
    }
    return out;
}

}  // namespace

void register_catalog_scenarios(ScenarioMap& map) {
    map["catalog-load"] = &bench_catalog_load;
    map["catalog-list"] = &bench_catalog_list;
}

}  // namespace pwb::bench
