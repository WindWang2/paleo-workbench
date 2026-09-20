#include "pwb/interchange/atomic_file.hpp"

#if !defined(_WIN32)
#include <fcntl.h>
#include <unistd.h>
#endif

#include <cerrno>
#include <mutex>
#include <random>
#include <stdexcept>
#include <string>
#include <system_error>

#if defined(_WIN32)
#include <windows.h>
#include <fcntl.h>
#include <io.h>
#include <share.h>
#endif

namespace pwb::interchange {
namespace {

void fsync_directory(const std::filesystem::path& dir) {
#if defined(_WIN32)
    (void)dir;  // no directory-handle fsync on Windows; the POSIX os.fsync
                // path in Python is best-effort too (OSError swallowed).
#else
    // Python fsyncs str(target.parent) — "" for a bare filename means ".".
    const std::filesystem::path effective = dir.empty()
        ? std::filesystem::path(".")
        : dir;
    const int fd = ::open(effective.c_str(), O_RDONLY);
    if (fd < 0) return;
    ::fsync(fd);  // best-effort, mirrors the swallowed OSError in Python
    ::close(fd);
#endif
}

std::string errno_message() {
    return std::error_code(errno, std::generic_category()).message();
}

// tempfile.mkstemp suffix pool: "abcdefghijklmnopqrstuvwxyz0123456789_".
char random_suffix_char() {
    static constexpr char kPool[] = "abcdefghijklmnopqrstuvwxyz0123456789_";
    static std::mutex mutex;
    static std::mt19937 engine(std::random_device{}());
    std::lock_guard<std::mutex> lock(mutex);
    return kPool[engine() % (sizeof(kPool) - 1)];
}

}  // namespace

void os_replace_atomic(const std::filesystem::path& temp_path,
                       const std::filesystem::path& target_path) {
#if defined(_WIN32)
    // Windows filter-driver lock: a freshly-written tree can transiently
    // fail to rename (PermissionError / WinError 5) because a scanner holds
    // handles inside it. Retry with the Python policy's exact backoff.
    std::string last;
    for (int attempt = 0; attempt < 10; ++attempt) {
        if (MoveFileExW(temp_path.c_str(), target_path.c_str(),
                        MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) {
            last.clear();
            break;
        }
        last = "WinError " + std::to_string(GetLastError());
        const int shift = attempt < 6 ? attempt : 6;
        Sleep(static_cast<DWORD>(0.05 * (1 << shift) * 1000.0));
    }
    if (!last.empty()) {
        throw std::runtime_error("atomic replace of " + target_path.string() +
                                 " kept failing after retries: " + last);
    }
#else
    // POSIX: single rename; a transient failure here is a real error.
    if (::rename(temp_path.c_str(), target_path.c_str()) != 0) {
        throw std::runtime_error("atomic replace of " + target_path.string() +
                                 " failed: " + errno_message());
    }
#endif
    fsync_directory(target_path.parent_path());
}

AtomicOutputFile::AtomicOutputFile(const std::filesystem::path& target)
    : target_path_(target) {
    const std::filesystem::path parent = target.parent_path();
    const std::string prefix = "." + target.filename().string() + ".";
    // Python keeps the target suffix so extension-based format inference
    // (e.g. pandas to_excel) still works on the temp path.
    std::string suffix = target.extension().string();

    for (int attempt = 0; attempt < 64; ++attempt) {
        std::string rand_chars;
        for (int i = 0; i < 8; ++i) rand_chars.push_back(random_suffix_char());
        if (!suffix.empty() && suffix[0] != '.') suffix = "." + suffix;
        const std::string candidate =
            (parent / (prefix + rand_chars + suffix)).string();
#if defined(_WIN32)
        // MSVC has no open()/O_EXCL; _wopen with _O_CREAT|_O_EXCL|_O_WRONLY
        // gives the same create-or-fail reservation (mode 0600 → _S_IWRITE).
        const int fd = _wopen(
            std::filesystem::path(candidate).c_str(),
            _O_CREAT | _O_EXCL | _O_WRONLY, _S_IWRITE);
#else
        const int fd = ::open(candidate.c_str(), O_CREAT | O_EXCL | O_WRONLY, 0600);
#endif
        if (fd >= 0) {
#if defined(_WIN32)
            _close(fd);
#else
            ::close(fd);
#endif
            temp_path_ = candidate;
            return;
        }
#if defined(_WIN32)
        if (errno != EEXIST) {
#else
        if (errno != EEXIST) {
#endif
            throw std::runtime_error("cannot create temp file beside " +
                                     target.string() + ": " + errno_message());
        }
    }
    throw std::runtime_error("cannot create temp file beside " + target.string() +
                             ": no free temp name");
}

void AtomicOutputFile::commit() {
    if (committed_) return;
    os_replace_atomic(temp_path_, target_path_);
    committed_ = true;
}

AtomicOutputFile::~AtomicOutputFile() {
    if (committed_) return;
    std::error_code ec;
    std::filesystem::remove(temp_path_, ec);  // best-effort cleanup
}

}  // namespace pwb::interchange
