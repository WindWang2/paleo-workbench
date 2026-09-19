#include "pwb/ingest/project_path.hpp"

namespace pwb::ingest {

namespace {

std::filesystem::path project_dir_for(const std::filesystem::path& project_path) {
    return std::filesystem::weakly_canonical(
        std::filesystem::path(project_path).parent_path());
}

// Python `resolved.relative_to(base)` succeeding: resolved == base yields
// Path('.') and SUCCEEDS; escaping shows up as a leading '..' component.
bool lexically_within(const std::filesystem::path& resolved,
                      const std::filesystem::path& base) {
    auto rel = resolved.lexically_relative(base);
    if (rel.empty()) return false;
    for (const auto& part : rel) {
        if (part == "..") return false;
    }
    return true;
}

}  // namespace

std::optional<StatResult> safe_file_stat(const std::filesystem::path& path) {
    std::error_code ec;
    auto st = std::filesystem::status(path, ec);
    if (ec || !std::filesystem::is_regular_file(st)) return std::nullopt;
    // std::filesystem has no nanosecond mtime; the oracle only freezes the
    // size component (decision D13).
    auto sz = std::filesystem::file_size(path, ec);
    if (ec) return std::nullopt;
    return StatResult{static_cast<long long>(sz), 0};
}

bool is_within_directory(const std::filesystem::path& path,
                         const std::filesystem::path& directory) {
    std::error_code ec;
    auto resolved = std::filesystem::weakly_canonical(path, ec);
    if (ec) return false;
    auto base = std::filesystem::weakly_canonical(directory, ec);
    if (ec) return false;
    return lexically_within(resolved, base);
}

Relativized relativize_path(const std::string& path,
                            const std::filesystem::path& project_path) {
    auto project_dir = project_dir_for(project_path);
    std::filesystem::path candidate(path);
    std::error_code ec;
    std::filesystem::path resolved;
    if (candidate.is_absolute()) {
        resolved = std::filesystem::weakly_canonical(candidate, ec);
        if (ec) resolved = candidate;
    } else {
        resolved = std::filesystem::weakly_canonical(project_dir / candidate, ec);
        if (ec) resolved = project_dir / candidate;
    }
    auto rel = resolved.lexically_relative(project_dir);
    Relativized out;
    if (!lexically_within(resolved, project_dir)) {
        out.path = resolved.generic_string();
        out.external = true;
        return out;
    }
    // generic_string() (not native(): wchar_t on Windows) so the "." literal
    // comparison is well-formed on both platforms.
    const std::string rel_text = rel.generic_string();
    out.path = (rel_text == "." ? std::string(".") : rel_text);
    out.external = false;
    return out;
}

std::string resolve_project_path(const std::string& path,
                                 const std::filesystem::path& project_path) {
    std::string raw = path;
    // str.strip()
    size_t b = 0, e = raw.size();
    while (b < e && (raw[b] == ' ' || raw[b] == '\t' || raw[b] == '\n' ||
                     raw[b] == '\r')) {
        ++b;
    }
    while (e > b && (raw[e - 1] == ' ' || raw[e - 1] == '\t' ||
                     raw[e - 1] == '\n' || raw[e - 1] == '\r')) {
        --e;
    }
    raw = raw.substr(b, e - b);
    if (raw.empty()) {
        throw ProjectPathError("Empty path cannot be resolved against a project");
    }
    std::filesystem::path candidate(raw);
    auto project_dir = project_dir_for(project_path);
    if (candidate.is_absolute()) {
        std::error_code ec;
        auto resolved = std::filesystem::weakly_canonical(candidate, ec);
        return (ec ? candidate : resolved).generic_string();
    }
    std::error_code ec;
    auto resolved = std::filesystem::weakly_canonical(project_dir / candidate, ec);
    if (ec) resolved = project_dir / candidate;
    if (!lexically_within(resolved, project_dir)) {
        throw ProjectPathError("Relative path escapes project directory: '" +
                               raw + "'");
    }
    return resolved.generic_string();
}

std::string resolve_asset_path(const std::string& path,
                               const std::filesystem::path& project_root) {
    namespace fs = std::filesystem;
    fs::path candidate(path);
    std::error_code ec;
    // expanduser: a bare "~" prefix maps to the user home (POSIX layout).
    // Compare on the generic (UTF-8) form: path::native() is wchar_t on
    // Windows, where the narrow literals would not compile.
    const std::string candidate_text = candidate.generic_string();
    if (candidate_text == "~") {
        const char* home = std::getenv("HOME");
        if (home) candidate = fs::path(home);
    } else if (candidate_text.rfind("~/", 0) == 0) {
        const char* home = std::getenv("HOME");
        if (home) candidate = fs::path(home) / candidate_text.substr(2);
    }
    if (fs::is_regular_file(candidate, ec)) {
        auto resolved = fs::weakly_canonical(candidate, ec);
        return (ec ? candidate : resolved).generic_string();
    }
    if (candidate.is_absolute()) {
        return candidate.generic_string();
    }
    std::string root = project_root.generic_string();
    // strip
    size_t b = 0, e = root.size();
    while (b < e && (root[b] == ' ' || root[b] == '\t')) ++b;
    while (e > b && (root[e - 1] == ' ' || root[e - 1] == '\t')) --e;
    root = root.substr(b, e - b);
    if (root.empty() || root == "." || root == "..") {
        return candidate.generic_string();
    }
    auto root_path = fs::weakly_canonical(fs::path(root), ec);
    if (ec) root_path = fs::path(root);
    auto joined = fs::weakly_canonical(root_path / candidate, ec);
    if (ec) joined = root_path / candidate;
    if (!is_within_directory(joined, root_path)) {
        // Escape attempt — do not open files outside the project root.
        return candidate.generic_string();
    }
    return joined.generic_string();
}

}  // namespace pwb::ingest
