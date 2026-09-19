#pragma once

// pwb::interchange — cross-platform atomic file publication (conv-14b):
// path_safety.os_replace_atomic (os.replace + parent-dir fsync + Windows
// filter-driver retry) and the resources/exporters.atomic_output context
// manager semantics as an RAII guard.

#include <filesystem>

namespace pwb::interchange {

// os.replace(temp, target) so the rename survives power loss (parent-dir
// fsync; the fsync itself is best-effort — OSError there is swallowed, as in
// Python). Windows: renaming a freshly-written tree can transiently fail
// with a permission error because a filter driver (Defender scanning the new
// files) briefly holds handles inside it — retry with exponential backoff
// (10 attempts, 0.05 * 2**min(attempt, 6) seconds) before giving up; POSIX
// rename tolerates open handles and runs once. Final failure raises
// std::runtime_error("atomic replace of <target> kept failing after
// retries: <reason>") on Windows / the filesystem error on POSIX.
void os_replace_atomic(const std::filesystem::path& temp_path,
                       const std::filesystem::path& target_path);

// resources/exporters.atomic_output as RAII: creates a temp file beside
// *target* (".<name>.<8 random chars><suffix>", O_EXCL, 0600 — mkstemp
// semantics), hands out its path, and atomically replaces the target on
// commit(); the temp is unlinked on destruction without commit, so a failed
// export never leaves a corrupt partial file at the user-visible
// destination. The temp keeps the target suffix so extension-based format
// inference still works.
class AtomicOutputFile {
public:
    explicit AtomicOutputFile(const std::filesystem::path& target);
    ~AtomicOutputFile();
    AtomicOutputFile(const AtomicOutputFile&) = delete;
    AtomicOutputFile& operator=(const AtomicOutputFile&) = delete;

    const std::filesystem::path& temp_path() const { return temp_path_; }
    const std::filesystem::path& target_path() const { return target_path_; }

    // os_replace_atomic(temp, target); idempotent.
    void commit();

private:
    std::filesystem::path target_path_;
    std::filesystem::path temp_path_;
    bool committed_ = false;
};

}  // namespace pwb::interchange
