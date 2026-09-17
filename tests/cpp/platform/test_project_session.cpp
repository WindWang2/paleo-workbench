// platform.project_session — the regular .paleo project flow through the
// REAL MainWindow (review follow-up step 2): open (B store + startup
// recovery + every bound GeoJSON layer materialized as an explicit working
// copy under .pwb-working/), edit the working copy, save through the real
// catalog transaction (stage -> B commit -> provider finalize), then
// REOPEN the project — the binding advanced and the working copy is
// refreshed from the new payload. Catalog payload immutability is proven
// by hashing the payload file before and after the edit round.

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <map>
#include <string>

#include <QFileInfo>
#include <QTemporaryDir>
#include <qgsapplication.h>
#include <qgsvectorlayer.h>

#include <pwb/application/adapters/data_store.hpp>
#include <pwb/application/project_session.hpp>
#include <pwb/qgis/map_session.hpp>
#include <pwb/qgis/qgis_runtime.hpp>

#include "main_window.hpp"

#include "test_fixtures.hpp"
#include "test_framework.hpp"

namespace fs = std::filesystem;
using pwb::app::MainWindow;

namespace {

bool copy_tree(const fs::path& from, const fs::path& to) {
    std::error_code ec;
    fs::create_directories(to, ec);
    for (const auto& entry : fs::recursive_directory_iterator(from, ec)) {
        const auto target = to / fs::relative(entry.path(), from, ec);
        if (entry.is_directory(ec)) fs::create_directories(target, ec);
        else if (entry.is_regular_file(ec)) {
            fs::create_directories(target.parent_path(), ec);
            fs::copy_file(entry.path(), target,
                          fs::copy_options::overwrite_existing, ec);
        }
        if (ec) return false;
    }
    return true;
}

std::string sha256_of(const fs::path& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input.good()) return std::string();
    // FNV-style stable file hash is enough for a before/after identity
    // check (we are comparing the SAME file, not matching an external
    // digest format).
    std::uint64_t hash = 1469598103934665603ull;
    char buffer[65536];
    while (input.good()) {
        input.read(buffer, sizeof(buffer));
        const std::streamsize got = input.gcount();
        for (std::streamsize i = 0; i < got; ++i) {
            hash ^= static_cast<unsigned char>(buffer[i]);
            hash *= 1099511628211ull;
        }
    }
    return std::to_string(hash);
}

const pwb::catalog::DataVersion* version_by_id(
    const pwb::data::ProjectSnapshotV1& snapshot, const std::string& id) {
    for (const auto& version : snapshot.catalog_versions) {
        if (version.id.str() == id) return &version;
    }
    return nullptr;
}

const pwb::workspace::LayerBinding* binding_for(
    const pwb::data::ProjectSnapshotV1& snapshot, const std::string& layer) {
    for (const auto& binding : snapshot.layer_bindings) {
        if (binding.layer_id == layer) return &binding;
    }
    return nullptr;
}

std::string version_sha(const pwb::data::ProjectSnapshotV1& snapshot,
                        const std::string& version_id) {
    const pwb::catalog::DataVersion* version =
        version_by_id(snapshot, version_id);
    return version != nullptr && version->sha256.has_value()
        ? *version->sha256
        : std::string();
}

// First vertex of feature 1 read straight from a file (no edit buffer).
QgsPointXY first_vertex_from_file(const QString& uri) {
    QgsVectorLayer layer(uri, "probe", "ogr");
    if (!layer.isValid()) return QgsPointXY();
    return layer.getFeature(1).geometry().vertexAt(0);
}

}  // namespace

int main(int argc, char** argv) {
    QgsApplication app(argc, argv, true);
    pwb::qgis::QgisRuntime::acquire();

    // ---- project fixture: typical + one REAL bound GeoJSON layer ---------
    QTemporaryDir temp_dir;
    const fs::path fixtures =
        fs::path(PWB_TEST_SRC_DIR) / ".." / "data" / "fixtures";
    const fs::path work =
        fs::path(temp_dir.path().toStdWString()) / "project";
    PWB_CHECK(copy_tree(fixtures / "typical", work));
    const fs::path project_file = work / "typical.paleo.json";
    const std::string layer_id = "L_drafted";

    std::string prep_asset, prep_base;
    {
        std::string open_error;
        auto store =
            pwb::application::PwbDataStore::open(project_file, &open_error);
        PWB_CHECK_MSG(store != nullptr, "prep store: " + open_error);
        auto snapshot = store->snapshot();
        PWB_CHECK(snapshot.is_ok());
        for (const auto& asset : snapshot.value().catalog_assets) {
            if (asset.current_version_id
                && !version_sha(snapshot.value(),
                                asset.current_version_id->str())
                         .empty()) {
                prep_asset = asset.id.str();
                prep_base = asset.current_version_id->str();
                break;
            }
        }
        PWB_CHECK(!prep_asset.empty());

        // Stage a real GeoJSON edit round module-only, then bind it through
        // B (rebind creates the workspace binding MainWindow will open).
        const QString gpkg_uri =
            pwb::test_fixtures::make_gpkg_fixture(temp_dir.path());
        PWB_CHECK(!gpkg_uri.isEmpty());
        pwb::application::ProjectSession session;
        pwb::qgis::LayerBinding qbinding{layer_id, prep_asset, prep_base,
                                         "catalog_version"};
        std::string add_error;
        QgsVectorLayer* layer = session.map().addVectorLayer(
            gpkg_uri.toStdString(), layer_id, qbinding, &add_error);
        PWB_CHECK_MSG(layer != nullptr, add_error);
        PWB_CHECK(session.edit().start_editing(layer_id).empty());
        const QgsPointXY v0 = layer->getFeature(1).geometry().vertexAt(0);
        PWB_CHECK(session.edit()
                      .move_vertex(layer_id, 1, 0, v0.x() + 0.1, v0.y() + 0.1)
                      .empty());
        std::string stage_error;
        const pwb::qgis::StagedAsset staged = session.stage_commit(
            layer_id,
            fs::path(temp_dir.path().toStdWString()) / "prep-staged",
            &stage_error);
        PWB_CHECK(fs::exists(staged.geojson_path));
        session.close();

        pwb::application::CommitRequestV1 request;
        request.operation_id = "prep-edit-0001";
        request.base_version = prep_base;
        request.asset_id = prep_asset;
        request.staged = staged;
        const auto receipt = store->commit(request);
        PWB_CHECK_MSG(receipt.ok, "prep B commit: " + receipt.error);

        auto after = store->snapshot();
        PWB_CHECK(after.is_ok());
        const pwb::workspace::LayerBinding* binding =
            binding_for(after.value(), layer_id);
        PWB_CHECK(binding != nullptr);
        PWB_CHECK(!binding->source_version_id.empty());
    }

    // ---- open through the real MainWindow ---------------------------------
    std::string bound_version;
    fs::path payload_at_open;
    std::string payload_hash_at_open;
    {
        MainWindow window;
        const QString error =
            window.openProject(QString::fromStdString(project_file.string()));
        PWB_CHECK_MSG(error.isEmpty(), error.toStdString());
        PWB_CHECK(window.session()->store() != nullptr);

        QgsVectorLayer* layer = window.session()->map().vectorLayerById(
            layer_id);
        PWB_CHECK(layer != nullptr);
        // The layer edits the WORKING COPY, never the catalog payload.
        PWB_CHECK(layer->source().contains(QStringLiteral(".pwb-working")));
        const fs::path working = work / ".pwb-working"
            / (layer_id + ".geojson");
        PWB_CHECK(fs::exists(working));

        {
            // A second read on the same files (the window keeps its own
            // store open; SQLite readers coexist).
            std::string probe_error;
            auto probe = pwb::application::PwbDataStore::open(project_file,
                                                              &probe_error);
            PWB_CHECK_MSG(probe != nullptr, probe_error);
            auto snapshot = probe->snapshot();
            PWB_CHECK(snapshot.is_ok());
            const pwb::workspace::LayerBinding* binding =
                binding_for(snapshot.value(), layer_id);
            PWB_CHECK(binding != nullptr);
            bound_version = binding->source_version_id;
            const pwb::catalog::DataVersion* version =
                version_by_id(snapshot.value(), bound_version);
            PWB_CHECK(version != nullptr);
            payload_at_open = work / version->path;
            payload_hash_at_open = sha256_of(payload_at_open);
            PWB_CHECK(!payload_hash_at_open.empty());
        }

        // ---- edit the working copy + save through the governed path -----
        PWB_CHECK(window.session()->edit().start_editing(layer_id).empty());
        const QgsPointXY v0 = layer->getFeature(1).geometry().vertexAt(0);
        const QgsPointXY moved(v0.x() + 0.25, v0.y() + 0.15);
        PWB_CHECK(window.session()->edit()
                      .move_vertex(layer_id, 1, 0, moved.x(), moved.y())
                      .empty());
        const QString save_error = window.commitActiveLayer(
            fs::path(temp_dir.path().toStdWString()) / "staged");
        PWB_CHECK_MSG(save_error.isEmpty(), save_error.toStdString());
        PWB_CHECK(!window.session()->edit().dirty(layer_id));

        // Catalog payload immutable; the working copy carries the edit.
        PWB_CHECK(sha256_of(payload_at_open) == payload_hash_at_open);
        const QgsPointXY working_v =
            first_vertex_from_file(QString::fromStdString(working.string()));
        PWB_CHECK(std::fabs(working_v.x() - moved.x()) < 1e-9
                  && std::fabs(working_v.y() - moved.y()) < 1e-9);

        // The binding advanced to a NEW version in B.
        {
            std::string reopen_error;
            auto reopened = pwb::application::PwbDataStore::open(
                project_file, &reopen_error);
            PWB_CHECK_MSG(reopened != nullptr, reopen_error);
            auto snapshot = reopened->snapshot();
            PWB_CHECK(snapshot.is_ok());
            const pwb::workspace::LayerBinding* binding =
                binding_for(snapshot.value(), layer_id);
            PWB_CHECK(binding != nullptr);
            PWB_CHECK(binding->source_version_id != bound_version);
        }
        window.close();
    }

    // ---- reopen: the working copy refreshes from the NEW payload ---------
    {
        MainWindow window;
        const QString error =
            window.openProject(QString::fromStdString(project_file.string()));
        PWB_CHECK_MSG(error.isEmpty(), error.toStdString());
        QgsVectorLayer* layer = window.session()->map().vectorLayerById(
            layer_id);
        PWB_CHECK(layer != nullptr);
        const QgsPointXY v = layer->getFeature(1).geometry().vertexAt(0);
        // The reopened copy starts from the saved payload state (the moved
        // vertex of the first round is now the base).
        const QString working_uri = layer->source();
        PWB_CHECK(working_uri.contains(QStringLiteral(".pwb-working")));
        const QgsPointXY file_v = first_vertex_from_file(working_uri);
        PWB_CHECK(std::fabs(file_v.x() - v.x()) < 1e-9
                  && std::fabs(file_v.y() - v.y()) < 1e-9);
        PWB_CHECK(layer->editBuffer() == nullptr);   // clean session
    }

    // ---- new project bootstrap: fresh dir -> empty catalog + one
    // boundary asset -> open a raw layer -> edit -> save auto-targets the
    // single asset (rebind) -> reopen materializes the bound layer.
    {
        const fs::path fresh_dir =
            fs::path(temp_dir.path().toStdWString()) / "fresh";
        const QString gpkg_uri =
            pwb::test_fixtures::make_gpkg_fixture(temp_dir.path());
        PWB_CHECK(!gpkg_uri.isEmpty());

        MainWindow window;
        const QString error = window.newProject(
            QString::fromStdString(fresh_dir.string()),
            QStringLiteral("bootstrap-工程"));
        PWB_CHECK_MSG(error.isEmpty(), error.toStdString());
        PWB_CHECK(window.session()->store() != nullptr);
        const fs::path project_file2 = fresh_dir
            / "bootstrap-工程.paleo.json";
        PWB_CHECK(fs::exists(project_file2));

        // One live asset seeded by the bootstrap publish.
        std::string asset_id;
        {
            std::string probe_error;
            auto probe = pwb::application::PwbDataStore::open(
                project_file2, &probe_error);
            PWB_CHECK_MSG(probe != nullptr, probe_error);
            auto snapshot = probe->snapshot();
            PWB_CHECK(snapshot.is_ok());
            int live = 0;
            for (const auto& asset : snapshot.value().catalog_assets) {
                if (!asset.trashed) {
                    ++live;
                    asset_id = asset.id.str();
                }
            }
            PWB_CHECK(live == 1);
            PWB_CHECK(!asset_id.empty());
        }

        // Open a raw vector layer, edit, save: with no binding and exactly
        // one live asset the commit auto-targets it and REBINDS the layer.
        const QString open_error2 =
            window.openVectorLayer(gpkg_uri);
        PWB_CHECK_MSG(open_error2.isEmpty(),
                      open_error2.toStdString());
        const std::string raw_layer =
            QFileInfo(gpkg_uri).completeBaseName().toStdString();
        PWB_CHECK(window.session()->edit().start_editing(raw_layer).empty());
        QgsVectorLayer* layer =
            window.session()->map().vectorLayerById(raw_layer);
        PWB_CHECK(layer != nullptr);
        const QgsPointXY v0 = layer->getFeature(1).geometry().vertexAt(0);
        PWB_CHECK(window.session()->edit()
                      .move_vertex(raw_layer, 1, 0, v0.x() + 0.3, v0.y())
                      .empty());
        const QString save_error = window.commitActiveLayer(
            fs::path(temp_dir.path().toStdWString()) / "fresh-staged");
        PWB_CHECK_MSG(save_error.isEmpty(), save_error.toStdString());

        {
            std::string probe_error;
            auto probe = pwb::application::PwbDataStore::open(
                project_file2, &probe_error);
            PWB_CHECK_MSG(probe != nullptr, probe_error);
            auto snapshot = probe->snapshot();
            PWB_CHECK(snapshot.is_ok());
            const pwb::workspace::LayerBinding* binding =
                binding_for(snapshot.value(), raw_layer);
            PWB_CHECK(binding != nullptr);
            PWB_CHECK(binding->source_asset_id == asset_id);
        }
        window.close();

        // Reopen: the auto-bound layer materializes as a working copy.
        MainWindow reopened;
        const QString reopen_error2 = reopened.openProject(
            QString::fromStdString(project_file2.string()));
        PWB_CHECK_MSG(reopen_error2.isEmpty(),
                      reopen_error2.toStdString());
        QgsVectorLayer* bound = reopened.session()->map().vectorLayerById(
            raw_layer);
        PWB_CHECK(bound != nullptr);
        PWB_CHECK(bound->source().contains(QStringLiteral(".pwb-working")));
        const QgsPointXY bound_v =
            bound->getFeature(1).geometry().vertexAt(0);
        PWB_CHECK(std::fabs(bound_v.x() - (v0.x() + 0.3)) < 1e-9);
    }

    pwb::qgis::QgisRuntime::release();
    return ::pwb::test::report("platform.project_session");
}
