// Small shared helpers for the conv-26 data_suite TUs (internal).
#pragma once

#include <algorithm>
#include <filesystem>
#include <string>

namespace pwb::data::util {

namespace fs = std::filesystem;

inline std::string lower_ascii(std::string text) {
    for (char& c : text) {
        if (c >= 'A' && c <= 'Z') c = static_cast<char>(c - 'A' + 'a');
    }
    return text;
}

// Path.suffix.lower() — extension WITH dot, "" when none.
inline std::string path_suffix(const fs::path& path) {
    return lower_ascii(path.extension().string());
}

// resolve().as_posix() parity: symlink-aware where the path exists, lexical
// normalization otherwise; "" when even lexicalization fails.
inline std::string resolved_posix(const fs::path& path) {
    std::error_code ec;
    fs::path canonical = fs::weakly_canonical(path, ec);
    if (ec || canonical.empty()) {
        canonical = fs::absolute(path, ec);
        if (ec) return "";
        canonical = canonical.lexically_normal();
    }
    return canonical.generic_string();
}

}  // namespace pwb::data::util
