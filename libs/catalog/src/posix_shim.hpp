// Cross-platform stat/localtime/chmod shim — PRIVATE to libs/catalog/src
// (same visibility class as row_mapping.hpp).
//
// The catalog library's frozen behavior was verified on POSIX (g++ direct;
// 01-ledger A12). Windows/MSVC has no gmtime_r/localtime_r, no wchar_t
// overload of ::stat, no st_mtim and no ::chmod — this shim keeps the
// POSIX path BYTE-IDENTICAL (#ifdef-free on Linux) and maps the Windows
// path to the closest semantics:
//   * stat → _wstat64 (readonly-attribute files still stat as regular);
//   * st_mtim ns → st_mtime seconds × 1e9 (the B-16 100 ns tick note
//     direction; second-granular, best-effort);
//   * mtime_ns_frac (st_mtim.tv_nsec alone — the stat_fingerprint
//     comparison field) → 0 on Windows (no sub-second field exists);
//   * chmod read-only/write → std::filesystem::permissions owner bits.
#pragma once

#include <atomic>
#include <cstdint>
#include <cstdio>
#include <ctime>
#include <filesystem>
#include <random>
#include <sys/stat.h>

namespace pwb::catalog::posix_shim {

struct FileStat {
    bool exists = false;
    bool is_regular = false;
    std::int64_t mtime_ns = 0;      // full nanosecond ticks (POSIX st_mtim)
    std::int64_t mtime_ns_frac = 0; // st_mtim.tv_nsec alone (fingerprint)
    std::uintmax_t size = 0;
};

inline FileStat stat_path(const std::filesystem::path& path) {
    FileStat out;
#if defined(_WIN32)
    struct _stat64 st {};
    if (_wstat64(path.c_str(), &st) != 0) return out;
    out.exists = true;
    out.is_regular = (st.st_mode & _S_IFMT) == _S_IFREG;
    out.mtime_ns = static_cast<std::int64_t>(st.st_mtime) * 1000000000LL;
    out.size = static_cast<std::uintmax_t>(st.st_size);
#else
    struct ::stat st {};
    if (::stat(path.c_str(), &st) != 0) return out;
    out.exists = true;
    out.is_regular = S_ISREG(st.st_mode);
    out.mtime_ns = static_cast<std::int64_t>(st.st_mtim.tv_sec) *
                       1000000000LL +
                   static_cast<std::int64_t>(st.st_mtim.tv_nsec);
    out.mtime_ns_frac = static_cast<std::int64_t>(st.st_mtim.tv_nsec);
    out.size = static_cast<std::uintmax_t>(st.st_size);
#endif
    return out;
}

inline void localtime_compat(std::time_t time, std::tm* out) {
#if defined(_WIN32)
    localtime_s(out, &time);
#else
    localtime_r(&time, out);
#endif
}

inline void gmtime_compat(std::time_t time, std::tm* out) {
#if defined(_WIN32)
    gmtime_s(out, &time);
#else
    gmtime_r(&time, out);
#endif
}

// trash.cpp make_readonly_best_effort / make_writable_best_effort —
// best-effort permission flips that never fail loudly.
inline void make_readonly_best_effort(const std::filesystem::path& path) {
    std::error_code ec;
    std::filesystem::permissions(path, std::filesystem::perms::owner_write,
                                 std::filesystem::perm_options::remove, ec);
}

inline void make_writable_best_effort(const std::filesystem::path& path) {
    std::error_code ec;
    std::filesystem::permissions(path, std::filesystem::perms::owner_write,
                                 std::filesystem::perm_options::add, ec);
}
// timegm — UTC inverse of mktime (MSVC: _mkgmtime).
inline std::time_t timegm_compat(std::tm* tm) {
#if defined(_WIN32)
    return _mkgmtime(tm);
#else
    return ::timegm(tm);
#endif
}

// strptime for the ONE format the catalog uses ("%Y-%m-%dT%H:%M:%S" —
// prefix parse, fractions/offsets beyond seconds ignored). sscanf keeps
// the same prefix semantics for well-formed ISO stamps.
inline bool strptime_iso_prefix(const char* text, std::tm* tm) {
#if defined(_WIN32)
    int year = 0, month = 0, day = 0, hour = 0, minute = 0, second = 0;
    if (std::sscanf(text, "%4d-%2d-%2dT%2d:%2d:%2d", &year, &month, &day,
                    &hour, &minute, &second) != 6) {
        return false;
    }
    tm->tm_year = year - 1900;
    tm->tm_mon = month - 1;
    tm->tm_mday = day;
    tm->tm_hour = hour;
    tm->tm_min = minute;
    tm->tm_sec = second;
    return true;
#else
    return ::strptime(text, "%Y-%m-%dT%H:%M:%S", tm) != nullptr;
#endif
}

// Unique temp file path in `directory` (mkstemp-name shape); the caller
// owns creation. Windows has no mkstemp — random hex suffix, same shape.
inline std::filesystem::path temp_file_path(
    const std::filesystem::path& directory, const char* prefix) {
    static std::atomic<std::uint64_t> counter{0};
    std::random_device rd;
    const std::uint64_t salt =
        (static_cast<std::uint64_t>(rd()) << 32) ^ rd() ^ counter.fetch_add(1);
    char suffix[32];
    std::snprintf(suffix, sizeof(suffix), "%016llx",
                  static_cast<unsigned long long>(salt));
    return directory / (std::string(prefix) + suffix);
}

}  // namespace pwb::catalog::posix_shim
