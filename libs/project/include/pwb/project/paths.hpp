// Path conventions (project/paths.py parity).
#pragma once

#include "pwb/domain/diagnostics.hpp"
#include "pwb/domain/errors.hpp"

#include <filesystem>
#include <optional>
#include <string>

namespace pwb::project {

namespace fs = std::filesystem;

// ---- UTF-8 bridge ----------------------------------------------------------
// JSON carries UTF-8; on Windows fs::path is wchar_t and its narrow
// conversions use the ANSI codepage — silently corrupting Chinese paths.
// Every string↔path crossing at a persistence boundary goes through these.
fs::path path_from_u8(std::string_view utf8);
std::string path_to_u8(const fs::path& path);  // generic (forward-slash) UTF-8

// `<name>.artifacts` sibling of the project file (artifact_dir_for).
fs::path artifact_dir_for(const fs::path& project_path);

// paths.py ensure_artifact_layout parity: create the durable artifact
// layout (cache/factor_maps/predictions/paleomaps/qc/exports/thumbnails)
// a new project's portable metadata may reference. Idempotent.
fs::path ensure_artifact_layout(const fs::path& project_path);

// Resolved parent directory of the project file (project_dir_for).
fs::path project_dir_for(const fs::path& project_path);

// `<artifacts>/metadata` (canonical catalog.sqlite + checkpoint home).
fs::path catalog_dir_for(const fs::path& project_path);
fs::path catalog_sqlite_for(const fs::path& project_path);
fs::path catalog_manifest_for(const fs::path& project_path);

struct Relativized {
    std::string stored;   // portable form written to the file
    bool external = false;
};

// Save-side normalization: project-internal → POSIX relative + external
// false; anything else → absolute POSIX + external true.
Relativized relativize_path(const fs::path& path,
                            const fs::path& project_path);

// Load-side resolution: absolute passes through; relative joins the project
// dir and MUST stay inside it (`..` escape → PathEscape, matching
// resolve_project_path). Empty path → PathEscape.
domain::Result<std::string> resolve_project_path(const std::string& stored,
                                                 const fs::path& project_path);

// Best-effort fsync of a directory (Windows: opening a directory needs
// FILE_FLAG_BACKUP_SEMANTICS; failure is non-fatal like Python fsync_dir).
void fsync_directory(const fs::path& directory);

// True if path == directory or is a descendant after lexically_normal
// resolution (no symlink resolution — the C++ side never writes symlinks).
bool is_within_directory(const fs::path& path, const fs::path& directory);

}  // namespace pwb::project
