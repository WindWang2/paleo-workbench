#include "pwb/catalog/gc.hpp"

#include "pwb/catalog/dedup.hpp"
#include "pwb/project/paths.hpp"

#include <algorithm>
#include <chrono>
#include <ctime>
#include <set>

namespace pwb::catalog {

namespace {

namespace fs = std::filesystem;
using pwb::project::artifact_dir_for;
using pwb::project::project_dir_for;

using pwb::catalog::kStageDirs;  // storage.py STAGE_DIRS: on-disk dir names
const char* const kTempScanSkipRoots[] = {"working", "trash"};

bool is_temp_name(const std::string& name) {
    static const char* const kPrefixes[] = {".place-", ".blob-",
                                            ".catalog.json."};
    if (name.size() >= 4 && name.compare(name.size() - 4, 4, ".tmp") == 0) {
        return true;
    }
    for (const char* prefix : kPrefixes) {
        if (name.rfind(prefix, 0) == 0) return true;
    }
    return false;
}

bool is_leased(const std::string& rel, const std::set<std::string>& leased) {
    for (const std::string& target : leased) {
        if (rel == target
            || (rel.size() > target.size() && rel.compare(0, target.size(), target) == 0
                && rel[target.size()] == '/')) {
            return true;
        }
    }
    return false;
}

bool is_under(const fs::path& path, const fs::path& base) {
    const std::string base_text = base.generic_string();
    const std::string path_text = path.generic_string();
    if (path_text == base_text) return true;
    if (base_text.empty()) return false;
    return path_text.rfind(base_text + "/", 0) == 0;
}

fs::path artifacts_root(const GcContext& context) {
    return artifact_dir_for(context.project_path);
}

fs::path project_root(const GcContext& context) {
    return project_dir_for(context.project_path);
}

// Python `_walk_files`: every regular file below *directory*.
std::vector<fs::path> walk_files(const fs::path& directory) {
    std::vector<fs::path> files;
    std::error_code ec;
    if (!fs::is_directory(directory, ec)) return files;
    for (const fs::directory_entry& entry :
         fs::recursive_directory_iterator(
             directory, fs::directory_options::skip_permission_denied, ec)) {
        std::error_code file_ec;
        if (entry.is_regular_file(file_ec) && !file_ec) {
            files.push_back(entry.path());
        }
    }
    return files;
}

std::string rel_or_empty(const fs::path& project_dir, const fs::path& path) {
    std::error_code ec;
    const fs::path rel = fs::relative(path, project_dir, ec);
    if (ec) return "";
    return pwb::project::path_to_u8(rel);
}

std::int64_t safe_size(const fs::path& path) {
    std::error_code ec;
    const auto size = fs::file_size(path, ec);
    return ec ? 0 : static_cast<std::int64_t>(size);
}

// Empty directories below *root*, deepest first (Python's per-root rglob
// with the -len(parts) ordering).
std::vector<fs::path> empty_dirs_below(const fs::path& root) {
    std::vector<fs::path> empties;
    std::error_code ec;
    if (!fs::is_directory(root, ec)) return empties;
    std::vector<fs::path> dirs;
    for (const fs::directory_entry& entry :
         fs::recursive_directory_iterator(
             root, fs::directory_options::skip_permission_denied, ec)) {
        std::error_code dir_ec;
        if (entry.is_directory(dir_ec) && !dir_ec) {
            dirs.push_back(entry.path());
        }
    }
    std::sort(dirs.begin(), dirs.end(), [](const fs::path& a,
                                           const fs::path& b) {
        const auto da = std::distance(a.begin(), a.end());
        const auto db = std::distance(b.begin(), b.end());
        if (da != db) return da > db;  // deepest first
        return a.generic_string() < b.generic_string();
    });
    for (const fs::path& dir : dirs) {
        std::error_code empty_ec;
        if (fs::is_empty(dir, empty_ec) && !empty_ec) {
            empties.push_back(dir);
        }
    }
    return empties;
}

// Empty directories below the stage/working/trash trees (gc.py `_empty_dirs`).
std::vector<fs::path> empty_dirs(const fs::path& stage_root) {
    std::vector<fs::path> empties;
    for (const char* root_name : kStageDirs) {
        auto sub = empty_dirs_below(stage_root / root_name);
        empties.insert(empties.end(), sub.begin(), sub.end());
    }
    auto working = empty_dirs_below(stage_root / "working");
    empties.insert(empties.end(), working.begin(), working.end());
    auto trash = empty_dirs_below(stage_root / "trash");
    empties.insert(empties.end(), trash.begin(), trash.end());
    return empties;
}

std::set<std::string> referenced_paths(const CatalogDocument& document) {
    std::set<std::string> paths;
    for (const DataVersion& version : document.versions) {
        if (version.managed) paths.insert(version.path);
    }
    return paths;
}

std::set<std::string> known_version_ids(const CatalogDocument& document) {
    std::set<std::string> ids;
    for (const DataVersion& version : document.versions) {
        ids.insert(version.id.str());
    }
    return ids;
}

}  // namespace

std::int64_t GcReport::count(std::optional<std::string_view> kind) const {
    if (!kind.has_value()) {
        return static_cast<std::int64_t>(items.size());
    }
    std::int64_t total = 0;
    for (const GcItem& item : items) {
        if (item.kind == *kind) total += 1;
    }
    return total;
}

std::int64_t GcReport::bytes_for(std::string_view kind) const {
    std::int64_t total = 0;
    for (const GcItem& item : items) {
        if (item.kind == kind) total += item.size;
    }
    return total;
}

std::int64_t GcReport::total_bytes() const {
    std::int64_t total = 0;
    for (const GcItem& item : items) total += item.size;
    return total;
}

std::set<std::string> active_staging_targets(const CatalogDocument& document,
                                             const std::string& cutoff_iso) {
    std::set<std::string> targets;
    for (const StagingLease& lease : document.staging_leases) {
        if (lease.heartbeat_at > cutoff_iso) targets.insert(lease.target);
    }
    return targets;
}

// CONV-31b (A5, findings §F-2 R-leak fix): the live read Python actually
// performs (db.py 1289-1308 queries sqlite; it never consults the loaded
// document). A lease acquired after the caller's document snapshot loaded
// — exactly the lease guarding in-flight registration bytes — is invisible
// to the snapshot form above, so plan/sweep must use this one.
std::set<std::string> active_staging_targets_live(Database& database,
                                                  const std::string& cutoff_iso) {
    std::set<std::string> targets;
    if (!database.is_open()) return targets;
    if (!database.table_exists("staging_leases")) return targets;
    Statement statement = database.prepare(
        "SELECT DISTINCT target FROM staging_leases WHERE heartbeat_at > ?");
    if (!statement.is_valid()) return targets;
    statement.bind(1, cutoff_iso);
    while (statement.step()) {
        targets.insert(statement.text(0));
    }
    return targets;
}

std::set<std::string> active_staging_targets_live(
    const fs::path& project_path, const std::string& cutoff_iso) {
    auto opened = Database::open(
        pwb::project::catalog_sqlite_for(project_path),
        SqliteOpenMode::ReadOnly);
    if (!opened.is_ok()) {
        return {};  // missing/unreadable store: no leases (swallow parity)
    }
    return active_staging_targets_live(opened.value(), cutoff_iso);
}

std::string default_lease_cutoff() {
    const auto now = std::chrono::system_clock::now()
        - std::chrono::seconds(3600);  // db.py STAGING_LEASE_TTL_SECONDS
    const std::time_t time = std::chrono::system_clock::to_time_t(now);
    std::tm local{};
#if !defined(_WIN32)
    localtime_r(&time, &local);
#else
    localtime_s(&local, &time);
#endif
    char buffer[32];
    const std::size_t written =
        std::strftime(buffer, sizeof(buffer), "%Y-%m-%dT%H:%M:%S", &local);
    return std::string(buffer, written);
}

GcReport plan_gc(const GcContext& context, bool explicit_plan) {
    GcReport report;
    const CatalogDocument& document = *context.document;
    const fs::path dir = project_root(context);
    const fs::path stage_root = artifacts_root(context);
    static_assert(std::size(pwb::catalog::kStageDirs) == 4);
    const std::set<std::string> referenced = referenced_paths(document);
    // CONV-31b: live sqlite lease read (the document snapshot cannot see a
    // lease acquired after the caller loaded it — findings §F-2).
    const std::set<std::string> leased =
        active_staging_targets_live(context.project_path,
                                    default_lease_cutoff());

    auto classify_temp_and_empty = [&](GcReport& into) {
        for (const fs::path& path : walk_files(stage_root)) {
            if (!is_temp_name(path.filename().generic_string())) continue;
            bool skipped = false;
            for (const char* skip : kTempScanSkipRoots) {
                // working/ and trash/ are skipped wholesale for temp names:
                // a temp-named working copy is uncommitted user work and
                // trash is reachability-governed (#889).
                if (is_under(path, stage_root / skip)) {
                    skipped = true;
                    break;
                }
            }
            if (skipped) continue;
            const std::string rel = rel_or_empty(dir, path);
            if (referenced.count(rel) != 0) continue;  // #889: referenced wins
            if (is_leased(rel, leased)) continue;
            into.items.push_back(
                {kGcTempOrphan, rel, safe_size(path)});
        }
        for (const fs::path& directory : empty_dirs(stage_root)) {
            const std::string rel = rel_or_empty(dir, directory);
            if (is_leased(rel, leased)) continue;
            into.items.push_back({kGcEmptyDir, rel, 0});
        }
    };

    if (!explicit_plan) {
        classify_temp_and_empty(report);
        return report;
    }

    // 1. Stage payloads not referenced by any managed version path.
    for (const char* stage_name : kStageDirs) {
        for (const fs::path& path : walk_files(stage_root / stage_name)) {
            const std::string rel = rel_or_empty(dir, path);
            if (rel.empty()) continue;
            if (referenced.count(rel) != 0) continue;
            if (is_leased(rel, leased)) continue;
            report.items.push_back({kGcStageOrphan, rel, safe_size(path)});
        }
    }

    // 2. Abandoned working copies; 3. unreferenced trash payloads.
    const std::set<std::string> version_ids = known_version_ids(document);
    auto classify_first_segment = [&](const char* root_name, const char* kind) {
        const fs::path root = stage_root / root_name;
        std::error_code ec;
        if (!fs::is_directory(root, ec)) return;
        for (const fs::path& path : walk_files(root)) {
            const fs::path rel = fs::relative(path, root, ec);
            if (ec || rel.empty()) continue;
            const std::string first = rel.begin()->generic_string();
            if (version_ids.count(first) != 0) continue;
            report.items.push_back(
                {kind, rel_or_empty(dir, path), safe_size(path)});
        }
    };
    classify_first_segment("working", kGcWorkingOrphan);
    classify_first_segment("trash", kGcTrashOrphan);

    // 4. Stale temp files anywhere (working/ + trash/ skipped, referenced
    // payloads never classified); 6. empty dirs.
    classify_temp_and_empty(report);

    // 5. Unreferenced blobs (reachability GC on the content store).
    for (const std::string& digest :
         plan_blob_gc(context.project_path, document)) {
        const fs::path blob = blob_path_for(context.project_path, digest);
        const std::string rel = rel_or_empty(dir, blob);
        if (is_leased(rel, leased)) continue;
        report.items.push_back({kGcBlobOrphan, rel, safe_size(blob)});
    }
    return report;
}

GcReport sweep_gc(const GcContext& context, bool dry_run,
                  bool explicit_sweep, const GcReport* precomputed) {
    static const char* const kAutoSweepable[] = {kGcTempOrphan, kGcEmptyDir};
    static const char* const kExplicitSweepable[] = {
        kGcStageOrphan, kGcTempOrphan, kGcTrashOrphan, kGcBlobOrphan,
        kGcEmptyDir};
    const GcReport source =
        precomputed != nullptr ? *precomputed
                               : plan_gc(context, explicit_sweep);
    auto sweepable = [&](const std::string& kind) {
        if (explicit_sweep) {
            for (const char* k : kExplicitSweepable) {
                if (kind == k) return true;
            }
        } else {
            for (const char* k : kAutoSweepable) {
                if (kind == k) return true;
            }
        }
        return false;
    };

    GcReport candidates;
    for (const GcItem& item : source.items) {
        if (sweepable(item.kind)) candidates.items.push_back(item);
    }
    if (dry_run) return candidates;

    const fs::path dir = project_root(context);
    const CatalogDocument& document = *context.document;
    const std::set<std::string> referenced = referenced_paths(document);
    // CONV-31b: re-validation also uses the live lease read (db.py 1289-1308
    // parity; the snapshot form misses in-flight leases — findings §F-2).
    const std::set<std::string> leased =
        active_staging_targets_live(context.project_path,
                                    default_lease_cutoff());

    GcReport removed;
    for (const GcItem& item : candidates.items) {
        // Re-validate the point-in-time plan: registered or staged since the
        // plan → keep it.
        if (referenced.count(item.rel_path) != 0) continue;
        if (is_leased(item.rel_path, leased)) continue;
        const fs::path absolute = dir / pwb::project::path_from_u8(item.rel_path);
        std::error_code ec;
        if (!fs::remove(absolute, ec)) {
            // Read-only accident guard (Windows refuses to unlink; POSIX
            // ignores the bit): add +u+w and retry once, then stay
            // conservative (gc.py chmod(mode | S_IWUSR) parity).
            std::error_code retry_ec;
            fs::permissions(absolute, fs::perms::owner_write,
                            fs::perm_options::add, retry_ec);
            if (!fs::remove(absolute, retry_ec) || retry_ec) {
                continue;
            }
        }
        removed.items.push_back(item);
    }
    return removed;
}

GcReport cleanup_working_copies(const GcContext& context) {
    GcReport report;
    const CatalogDocument& document = *context.document;
    const std::set<std::string> version_ids = known_version_ids(document);
    const fs::path dir = project_root(context);
    const fs::path working_root =
        artifact_dir_for(context.project_path) / "working";
    std::error_code ec;
    if (!fs::is_directory(working_root, ec)) return report;
    for (const fs::path& path : walk_files(working_root)) {
        const fs::path rel = fs::relative(path, working_root, ec);
        if (ec || rel.empty()) continue;
        const std::string first = rel.begin()->generic_string();
        if (version_ids.count(first) != 0) continue;
        if (!fs::remove(path, ec) || ec) continue;
        report.items.push_back({kGcWorkingOrphan, rel_or_empty(dir, path), 0});
    }
    // Prune now-empty working subdirs (deepest first).
    for (const fs::path& directory : empty_dirs_below(working_root)) {
        std::error_code rm_ec;
        fs::remove(directory, rm_ec);  // rmdir semantics: fails if non-empty
    }
    return report;
}

}  // namespace pwb::catalog
