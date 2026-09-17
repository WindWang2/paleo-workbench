// WritableSession — the explicit write/recovery entry over one project
// (v3-contracts.md §4). Read-only opens (DataFacade, pwb-inspect queries)
// never write; every mutating or recovery write goes through a session the
// caller constructed deliberately: future-schema / read-only projects
// refuse to open here instead of failing later mid-transaction.
//
// The manager/repository/document/coordinator stack is boxed: the
// coordinator binds references to its siblings, so the session is moved as
// a unit and never re-assembled after construction.
#pragma once

#include "pwb/catalog/repository.hpp"
#include "pwb/data/commit_coordinator.hpp"
#include "pwb/data/facade.hpp"
#include "pwb/domain/errors.hpp"
#include "pwb/project/document.hpp"
#include "pwb/project/manager.hpp"

#include <filesystem>
#include <memory>
#include <utility>

namespace pwb::data {

namespace fs = std::filesystem;

class WritableSession {
public:
    // Loads the project document and opens the catalog read-write. Fails
    // for unreadable projects, corrupt stores and read-only (future
    // schema) documents — a session that cannot write must not exist.
    static domain::Result<WritableSession> open(const fs::path& project_file);

    // The ONLY recovery entry: resumes or rolls back every unfinished
    // journal using this session's writable handles. Unresolvable journals
    // stay pending on disk (never auto-deleted) and keep blocking
    // conflicting writes.
    RecoveryReportV1 recover() { return impl_->coordinator.recover(impl_->document); }

    CommitCoordinator& coordinator() { return impl_->coordinator; }
    project::ProjectManager& manager() { return impl_->manager; }
    catalog::CatalogRepository& repository() { return impl_->repository; }
    project::ProjectDocument& document() { return impl_->document; }

    const fs::path& project_file() const { return impl_->manager.path(); }

    WritableSession(WritableSession&&) noexcept = default;
    WritableSession& operator=(WritableSession&&) noexcept = default;

private:
    struct Impl {
        Impl(project::ProjectManager m, catalog::CatalogRepository r,
             project::ProjectDocument d)
            : manager(std::move(m)), repository(std::move(r)),
              document(std::move(d)),
              coordinator(manager, repository,
                          DataFacade::journal_dir_for(manager.path())) {}

        project::ProjectManager manager;
        catalog::CatalogRepository repository;
        project::ProjectDocument document;
        CommitCoordinator coordinator;
    };

    explicit WritableSession(std::unique_ptr<Impl> impl)
        : impl_(std::move(impl)) {}

    std::unique_ptr<Impl> impl_;
};

}  // namespace pwb::data
