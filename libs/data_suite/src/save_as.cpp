// save_session_as (conv-26) — see save_as.hpp.
#include "pwb/data/save_as.hpp"

#include "pwb/catalog/repository.hpp"
#include "pwb/project/manager.hpp"
#include "pwb/project/relocation.hpp"

#include <system_error>

namespace pwb::data {

domain::Result<SaveAsOutcome> save_session_as(WritableSession& session,
                                              const fs::path& target_file) {
    const fs::path old_file = session.project_file();
    std::error_code ec;
    if (fs::exists(target_file, ec) && ec) {
        return domain::DataError(domain::ErrorCode::InvalidArgument,
                                 "save-as target unreadable: " +
                                     target_file.string());
    }
    // Refuse a target that already owns artifacts — merging into an
    // occupied tree is a user decision, never a silent save-as side
    // effect (Python save_project_as parity).
    const fs::path target_artifacts =
        project::artifact_dir_for(target_file);
    if (fs::exists(target_artifacts, ec) && !ec) {
        fs::directory_iterator probe(target_artifacts, ec);
        if (!ec && probe != fs::directory_iterator()) {
            return domain::DataError(
                domain::ErrorCode::InvalidArgument,
                "save-as target already has artifacts: " +
                    target_artifacts.string());
        }
    }

    auto staged = project::StagedArtifactRelocation::stage(old_file,
                                                           target_file);
    if (!staged.is_ok()) return staged.error();
    const bool will_relocate = staged.value().staged();

    SaveAsOutcome outcome;
    outcome.new_project_file = target_file;
    outcome.rebased_paths = project::rebase_project_artifact_paths(
        session.document().root(), old_file, target_file);

    if (will_relocate) {
        // The staged catalog belongs to the target BEFORE its project JSON
        // lands: rewrite the managed paths' artifacts prefix so an
        // interruption after the JSON replace can never leave a valid
        // target project pointing at the old artifact-directory name
        // (service.py rebase_artifact_paths, called at the same point).
        catalog::CatalogRepository staged_catalog(
            project::catalog_sqlite_for(target_file));
        const int catalog_rebased = staged_catalog.rebase_artifact_paths();
        if (catalog_rebased < 0) {
            staged.value().rollback();
            return domain::DataError(
                domain::ErrorCode::CorruptDatabase,
                "staged catalog rebase failed: " + target_file.string());
        }
        outcome.rebased_paths += catalog_rebased;
    }

    // Write through a manager bound to the TARGET path: the portable
    // payload relativizes against the new directory and stamps
    // meta.project_root there. The stale-write guard starts empty for a
    // fresh file.
    project::ProjectManager target_manager(target_file);
    auto saved = target_manager.save(session.document());
    if (!saved.is_ok()) {
        staged.value().rollback();
        return saved.error();
    }
    if (will_relocate) {
        staged.value().commit();
        outcome.artifacts_relocated = true;
    }
    return domain::Result<SaveAsOutcome>(std::move(outcome));
}

}  // namespace pwb::data
