// platform.adapters.substitutes — A4 (module-only): B/C port substitutes
// verify the platform-side wiring of the staged-asset commit protocol and
// the result publisher port. Real B/C E2E integration is a separate gate and
// is NOT claimed by this test.

#include <cmath>

#include <qgsapplication.h>
#include <QTemporaryDir>

#include <qgsvectorlayer.h>

#include <pwb/application/adapters/result_publisher.hpp>
#include <pwb/application/project_session.hpp>
#include <pwb/qgis/map_session.hpp>
#include <pwb/qgis/qgis_runtime.hpp>
#include <pwb/tool_policy/tool_availability.hpp>

#include "test_fixtures.hpp"
#include "test_framework.hpp"

namespace {

// B-side substitute: records the CommitRequest and issues a fake-new-version
// receipt. Test-only; the real store is B's recovery-coordinated SQLite path.
class SubstitututeProjectStore : public pwb::application::IProjectStore {
public:
    pwb::application::ProjectSnapshotV1 open(const std::string&) override {
        ++opens_;
        return pwb::application::ProjectSnapshotV1{"pid", "v13", {}};
    }
    std::vector<pwb::application::LayerBindingV1> load_bindings() override {
        return {{"adapters.layer", "asset-1", "version-1", "vector"}};
    }
    pwb::application::CommitReceiptV1 commit(
        const pwb::application::CommitRequestV1& request) override {
        ++commits_;
        last_operation_id_ = request.operation_id;
        last_base_version_ = request.base_version;
        last_staged_path_ = request.staged.geojson_path.string();
        last_sha256_ = request.staged.sha256;
        operation_ids_.push_back(request.operation_id);
        pwb::application::CommitReceiptV1 receipt;
        receipt.ok = !request.staged.sha256.empty()
            && std::filesystem::exists(request.staged.geojson_path)
            && reject_next_ == 0;
        if (reject_next_ > 0) --reject_next_;
        receipt.new_version = receipt.ok ? "version-2" : std::string();
        receipt.error = receipt.ok ? std::string()
                                   : (request.staged.sha256.empty() ||
                                              !std::filesystem::exists(
                                                  request.staged.geojson_path)
                                          ? "staged asset missing"
                                          : "scripted rejection (test)");
        return receipt;
    }
    int opens_ = 0;
    int commits_ = 0;
    int reject_next_ = 0;   // reject the next N commits (failure injection)
    std::string last_operation_id_;
    std::string last_base_version_;
    std::string last_staged_path_;
    std::string last_sha256_;
    std::vector<std::string> operation_ids_;
};

// C-side substitute publisher (module-only verification of the port).
class SubstituteResultPublisher : public pwb::application::IResultPublisher {
public:
    bool publish(const std::vector<pwb::application::ResultAssetV1>& assets,
                 const pwb::application::ProvenanceRecordV1& provenance,
                 std::string* new_version) override {
        published_ += static_cast<int>(assets.size());
        last_algorithm_ = provenance.algorithm_id;
        if (new_version != nullptr) *new_version = "run-1";
        return !assets.empty();
    }
    int published_ = 0;
    std::string last_algorithm_;
};

}  // namespace

int main(int argc, char** argv) {
    QgsApplication app(argc, argv, true);
    pwb::qgis::QgisRuntime::acquire();

    QTemporaryDir temp_dir;
    const QString gpkg_uri = pwb::test_fixtures::make_gpkg_fixture(temp_dir.path());
    PWB_CHECK_MSG(!gpkg_uri.isEmpty(), "fixture creation failed");
    const std::filesystem::path staged_dir =
        std::filesystem::path(temp_dir.path().toStdWString()) / "staged";

    {
        pwb::application::ProjectSession session;
        std::string error;
        auto* layer = session.map().addVectorLayer(
            gpkg_uri.toStdString(), "adapters",
            {"adapters.layer", "asset-1", "version-1", "vector"}, &error);
        PWB_CHECK_MSG(layer != nullptr, error);

        pwb::application::DomainLayerFacts facts;
        facts.layer_id = "adapters.layer";
        facts.role = "facies_boundary";
        facts.write_granted = true;
        session.set_active_layer(facts);
        PWB_CHECK(session.active_layer_error().empty());

        // Without a store: honest module-only error, staged asset still real.
        // (An edit session + one change first — commit requires a session.)
        PWB_CHECK(session.edit().start_editing("adapters.layer").empty());
        const QgsPointXY first_v0 = layer->getFeature(1).geometry().vertexAt(0);
        PWB_CHECK(session.edit().move_vertex("adapters.layer", 1, 0,
                                             first_v0.x() + 0.05,
                                             first_v0.y() + 0.05).empty());
        std::string module_only_error;
        pwb::qgis::StagedAsset staged =
            session.stage_commit("adapters.layer", staged_dir, &module_only_error);
        PWB_CHECK(!module_only_error.empty());
        PWB_CHECK(module_only_error.find("module-only") != std::string::npos);
        PWB_CHECK(std::filesystem::exists(staged.geojson_path));

        // With the B substitute: full staged protocol round-trip.
        auto store = std::make_shared<SubstitututeProjectStore>();
        session.set_store(store);
        PWB_CHECK(session.edit().start_editing("adapters.layer").empty());
        const QgsPointXY v0 = layer->getFeature(1).geometry().vertexAt(0);
        PWB_CHECK(session.edit().move_vertex("adapters.layer", 1, 0, v0.x() + 0.1,
                                             v0.y() + 0.1).empty());
        std::string store_error;
        staged = session.stage_commit("adapters.layer", staged_dir, &store_error);
        PWB_CHECK_MSG(store_error.empty(), store_error);
        PWB_CHECK(store->commits_ == 1);
        PWB_CHECK(store->last_operation_id_.find("pwb-edit-adapters.layer") == 0);
        PWB_CHECK(store->last_sha256_ == staged.sha256);
        PWB_CHECK(!store->last_staged_path_.empty());

        // C-side port substitute.
        SubstituteResultPublisher publisher;
        pwb::application::ResultAssetV1 asset;
        asset.asset_path = staged.geojson_path.string();
        asset.kind = "vector";
        asset.sha256 = staged.sha256;
        pwb::application::ProvenanceRecordV1 provenance;
        provenance.algorithm_id = "pwb.test.algorithm";
        provenance.algorithm_version = "1";
        std::string new_version;
        PWB_CHECK(publisher.publish({asset}, provenance, &new_version));
        PWB_CHECK(publisher.published_ == 1);
        PWB_CHECK(new_version == "run-1");

        // Snapshot derivation sanity: the session collector feeds the
        // evaluator with live facts (active layer resolves, editing closed).
        const auto snapshot = session.snapshot();
        PWB_CHECK(snapshot.active_layer_id == "adapters.layer");
        PWB_CHECK(snapshot.active_layer_kind == "polygon");
        PWB_CHECK(snapshot.editing == false);  // commit closed the session
        const auto availability =
            pwb::tool_policy::evaluate_all(snapshot);
        PWB_CHECK(availability.at("vertex").enabled == false);
        PWB_CHECK(availability.at("toggle_editing").enabled);

        session.close();
    }

    // ---- review P1 locks: consecutive rounds get distinct operation ids,
    // a rejected catalog commit never writes the source provider, and a
    // retry of the same content reuses the same operation id.
    {
        const auto same_pos = [](const QgsPointXY& a, const QgsPointXY& b) {
            return std::fabs(a.x() - b.x()) < 1e-9
                && std::fabs(a.y() - b.y()) < 1e-9;
        };

        pwb::application::ProjectSession session;
        std::string error;
        auto* layer = session.map().addVectorLayer(
            gpkg_uri.toStdString(), "adapters2",
            {"adapters.layer", "asset-1", "version-1", "vector"}, &error);
        PWB_CHECK_MSG(layer != nullptr, error);
        auto store = std::make_shared<SubstitututeProjectStore>();
        session.set_store(store);

        // Round 1: frozen base version comes from the store's binding.
        PWB_CHECK(session.edit().start_editing("adapters.layer").empty());
        const QgsPointXY round1_v0 = layer->getFeature(1).geometry().vertexAt(0);
        PWB_CHECK(session.edit().move_vertex("adapters.layer", 1, 0,
                                             round1_v0.x() + 0.1,
                                             round1_v0.y() + 0.1).empty());
        std::string round1_error;
        session.stage_commit("adapters.layer", staged_dir, &round1_error);
        PWB_CHECK_MSG(round1_error.empty(), round1_error);
        PWB_CHECK(store->last_base_version_ == "version-1");

        // Round 2 (consecutive round in the same window): a NEW operation
        // id — B must never replay round 1's receipt for new edits.
        PWB_CHECK(session.edit().start_editing("adapters.layer").empty());
        const QgsPointXY round2_v0 = layer->getFeature(1).geometry().vertexAt(0);
        PWB_CHECK(session.edit().move_vertex("adapters.layer", 1, 0,
                                             round2_v0.x() + 0.1,
                                             round2_v0.y() + 0.1).empty());
        std::string round2_error;
        session.stage_commit("adapters.layer", staged_dir, &round2_error);
        PWB_CHECK_MSG(round2_error.empty(), round2_error);
        PWB_CHECK(store->operation_ids_.size() == 2);
        PWB_CHECK(store->operation_ids_[0] != store->operation_ids_[1]);

        // Round 3 with the catalog REJECTING: the source provider must stay
        // untouched and the edit buffer must survive for retry.
        PWB_CHECK(session.edit().start_editing("adapters.layer").empty());
        const QgsPointXY round3_v0 = layer->getFeature(1).geometry().vertexAt(0);
        const QgsPointXY round3_moved(round3_v0.x() + 0.2, round3_v0.y() + 0.2);
        PWB_CHECK(session.edit().move_vertex("adapters.layer", 1, 0,
                                             round3_moved.x(),
                                             round3_moved.y()).empty());
        store->reject_next_ = 1;
        std::string round3_error;
        session.stage_commit("adapters.layer", staged_dir, &round3_error);
        PWB_CHECK(!round3_error.empty());
        PWB_CHECK(round3_error.find("store rejected commit")
                  != std::string::npos);
        PWB_CHECK(session.edit().dirty("adapters.layer"));
        PWB_CHECK(layer->editBuffer() != nullptr);
        // A second reader of the same source file sees the pre-edit vertex:
        // the provider was not written before B accepted.
        QgsVectorLayer source_check(gpkg_uri, "source_check", "ogr");
        PWB_CHECK(source_check.isValid());
        const QgsPointXY source_v =
            source_check.getFeature(1).geometry().vertexAt(0);
        PWB_CHECK(same_pos(source_v, round3_v0));

        // Retry of the SAME staged content: the operation id is reused
        // (B idempotency contract) and acceptance finalizes the provider.
        const std::string rejected_id = store->operation_ids_.back();
        std::string retry_error;
        session.stage_commit("adapters.layer", staged_dir, &retry_error);
        PWB_CHECK_MSG(retry_error.empty(), retry_error);
        PWB_CHECK(store->operation_ids_.back() == rejected_id);
        PWB_CHECK(!session.edit().dirty("adapters.layer"));
        QgsVectorLayer source_after(gpkg_uri, "source_after", "ogr");
        PWB_CHECK(source_after.isValid());
        const QgsPointXY after_v =
            source_after.getFeature(1).geometry().vertexAt(0);
        PWB_CHECK(same_pos(after_v, round3_moved));

        session.close();
    }

    pwb::qgis::QgisRuntime::release();
    return ::pwb::test::report("platform.adapters.substitutes");
}
