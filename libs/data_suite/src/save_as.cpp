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
    // Same-location save-as is a plain save (Python guards the relocation
    // block with old_path != target; no refusal, no staging).
    std::error_code same_ec;
    const bool same_target =
        fs::weakly_canonical(target_file, same_ec) ==
            fs::weakly_canonical(old_file, same_ec) &&
        !same_ec;

    if (!same_target) {
        // Fail closed on an unreadable target before anything moves.
        const bool target_exists = fs::exists(target_file, ec);
        if (ec) {
            return domain::DataError(domain::ErrorCode::InvalidArgument,
                                     "save-as target unreadable: " +
                                         target_file.string());
        }
        (void)target_exists;
        // Refuse a target that already owns artifacts — merging into an
        // occupied tree is a user decision, never a silent save-as side
        // effect (Python save_project_as refuses on any existing dir).
        const fs::path target_artifacts =
            project::artifact_dir_for(target_file);
        if (fs::exists(target_artifacts, ec)) {
            if (ec) {
                return domain::DataError(
                    domain::ErrorCode::InvalidArgument,
                    "save-as target unreadable: " +
                        target_artifacts.string());
            }
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

    const auto restore_document = [&] {
        // Failure must not leave the caller's in-memory document pointing
        // at the rolled-back target tree (Python re-rebases back in its
        // except branch).
        project::rebase_project_artifact_paths(session.document().root(),
                                               target_file, old_file);
    };

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
            restore_document();
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
        restore_document();
        return saved.error();
    }
    if (will_relocate) {
        // The old session's read-write sqlite handle must not outlive the
        // source tree it points into (Windows cannot delete an open file;
        // Python closes the handle before relocating).
        session.repository().close();
        // commit() False means the target is durable but source debris
        // remains — surfaced honestly instead of reported as relocated.
        outcome.artifacts_relocated = staged.value().commit();
    }
    return domain::Result<SaveAsOutcome>(std::move(outcome));
}

}  // namespace pwb::data
