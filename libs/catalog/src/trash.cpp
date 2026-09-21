#include "posix_shim.hpp"
#include "pwb/catalog/trash.hpp"

#include "pwb/catalog/models.hpp"
#include "pwb/domain/errors.hpp"
#include "pwb/project/paths.hpp"

#include <cstdio>
#if !defined(_WIN32)
#include <fcntl.h>
#endif
#include <fstream>
#include <sys/stat.h>
#if !defined(_WIN32)
#include <unistd.h>
#endif
#include <vector>

namespace pwb::catalog {

namespace {

using domain::DataError;
using domain::ErrorCode;

fs::path project_dir(const fs::path& project_path) {
    return pwb::project::project_dir_for(project_path);
}

fs::path artifacts_root(const fs::path& project_path) {
    // ensure_catalog_layout: the tree exists lazily; mkdir -p semantics.
    fs::path root = pwb::project::artifact_dir_for(project_path);
    std::error_code ec;
    fs::create_directories(root, ec);
    return root;
}

void fsync_dir_best_effort(const fs::path& directory) {
#if !defined(_WIN32)
    int fd = ::open(directory.c_str(), O_RDONLY | O_DIRECTORY);
    if (fd < 0) return;
    ::fsync(fd);
    ::close(fd);
#else
    // storage.py returns early on Windows (B-31); no directory-fsync
    // equivalent exists there.
    (void)directory;
#endif
}

void make_readonly_best_effort(const fs::path& path) {
    posix_shim::make_readonly_best_effort(path);
}

void make_writable_best_effort(const fs::path& path) {
    posix_shim::make_writable_best_effort(path);
}

void prune_empty_ancestors(const fs::path& directory, int levels) {
    fs::path target = directory;
    std::error_code ec;
    for (int i = 0; i < levels; ++i) {
        if (!fs::is_empty(target)) return;
        fs::path parent = target.parent_path();
        fs::remove(target, ec);
        if (ec) return;
        target = parent;
    }
}

// storage.py is_safe_entity_id — same bounded implementation contract as
// dedup.cpp (ASCII rules verbatim; non-ASCII UTF-8 accepted as a declared
// superset, 15-decisions.md D14).
bool safe_entity_id(const std::string& id) {
    if (id.empty() || id[0] == '.') return false;
    if (id.find("..") != std::string::npos) return false;
    std::size_t i = 0;
    while (i < id.size()) {
        const unsigned char c = static_cast<unsigned char>(id[i]);
        const bool ascii_ok = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
                              (c >= '0' && c <= '9') || c == '.' || c == '_' ||
                              c == '-';
        if (ascii_ok) {
            ++i;
            continue;
        }
        if (c < 0x80) return false;
        std::size_t length = 1;
        if ((c & 0xE0) == 0xC0) length = 2;
        else if ((c & 0xF0) == 0xE0) length = 3;
        else if ((c & 0xF8) == 0xF0) length = 4;
        else return false;
        if (i + length > id.size()) return false;
        i += length;
    }
    return true;
}

std::string relpath_for(const fs::path& project_path, const fs::path& absolute) {
    // Python relative_to(project_dir); callers pass payloads under it.
    const std::string abs = fs::weakly_canonical(absolute).string();
    const std::string base = project_dir(project_path).string();
    if (abs.rfind(base + "/", 0) == 0) return abs.substr(base.size() + 1);
    return absolute.filename().string();
}

}  // namespace

// ---- free helpers (public) ---------------------------------------------------

std::string stage_dir_name(domain::DataStage stage) {
    switch (stage) {
        case domain::DataStage::Raw: return "raw";
        case domain::DataStage::Derived: return "derived";
        case domain::DataStage::Intermediate: return "intermediate";
        case domain::DataStage::Output: return "outputs";
    }
    return "intermediate";
}

fs::path working_dir_for(const fs::path& project_path) {
    return pwb::project::artifact_dir_for(project_path) / "working";
}

fs::path trash_dir_for(const fs::path& project_path) {
    return pwb::project::artifact_dir_for(project_path) / "trash";
}

bool is_safe_entity_id(const std::string& entity_id) {
    return safe_entity_id(entity_id);
}

bool is_cas_path(const fs::path& project_path, const std::string& rel_path) {
    fs::path candidate(rel_path);
    if (!candidate.is_absolute()) candidate = project_dir(project_path) / candidate;
    std::error_code ec;
    const fs::path blobs = fs::weakly_canonical(
        pwb::project::artifact_dir_for(project_path) / "blobs", ec);
    const fs::path resolved = fs::weakly_canonical(candidate, ec);
    const std::string blobs_text = blobs.string();
    const std::string resolved_text = resolved.string();
    return resolved_text.rfind(blobs_text + "/", 0) == 0;
}

domain::Result<std::string> trash_payload(const fs::path& project_path,
                                           const fs::path& version_path,
                                           const std::string& version_id) {
    if (!safe_entity_id(version_id)) {
        return DataError(ErrorCode::UnsafeId,
                         "Unsafe version id '" + version_id +
                             "': only [A-Za-z0-9._-] allowed");
    }
    if (is_cas_path(project_path, relpath_for(project_path, version_path))) {
        return relpath_for(project_path, version_path);
    }
    std::error_code ec;
    const bool is_dir = fs::is_directory(version_path, ec);
    if (!is_dir && !fs::is_regular_file(version_path, ec)) {
        return DataError(ErrorCode::NotFound,
                         "Managed payload not found: " + version_path.string());
    }
    const fs::path trash_dir = artifacts_root(project_path) / "trash" / version_id;
    fs::create_directories(trash_dir, ec);
    const fs::path target = trash_dir / version_path.filename();
    fs::rename(version_path, target, ec);
    if (ec) {
        return DataError(ErrorCode::IoError,
                         "trash move failed: " + ec.message());
    }
    fsync_dir_best_effort(trash_dir);
    fsync_dir_best_effort(version_path.parent_path());
    prune_empty_ancestors(version_path.parent_path(), 2);
    return relpath_for(project_path, target);
}

domain::Result<std::string> restore_payload(const fs::path& project_path,
                                             const fs::path& version_path,
                                             const std::string& original_rel_path) {
    if (is_cas_path(project_path, relpath_for(project_path, version_path))) {
        return relpath_for(project_path, version_path);
    }
    std::error_code ec;
    const bool is_dir = fs::is_directory(version_path, ec);
    if (!is_dir && !fs::is_regular_file(version_path, ec)) {
        return DataError(ErrorCode::NotFound,
                         "Trashed payload not found: " + version_path.string());
    }
    const fs::path target = project_dir(project_path) / original_rel_path;
    if (fs::exists(target, ec)) {
        return DataError(ErrorCode::ConflictBaseVersion,
                         "Restore target already exists: " + target.string());
    }
    fs::create_directories(target.parent_path(), ec);
    fs::rename(version_path, target, ec);
    if (ec) {
        return DataError(ErrorCode::IoError, "restore move failed: " + ec.message());
    }
    if (!is_dir) make_readonly_best_effort(target);
    fsync_dir_best_effort(target.parent_path());
    prune_empty_ancestors(version_path.parent_path(), 1);
    return relpath_for(project_path, target);
}

void purge_trashed_payload(const fs::path& project_path,
                           const fs::path& version_path, bool shared) {
    std::error_code ec;
    if (fs::is_directory(version_path, ec)) {
        // Directory-backed derived store: purge removes the whole tree.
        fs::remove_all(version_path, ec);
        prune_empty_ancestors(version_path.parent_path(), 1);
        return;
    }
    // The shared flag only guards blob-backed payloads (refcount).
    if (shared && is_cas_path(project_path, relpath_for(project_path, version_path))) {
        return;  // the version record is the only thing being purged
    }
    if (fs::remove(version_path, ec)) {
        fsync_dir_best_effort(version_path.parent_path());
        prune_empty_ancestors(version_path.parent_path(), 1);
    }
}

domain::Result<fs::path> create_working_copy(const fs::path& project_path,
                                              const fs::path& version_path,
                                              const std::string& version_id) {
    if (!safe_entity_id(version_id)) {
        return DataError(ErrorCode::UnsafeId,
                         "Unsafe version id '" + version_id +
                             "': only [A-Za-z0-9._-] allowed");
    }
    std::error_code ec;
    const fs::path target_dir = working_dir_for(project_path) / version_id;
    fs::create_directories(target_dir, ec);
    if (ec) {
        return DataError(ErrorCode::IoError, ec.message());
    }
    const fs::path target = target_dir / version_path.filename();

    // #1219-style unique temp per writer under the target dir - portable
    // staged write (temp + rename). POSIX additionally fsyncs the payload
    // before the rename (crash-safety parity with the mkstemp original);
    // Windows has no mkstemp/fsync equivalent (storage.py B-31 note).
    fs::path temp = posix_shim::temp_file_path(target_dir, ".work-");
    do {
        std::ofstream out(temp, std::ios::binary | std::ios::trunc);
        if (!out) {
            fs::remove(temp, ec);
            return DataError(ErrorCode::IoError,
                             "working-copy temp create failed");
        }
        std::ifstream in(version_path, std::ios::binary);
        if (!in) {
            fs::remove(temp, ec);
            return DataError(ErrorCode::NotFound,
                             "Managed payload not found: " + version_path.string());
        }
        char chunk[1 << 20];
        while (in) {
            in.read(chunk, sizeof(chunk));
            if (in.gcount() > 0) {
                out.write(chunk, in.gcount());
            }
        }
        out.flush();
        if (!out) {
            fs::remove(temp, ec);
            return DataError(ErrorCode::IoError, "working-copy write failed");
        }
#if !defined(_WIN32)
        out.close();
        const int fd = ::open(temp.c_str(), O_RDONLY);
        if (fd >= 0) {
            const int synced = ::fsync(fd);
            ::close(fd);
            if (synced != 0) {
                fs::remove(temp, ec);
                return DataError(ErrorCode::IoError,
                                 "working-copy fsync failed");
            }
        }
#endif
    } while (false);

    make_writable_best_effort(target);  // replace over a stale read-only copy
    fs::rename(temp, target, ec);
    if (ec) {
        fs::remove(temp, ec);
        return DataError(ErrorCode::IoError, "working-copy rename failed");
    }
    make_writable_best_effort(target);
    fsync_dir_best_effort(target_dir);
    return target;
}

}  // namespace pwb::catalog
