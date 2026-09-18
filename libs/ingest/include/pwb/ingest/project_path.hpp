// Project path resolution with traversal rejection — port of the
// paleo_workbench/project/paths.py surface the ingest flow depends on
// (safe_file_stat / is_within_directory / relativize_path /
// resolve_project_path) plus the preview registry's _resolve_project_path.
#pragma once

#include <filesystem>
#include <optional>
#include <string>
#include <system_error>

namespace pwb::ingest {

struct StatResult {
    long long size = 0;
    long long mtime_ns = 0;
};

// safe_file_stat: (size, mtime_ns) or nullopt when unreadable.
std::optional<StatResult> safe_file_stat(const std::filesystem::path& path);

// is_within_directory: path is directory or descendant (after resolve).
bool is_within_directory(const std::filesystem::path& path,
                         const std::filesystem::path& directory);

// relativize_path: portable (relative-or-absolute posix string, external flag).
struct Relativized {
    std::string path;
    bool external = false;
};
Relativized relativize_path(const std::string& path,
                            const std::filesystem::path& project_path);

// resolve_project_path: relative paths MUST stay inside the project
// directory; escaping raises ProjectPathError (same class name as Python).
struct ProjectPathError : std::runtime_error {
    explicit ProjectPathError(const std::string& message)
        : std::runtime_error(message) {}
};
std::string resolve_project_path(const std::string& path,
                                 const std::filesystem::path& project_path);

// PreviewRegistry._resolve_project_path: existing files win, absolute paths
// pass through, relative joins are confined to the project root; an escape
// returns the ORIGINAL candidate untouched.
std::string resolve_asset_path(const std::string& path,
                               const std::filesystem::path& project_root);

}  // namespace pwb::ingest
