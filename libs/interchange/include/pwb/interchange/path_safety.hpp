#pragma once

// pwb::interchange — path-safety primitives, a faithful C++ port of
// paleo_workbench/interchange/path_safety.py (conv-14). Fail-closed: every
// check rejects with UnsafePathError carrying the exact Python message
// (Python str.repr semantics included), never sanitizes silently.
//
// Not ported in this slice (see ledgers/14-decisions.md D14-2):
// safe_members/extract_archive (zip container), os_replace_atomic (Windows
// filter-driver retry policy). Qt-free, Python-free.

#include <filesystem>
#include <set>
#include <string>
#include <string_view>

namespace pwb::interchange {

class UnsafePathError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

inline constexpr std::size_t kMaxComponentLen = 200;
inline constexpr std::size_t kMaxRelativeLen = 900;

// Python repr(str) for error-message fidelity (bounded: covers ASCII
// controls, DEL, quotes and backslash; other code points pass through —
// same range the oracle freezes).
std::string python_repr(std::string_view text);

// Validate a package-relative POSIX path; returns the canonical relative
// path (PurePosixPath semantics: "." components dropped, duplicate and
// trailing slashes collapsed, ".." kept for the traversal check).
// Throws UnsafePathError with the Python message on any unsafe input.
std::string safe_relative_path(const std::string& name,
                               const std::string& what = "entry");

// Track a validated name; raises on NFC-duplicate or case-insensitive clash.
// Mirrors the Python signature: both sets are updated in place.
void check_collision(const std::string& name,
                     std::set<std::string>& seen_casefold,
                     std::set<std::string>& seen_nfc);

// Resolve candidate under root; fail-closed on symlink or escape.
// Throws UnsafePathError ("symlink rejected: ..." / "path escapes package
// root: ...") and returns the resolved path otherwise.
std::filesystem::path ensure_within_root(const std::filesystem::path& root,
                                         const std::filesystem::path& candidate);

// Make an arbitrary string safe as a single file name (NFC rewrite included).
std::string sanitize_filename(const std::string& stem,
                              const std::string& fallback = "export");

bool is_reserved_or_unsafe(const std::string& name);

}  // namespace pwb::interchange
