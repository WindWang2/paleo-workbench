// ProjectManager — crash-safe read/write of `*.paleo.json`
// (project/manager.py parity: atomic replace + single .bak + v6 recovery
// decision table + #411/#1229 stale-write guard).
#pragma once

#include "pwb/domain/diagnostics.hpp"
#include "pwb/project/document.hpp"
#include "pwb/project/paths.hpp"

#include <filesystem>
#include <optional>
#include <string>

namespace pwb::project {

namespace fs = std::filesystem;

struct LoadedProject {
    ProjectDocument document;
    bool recovered = false;
    std::string recovery_source;      // backup-interrupted-save / backup-corrupt-main
    std::optional<std::string> quarantine;  // isolated corrupt main path
};

struct SaveStats {
    bool wrote = false;
    std::string updated_at;
    std::uintmax_t bytes_written = 0;
};

fs::path project_backup_path(const fs::path& project_path);

class ProjectManager {
public:
    explicit ProjectManager(fs::path project_path);

    // Deterministic timestamp injection for tests (empty → wall clock).
    void set_clock_for_tests(std::string fixed_iso) {
        fixed_clock_ = std::move(fixed_iso);
    }

    // Load with the full recovery decision table. NEVER falls back to .bak
    // on transient read failures (PermissionError parity: honest error).
    domain::Result<LoadedProject> load();

    // Build the portable payload (path relativization for the 5 path-bearing
    // sections + meta overrides) and atomically replace the file.
    domain::Result<SaveStats> save(ProjectDocument& document);

    // Save-side normalization only (no file IO) — exposed for tests and
    // pwb-migrate preflight.
    domain::Json build_portable_payload(const ProjectDocument& document) const;

    const fs::path& path() const { return project_path_; }
    const std::optional<std::string>& last_disk_sha256() const {
        return disk_sha256_;
    }

    // Raw hash helper (SHA-256 hex of file bytes; nullopt when unreadable).
    static std::optional<std::string> file_sha256(const fs::path& file);

private:
    domain::Result<LoadedProject> load_primary();
    domain::Result<LoadedProject> recover_from_backup(
        const std::string& failure_class);
    void cleanup_stale_temps();
    domain::Result<SaveStats> write_payload(const std::string& payload);

    fs::path project_path_;
    std::optional<std::string> fixed_clock_;
    std::optional<std::string> disk_sha256_;  // baseline at load/last save
};

// Relativizes the five path-bearing sections in `payload` in place
// (manager.py _portable_section parity).
void make_sections_portable(domain::Json& payload, const fs::path& project_path);

// Resolves stored paths for runtime access; escape → diagnostic + nullopt
// entry. Used by the snapshot layer (never mutates the document).
struct ResolvedResource {
    std::string id;
    std::string stored;
    std::string resolved;      // empty when resolution failed
    bool external = false;
    bool exists = false;
    std::string error;         // empty when ok
};
std::vector<ResolvedResource> resolve_resource_paths(
    const ProjectDocument& document, const fs::path& project_path);

}  // namespace pwb::project
