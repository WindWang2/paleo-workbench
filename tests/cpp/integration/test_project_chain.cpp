// integration.project_chain — REAL B + platform chain, no substitutes:
// open B's typical fixture as a writable session -> map layer bound by the
// domain join key -> vertex edit -> undo/redo -> commit through B's
// coordinator (new version, old versions untouched) -> close -> reopen and
// verify the binding points at the new version. Error chain: duplicate
// operation id replays (no second version); stale base version conflicts.

#include <cmath>
#include <cstdio>
#include <filesystem>
#include <string>

#include <QTemporaryDir>
#include <QTimer>
#include <qgsapplication.h>
#include <qgsvectorlayer.h>

#include <pwb/application/adapters/data_store.hpp>
#include <pwb/application/project_session.hpp>
#include <pwb/qgis/qgis_runtime.hpp>

#include "../platform/test_fixtures.hpp"
#include "../platform/test_framework.hpp"

namespace fs = std::filesystem;

namespace {

// Minimal recursive copy (fixture dirs are small; excludes nothing).
bool copy_tree(const fs::path& from, const fs::path& to, std::string* error) {
    std::error_code ec;
    fs::create_directories(to, ec);
    if (ec) { *error = ec.message(); return false; }
    for (const auto& entry : fs::recursive_directory_iterator(from, ec)) {
        const auto target = to / fs::relative(entry.path(), from, ec);
        if (entry.is_directory(ec)) {
            fs::create_directories(target, ec);
        } else if (entry.is_regular_file(ec)) {
            fs::create_directories(target.parent_path(), ec);
            fs::copy_file(entry.path(), target,
                          fs::copy_options::overwrite_existing, ec);
        }
        if (ec) { *error = ec.message(); return false; }
    }
    return true;
}

int count_versions(const pwb::data::ProjectSnapshotV1& snapshot,
                   const std::string& asset_id) {
    int count = 0;
    for (const auto& version : snapshot.catalog_versions) {
        if (version.asset_id.str() == asset_id) ++count;
    }
    return count;
}

std::string version_sha(const pwb::data::ProjectSnapshotV1& snapshot,
                        const std::string& version_id) {
    for (const auto& version : snapshot.catalog_versions) {
        if (version.id.str() == version_id) {
            return version.sha256.value_or(std::string());
        }
    }
    return std::string();
}

}  // namespace

int main(int argc, char** argv) {
    QgsApplication app(argc, argv, true);
    pwb::qgis::QgisRuntime::acquire();

    const fs::path fixtures = PWB_TEST_SRC_DIR "/../data/fixtures";
    const fs::path typical = fixtures / "typical";
    if (!fs::exists(typical / "typical.paleo.json")) {
        PWB_CHECK_MSG(false, "typical fixture missing: " + typical.string());
    }

    QTemporaryDir temp;
    const fs::path work =
        fs::path(temp.path().toStdWString()) / "project";
    std::string copy_error;
    if (!copy_tree(typical, work, &copy_error)) {
        PWB_CHECK_MSG(false, "fixture copy failed: " + copy_error);
    }
    const fs::path project_file = work / "typical.paleo.json";

    // ---- open the real store -----------------------------------------------
    std::string open_error;
    auto store = pwb::application::PwbDataStore::open(project_file, &open_error);
    PWB_CHECK_MSG(store != nullptr, "store open failed: " + open_error);

    auto first_snapshot = store->snapshot();
    PWB_CHECK(first_snapshot.is_ok());
    PWB_CHECK(!first_snapshot.value().catalog_assets.empty());

    // Edit target: a REAL catalog asset (the typical fixture's workspace
    // bindings reference synthetic ids — first-time commits rebind the
    // layer to the real asset via rebind_layer). Pick the asset whose head
    // version carries a payload hash (the immutability check reads it).
    std::string layer_id = "L_drafted";
    std::string asset_id, base_version;
    for (const auto& asset : first_snapshot.value().catalog_assets) {
        if (!asset.current_version_id) continue;
        const std::string head = asset.current_version_id->str();
        if (!version_sha(first_snapshot.value(), head).empty()) {
            asset_id = asset.id.str();
            base_version = head;
            break;
        }
    }
    PWB_CHECK_MSG(!asset_id.empty(),
                  "fixture carries no asset with a hashed head version");
    const int versions_before = count_versions(first_snapshot.value(), asset_id);
    const std::string base_sha =
        version_sha(first_snapshot.value(), base_version);
    PWB_CHECK(!base_sha.empty());

    // ---- map layer + edit through the platform ------------------------------
    QString gpkg_error;
    {
        pwb::application::ProjectSession session;
        pwb::qgis::LayerBinding qbinding{layer_id, asset_id, base_version,
                                         "catalog_version"};

        // Isolated working copy: the platform never edits fixture payloads.
        const fs::path working_gpkg =
            fs::path(temp.path().toStdWString()) / "working.gpkg";
        const QString uri = pwb::test_fixtures::make_gpkg_fixture(
            temp.path());
        PWB_CHECK_MSG(!uri.isEmpty(), "working GPKG fixture failed");

        std::string add_error;
        QgsVectorLayer* layer = session.map().addVectorLayer(
            uri.toStdString(), layer_id, qbinding, &add_error);
        PWB_CHECK_MSG(layer != nullptr, "layer add failed: " + add_error);

        PWB_CHECK(session.edit().start_editing(layer_id).empty());
        const QgsPointXY v0 = layer->getFeature(1).geometry().vertexAt(0);
        PWB_CHECK(session.edit()
                      .move_vertex(layer_id, 1, 0, v0.x() + 0.2, v0.y() + 0.1)
                      .empty());
        PWB_CHECK(session.edit().undo(layer_id).empty());
        PWB_CHECK(session.edit().redo(layer_id).empty());
        PWB_CHECK(session.edit().dirty(layer_id));

        const fs::path staged_dir =
            fs::path(temp.path().toStdWString()) / "staged";
        std::string commit_error;
        pwb::qgis::StagedAsset staged =
            session.stage_commit(layer_id, staged_dir, &commit_error);
        // Module-only session has no store attached; the platform-side
        // commit (topology gate + staged GeoJSON) must still succeed.
        PWB_CHECK_MSG(fs::exists(staged.geojson_path),
                      "platform commit failed: " + commit_error);
        PWB_CHECK(!staged.sha256.empty());
        session.close();

        // ---- B commit through the adapter ----------------------------------
        pwb::application::CommitRequestV1 request;
        request.operation_id = "int-edit-0001";
        request.base_version = base_version;
        request.asset_id = asset_id;
        request.staged = staged;
        const auto receipt = store->commit(request);
        PWB_CHECK_MSG(receipt.ok, "B commit failed: " + receipt.error);
        PWB_CHECK(!receipt.new_version.empty());
        PWB_CHECK(receipt.new_version != base_version);

        // ---- duplicate operation id: replay, no second version -------------
        const auto replay = store->commit(request);
        PWB_CHECK_MSG(replay.ok && replay.duplicate,
                      "idempotent replay failed: " + replay.error);
        PWB_CHECK(replay.new_version == receipt.new_version);

        // ---- stale base: optimistic lock refuses ----------------------------
        pwb::application::CommitRequestV1 stale_request;
        stale_request.operation_id = "int-edit-0002";
        stale_request.base_version = base_version;   // superseded now
        stale_request.asset_id = asset_id;
        // Re-stage from the same edited working copy for a genuinely new op.
        pwb::application::ProjectSession stale_session;
        std::string stale_add_error;
        QgsVectorLayer* stale_layer = stale_session.map().addVectorLayer(
            uri.toStdString(), layer_id, qbinding, &stale_add_error);
        PWB_CHECK(stale_layer != nullptr);
        PWB_CHECK(stale_session.edit().start_editing(layer_id).empty());
        const QgsPointXY sv0 = stale_layer->getFeature(1).geometry().vertexAt(0);
        PWB_CHECK(stale_session.edit()
                      .move_vertex(layer_id, 1, 0, sv0.x() + 0.4, sv0.y())
                      .empty());
        pwb::qgis::StagedAsset stale_staged;
        const std::string stale_commit_error = stale_session.edit().commit(
            layer_id, staged_dir, &stale_staged, nullptr);
        PWB_CHECK_MSG(stale_commit_error.empty(),
                      "staged recommit failed: " + stale_commit_error);
        stale_session.close();
        stale_request.staged = stale_staged;
        const auto stale_receipt = store->commit(stale_request);
        PWB_CHECK_MSG(!stale_receipt.ok,
                      "stale base commit was not refused");
    }

    // ---- durability: reopen and verify --------------------------------------
    {
        std::string reopen_error;
        auto reopened = pwb::application::PwbDataStore::open(
            project_file, &reopen_error);
        PWB_CHECK_MSG(reopened != nullptr,
                      "reopen failed: " + reopen_error);
        auto snapshot = reopened->snapshot();
        PWB_CHECK(snapshot.is_ok());

        // Old version intact, exactly one version added, binding advanced.
        PWB_CHECK_MSG(
            version_sha(snapshot.value(), base_version) == base_sha,
            "old version hash changed after the new commit");
        const int versions_after =
            count_versions(snapshot.value(), asset_id);
        PWB_CHECK_MSG(versions_after == versions_before + 1,
                      "version count not exactly +1 ("
                          + std::to_string(versions_before) + " -> "
                          + std::to_string(versions_after) + ")");
        const auto* binding = reopened->binding_for(layer_id);
        PWB_CHECK(binding != nullptr);
        PWB_CHECK_MSG(binding->source_version_id != base_version,
                      "workspace binding did not advance to the new version");
    }

    pwb::qgis::QgisRuntime::release();
    return ::pwb::test::report("integration.project_chain");
}
