// Trash lifecycle + working copies over the artifacts tree (conv-31;
// catalog/storage.py remaining surface parity).
//
// dedup.hpp already carries the blob store and place_managed_file; this
// header completes the storage contract: the CAS-path test, the
// trash/{version_id}/ move (atomic, same-filesystem, with directory
// fsyncs and empty-ancestor pruning), restore (read-only re-marked),
// best-effort purge (shared-blob refcount awareness) and mutable
// working-copy creation (full copy, never a hardlink).
#pragma once

#include "pwb/domain/errors.hpp"
#include "pwb/domain/stage.hpp"

#include <filesystem>
#include <optional>
#include <string>

namespace pwb::catalog {

namespace fs = std::filesystem;

// storage.py STAGE_DIRS: DataStage → directory name ("outputs" for OUTPUT).
std::string stage_dir_name(domain::DataStage stage);

fs::path working_dir_for(const fs::path& project_path);
fs::path trash_dir_for(const fs::path& project_path);

// storage.py is_safe_entity_id (#1175): non-empty, no leading dot, only
// [A-Za-z0-9._-], no "..".
bool is_safe_entity_id(const std::string& entity_id);

// True when *rel_path* (project-relative as stored on a DataVersion, or
// absolute) points into blobs/ — blob-backed payloads are shared, so the
// lifecycle treats them by refcount, never move/unlink.
bool is_cas_path(const fs::path& project_path, const std::string& rel_path);

// Move a managed payload into trash/{version_id}/ (files and whole
// directory trees alike). Returns the new project-relative POSIX path;
// blob-backed paths return unchanged. Missing payloads are an error
// (callers decide on metadata-only tombstones).
domain::Result<std::string> trash_payload(const fs::path& project_path,
                                           const fs::path& version_path,
                                           const std::string& version_id);

// Move a trashed payload back to *original_rel_path* (managed read-only
// bit restored). Blob-backed paths return unchanged.
domain::Result<std::string> restore_payload(const fs::path& project_path,
                                             const fs::path& version_path,
                                             const std::string& original_rel_path);

// Permanently delete a trashed payload (best-effort; missing = already
// gone). *shared* leaves a shared blob in place (refcount semantics).
void purge_trashed_payload(const fs::path& project_path,
                           const fs::path& version_path, bool shared = false);

// Copy a committed payload into working/{version_id}/ as a mutable file
// (atomic temp + rename; always a full copy).
domain::Result<fs::path> create_working_copy(const fs::path& project_path,
                                              const fs::path& version_path,
                                              const std::string& version_id);

}  // namespace pwb::catalog
