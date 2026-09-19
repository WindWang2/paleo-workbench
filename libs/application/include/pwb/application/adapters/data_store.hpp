#pragma once

// PwbDataStore — the real B implementation of A's IProjectStore port
// (v3-contracts.md §5). Owns one writable project context assembled from
// B's COMMITTED surface (ProjectManager + CatalogRepository +
// CommitCoordinator over DataFacade's journal dir): reads go through
// DataFacade snapshots (zero writes), every commit goes through B's
// CommitCoordinator with caller-supplied operation_id idempotency. B's
// WritableSession is not consumed yet (headers committed, implementation
// pending on their branch); when B delivers it this class switches to it
// without changing A's port.
//
// Cross-domain translation lives here and only here (string ids <->
// domain::StrongId, staged GeoJSON -> StagedAssetV1).

#include <filesystem>
#include <memory>
#include <string>
#include <vector>

#include <pwb/application/adapters/project_store.hpp>
#include <pwb/catalog/repository.hpp>
#include <pwb/data/commit_coordinator.hpp>
#include <pwb/data/facade.hpp>
#include <pwb/project/manager.hpp>

namespace pwb::application {

class PwbDataStore : public IProjectStore {
public:
    // Opens read-write (a store that cannot write must not exist): refuses
    // unreadable projects, corrupt stores and read-only (future schema)
    // documents. Returns nullptr + error; never a fake store.
    static std::shared_ptr<PwbDataStore> open(
        const std::filesystem::path& project_file, std::string* error);

    // ---- IProjectStore (A port) -------------------------------------------
    ProjectSnapshotV1 open(const std::string& project_uri) override;
    std::vector<LayerBindingV1> load_bindings() override;
    CommitReceiptV1 commit(const CommitRequestV1& request) override;

    // ---- B surfaces for the application/tests ------------------------------
    pwb::data::CommitCoordinator& coordinator() {
        return impl_->coordinator;
    }
    pwb::project::ProjectDocument& document() { return impl_->document; }
    const std::filesystem::path& project_file() const {
        return impl_->manager.path();
    }
    // Resumes/rolls back unfinished journals (B recovery entry).
    pwb::data::RecoveryReportV1 recover() {
        return impl_->coordinator.recover(impl_->document);
    }
    // Checkpoints metadata/catalog.json (B's ADR 0056 export contract:
    // atomic, previous revision kept as .bak).
    pwb::domain::DataError export_manifest() {
        return impl_->repository.export_manifest(
            pwb::project::catalog_manifest_for(project_file()));
    }
    // Fresh zero-write snapshot of the underlying project.
    pwb::domain::Result<pwb::data::ProjectSnapshotV1> snapshot() const {
        return pwb::data::DataFacade(project_file()).open_snapshot();
    }

    // The layer binding B holds for one domain layer id (nullptr when the
    // layer is not bound in the workspace).
    const pwb::workspace::LayerBinding* binding_for(
        const std::string& layer_id) const;

private:
    struct Impl {
        // The repository is constructed in place from its sqlite path —
        // CatalogRepository is not movable since #1380/#1381 (it owns a
        // serialization mutex). PwbDataStore::open pre-validates
        // writability on a throwaway probe before constructing.
        Impl(pwb::project::ProjectManager m, std::filesystem::path sqlite_path,
             pwb::project::ProjectDocument d);
        pwb::project::ProjectManager manager;
        pwb::catalog::CatalogRepository repository;
        pwb::project::ProjectDocument document;
        pwb::data::CommitCoordinator coordinator;
    };

    explicit PwbDataStore(std::unique_ptr<Impl> impl,
                          pwb::data::ProjectSnapshotV1 initial);
    std::unique_ptr<Impl> impl_;
    pwb::data::ProjectSnapshotV1 snapshot_cache_;
};

}  // namespace pwb::application
