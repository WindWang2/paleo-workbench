// asset_view_guard_test — #1382/#1383 regressions: catalog overview
// dangling asset pointer, missing variant alternative, null shared_ptr
// dereference. The repro cases must fail on the pre-fix code and pass after
// ownership is made explicit (see docs/development/cpp-viz-e/scope-ledger.md).
#include <pwb/ui_data_core/asset_view.hpp>
#include <pwb/ui_data_core/filter_index.hpp>

#include <cstring>
#include <cstdio>
#include <memory>
#include <new>
#include <string>
#include <vector>

using namespace pwb::ui_data_core;
namespace domain = pwb::domain;
namespace catalog = pwb::catalog;

static int checks = 0;
static int failures = 0;

#define CHECK(cond)                                                        \
    do {                                                                   \
        ++checks;                                                          \
        if (!(cond)) {                                                     \
            ++failures;                                                    \
            std::printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);    \
        }                                                                  \
    } while (0)

// ---------------------------------------------------------------------------
// Fake read-side service: list_assets returns BY VALUE exactly like the real
// seam (virtual std::vector<catalog::DataAsset> list_assets(bool)) — that is
// the lifetime contract #1382 trips over.
// ---------------------------------------------------------------------------
class FakeCatalogService : public CatalogReadService {
public:
    catalog::CatalogDocument doc_;
    std::filesystem::path root_ = "/tmp/pwb-viz-e-fake-root";

    const catalog::CatalogDocument& document() const override { return doc_; }
    const catalog::DataAsset* get_asset(const std::string& asset_id) override {
        return doc_.find_asset(domain::AssetId(asset_id));
    }
    std::vector<catalog::DataVersion> list_versions(
        const std::string& asset_id) override {
        std::vector<catalog::DataVersion> out;
        for (const auto& v : doc_.versions) {
            if (v.asset_id.str() == asset_id) out.push_back(v);
        }
        return out;
    }
    std::vector<catalog::DataAsset> list_assets(bool include_trashed) override {
        std::vector<catalog::DataAsset> out;
        for (const auto& a : doc_.assets) {
            if (include_trashed || !a.trashed) out.push_back(a);
        }
        return out;
    }
    std::filesystem::path resolve_path(
        const catalog::DataVersion& version) override {
        return root_ / version.path;
    }
    std::optional<LineageResult> get_lineage(
        const std::string& /*version_id*/) override {
        return std::nullopt;
    }
    std::unordered_map<std::string, domain::Json> lineage_summaries() override {
        return {};
    }
};

static void populate(FakeCatalogService& service, int asset_count) {
    for (int i = 0; i < asset_count; ++i) {
        catalog::DataAsset asset;
        asset.id = domain::AssetId("ast_" + std::to_string(i));
        asset.name = "asset-" + std::to_string(i) + "-name";
        asset.type = "well_log";
        asset.metadata = domain::Json::object();
        asset.metadata["format"] = "las";
        asset.metadata["source"] = "catalog";
        service.doc_.assets.push_back(asset);

        catalog::DataVersion version;
        version.id = domain::VersionId("ver_" + std::to_string(i));
        version.asset_id = asset.id;
        version.version_number = 1;
        version.stage = domain::DataStage::Raw;
        version.managed = true;
        version.path = "raw/asset_" + std::to_string(i) + "/payload.las";
        version.format = "las";
        version.size_bytes = 1024 + i;
        version.sha256 = "deadbeef" + std::to_string(i);
        version.created_at = "2026-09-19T00:00:0" + std::to_string(i % 10) + "Z";
        service.doc_.versions.push_back(version);
        service.doc_.assets.back().current_version_id = version.id;
    }
}

// Deterministic post-free detection for the by-value seam: same-size
// reallocation reclaims the just-freed vector chunk (glibc tcache/unsorted
// LIFO), then we scrub it. A dangling `overview.asset` reads the scrubbed
// bytes; an owning copy is immune. Under ASAN the same sequence reports
// heap-use-after-free directly, so both build modes catch the bug.
static void scrub_just_freed(std::size_t bytes) {
    void* p = ::operator new(bytes, std::nothrow);
    if (p != nullptr) {
        std::memset(p, 0x7f, bytes);
        ::operator delete(p);
    }
}

int main() {
    // --- #1382: overview.asset outlives the by-value list_assets copy ----
    {
        std::unordered_map<std::string, CatalogRowOverview> overviews;
        std::size_t vector_bytes = 0;
        {
            FakeCatalogService service;
            populate(service, 256);
            vector_bytes =
                service.doc_.assets.size() * sizeof(catalog::DataAsset);
            overviews = compute_catalog_row_overview(service);
            // service (and its document) die here — overviews must stand
            // alone; #1382's pointers died even earlier, at function return.
        }
        CHECK(overviews.size() == 256);
        scrub_just_freed(vector_bytes);
        for (int i : {0, 42, 128, 255}) {
            const std::string key = "ast_" + std::to_string(i);
            const auto it = overviews.find(key);
            CHECK(it != overviews.end());
            if (it == overviews.end()) continue;
            const CatalogRowOverview& overview = it->second;
            CHECK(overview.asset != nullptr);
            if (overview.asset == nullptr) continue;
            const std::string expected = "asset-" + std::to_string(i) + "-name";
            CHECK(overview.asset->name == expected);
            CHECK(overview.asset->metadata.is_object());
            CHECK(overview.asset->metadata.value("format", "") == "las");
        }
        // apply_catalog_overview consumes overview.asset->metadata after the
        // pass returned (#1382 consumer #1).
        {
            AssetView view;
            view.id = "ast_7";
            apply_catalog_overview(view, overviews.at("ast_7"));
            CHECK(view.catalog_metadata.is_object());
            CHECK(view.catalog_metadata.value("format", "") == "las");
        }
        // asset_view_from_catalog_overview dereferences overview.asset
        // (#1382 consumer #2) and must keep working after the service died.
        {
            const AssetView view =
                asset_view_from_catalog_overview(overviews.at("ast_9"), nullptr);
            CHECK(view.id == "ast_9");
            CHECK(view.name == "asset-9-name");
            CHECK(view.type == "well_log");
            CHECK(view.format == "las");
            CHECK(view.source == "catalog");
            CHECK(view.path == "/tmp/pwb-viz-e-fake-root/raw/asset_9/payload.las");
        }
    }

    // --- #1382 lifecycle: long-lived enricher over destroyed service -----
    {
        std::unordered_map<std::string, CatalogRowOverview> overviews;
        {
            FakeCatalogService service;
            populate(service, 8);
            overviews = compute_catalog_row_overview(service);
        }
        scrub_just_freed(8 * sizeof(catalog::DataAsset));
        CatalogEnricher enricher(overviews);
        catalog::DataAsset doc_asset;
        doc_asset.id = domain::AssetId(std::string("ast_3"));
        doc_asset.name = "asset-3-name";
        doc_asset.type = "well_log";
        AssetView view = asset_view_from_object(make_asset_handle(&doc_asset),
                                                nullptr, nullptr);
        AssetView enriched = enricher.enrich(std::move(view));
        CHECK(enriched.catalog_metadata.is_object());
        CHECK(enriched.catalog_metadata.value("format", "") == "las");
        CHECK(enriched.checksum.has_value() &&
              *enriched.checksum == "deadbeef3");
    }

    // --- #1383: shared_ptr<const DataAsset> alternative must not throw ---
    {
        auto owned = std::make_shared<const catalog::DataAsset>();
        // const access to a make_shared<const> object: build via copy.
        catalog::DataAsset src;
        src.id = domain::AssetId(std::string("ast_cat"));
        src.name = "catalog-row";
        src.type = "surface";
        src.metadata = domain::Json::object();
        src.metadata["format"] = "grd";
        owned = std::make_shared<const catalog::DataAsset>(src);

        AssetHandle handle =
            std::make_shared<AssetObjectData>(std::shared_ptr<const catalog::DataAsset>(owned));
        bool threw = false;
        AssetView view;
        try {
            view = asset_view_from_object(handle, nullptr, nullptr);
        } catch (const std::bad_variant_access&) {
            threw = true;
        } catch (...) {
            threw = true;
        }
        CHECK(!threw);
        if (!threw) {
            // Duck-typing parity with Python getattr on a catalog document
            // row: id/name/type are read; absent attrs take the defaults.
            CHECK(view.id == "ast_cat");
            CHECK(view.name == "catalog-row");
            CHECK(view.type == "surface");
            CHECK(view.format == "unknown");  // DataAsset has no format attr
            CHECK(view.source == "local");
            CHECK(view.managed);
        }
    }

    // --- #1383: null shared_ptr<AssetView> must not dereference ----------
    {
        AssetHandle handle =
            std::make_shared<AssetObjectData>(std::shared_ptr<AssetView>());
        AssetView view = asset_view_from_object(handle, nullptr, nullptr);
        CHECK(view.id.empty());
        CHECK(view.name.empty());
    }

    // --- #1383: null shared_ptr<const DataAsset> must be safe ------------
    {
        AssetHandle handle = std::make_shared<AssetObjectData>(
            std::shared_ptr<const catalog::DataAsset>());
        AssetView view = asset_view_from_object(handle, nullptr, nullptr);
        CHECK(view.id.empty());
    }

    // --- Reachable path: FilterIndex::rebuild over DataAsset handles -----
    // (filter_index.cpp build_view → asset_view_from_object; pre-fix this
    // throws bad_variant_access for catalog rows.)
    {
        FakeCatalogService service;
        populate(service, 4);
        std::vector<AssetHandle> handles;
        // Aliasing handles like make_asset_handle(const DataAsset*) — the
        // service document stays alive across the rebuild here.
        for (const auto& a : service.doc_.assets) {
            handles.push_back(make_asset_handle(&a));
        }
        FilterIndex index;
        bool threw = false;
        try {
            index.rebuild(handles, nullptr);
        } catch (const std::bad_variant_access&) {
            threw = true;
        } catch (...) {
            threw = true;
        }
        CHECK(!threw);
        CHECK(index.last_rebuild_view_builds >= 0);
    }

    std::printf("%s: %d checks, %d failures\n", __func__, checks, failures);
    return failures == 0 ? 0 : 1;
}
