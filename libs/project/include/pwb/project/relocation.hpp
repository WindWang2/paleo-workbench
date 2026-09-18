// Save-As artifact relocation (conv-26; project/paths.py
// StagedArtifactRelocation / stage_artifact_relocation /
// relocate_artifacts / rebase_owned_artifact_path parity). Conservative,
// never destroys data: fresh targets are COPIED and the source tree is
// only removed after the target project metadata is durable (commit);
// existing target roots only receive missing direct children and every
// owned move stays reversible (rollback).
#pragma once

#include "pwb/domain/errors.hpp"
#include "pwb/domain/json.hpp"

#include <filesystem>
#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace pwb::project {

namespace fs = std::filesystem;

// Best-effort recursive removal that clears read-only flags on demand
// (#1190 parity): True when the tree is gone (or never existed).
bool safe_rmtree(const fs::path& path);

class StagedArtifactRelocation {
public:
    StagedArtifactRelocation(fs::path source, fs::path target);

    // Stage a reversible relocation for a Save As transaction. Same
    // artifacts location (or no source artifacts) → a no-op staging.
    static domain::Result<StagedArtifactRelocation> stage(
        const fs::path& old_project_path, const fs::path& new_project_path);

    bool staged() const;
    // Finalize a source-preserving copy only after target metadata is
    // durable. True when nothing remains to clean; False means the target
    // is durable but source debris is still present (safe direction — the
    // old project stays usable; the caller decides whether to surface it).
    bool commit();
    // Best-effort reversal limited to entries this transaction owns. True
    // when every owned entry was restored/removed.
    bool rollback();

    const fs::path& source() const { return source_; }
    const fs::path& target() const { return target_; }

private:
    fs::path source_;
    fs::path target_;
    bool moved_root_ = false;
    bool copied_root_ = false;
    bool preserved_source_ = false;
    std::vector<std::pair<fs::path, fs::path>> moved_children_;
};

// One-shot re-home of `<old>.artifacts/` to the save-as location; True when
// anything was moved/merged.
bool relocate_artifacts(const fs::path& old_project_path,
                        const fs::path& new_project_path);

// Rewrite a project-owned artifact path after Save As relocation.
// Resolve-against-old-root first, then a `<name>.artifacts/` prefix rewrite
// so relative refs that resolve against CWD still move with the project.
// Nullopt when the path is external / unrelated.
std::optional<std::string> rebase_owned_artifact_path(
    const std::string& raw, const fs::path& old_root, const fs::path& new_root,
    const std::optional<fs::path>& project_dir = std::nullopt);

// Rebase the document's owned artifact-path sections after relocation
// (factor_map_tasks[].grid_artifact_path, {horizon,correlation,fault}_
// interpretations[].artifact_path — the sections whose payloads live under
// the artifacts root). Returns the number of rewritten values.
int rebase_project_artifact_paths(domain::Json& document_root,
                                  const fs::path& old_project_path,
                                  const fs::path& new_project_path);

}  // namespace pwb::project
