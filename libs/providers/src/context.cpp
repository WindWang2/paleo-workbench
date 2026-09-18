#include <pwb/providers/context.hpp>

#include <pwb/providers/errors.hpp>

#include <cstdlib>
#include <filesystem>  // NOLINT(misc-include-cleaner): path containment
#include <string>

namespace pwb::providers {

namespace {

// Python Path.expanduser() for the leading "~" form ("~user" is not
// supported — no passwd database in scope).
std::string expanduser(std::string value) {
    if (value.rfind("~/", 0) == 0 || value == "~") {
        if (const char* home = std::getenv("HOME")) {
            return std::string(home) + value.substr(1);
        }
    }
    return value;
}

std::filesystem::path normalized(const std::filesystem::path& p) {
    // weakly_canonical resolves the existing prefix (symlinks included) and
    // normalizes the rest — the Python Path.resolve(strict=False) semantics
    // this port needs.
    std::error_code ec;
    auto canonical = std::filesystem::weakly_canonical(p, ec);
    if (ec) return std::filesystem::absolute(p).lexically_normal();
    return canonical;
}

// Python resolved.relative_to(root) — component-wise prefix containment.
bool is_under(const std::filesystem::path& resolved, const std::filesystem::path& root) {
    const std::string r = root.generic_string();
    const std::string v = resolved.generic_string();
    if (r.empty()) return false;
    if (v == r) return true;
    if (v.size() > r.size() && v.compare(0, r.size(), r) == 0 &&
        (r.back() == '/' || v[r.size()] == '/')) {
        return true;
    }
    return false;
}

}  // namespace

std::filesystem::path resolve_contained_output(const ProviderContext& context,
                                               const std::string& raw,
                                               const std::string& provider_id) {
    const std::string root_raw = !context.workspace_root.empty()
                                     ? context.workspace_root
                                     : context.work_dir;
    if (root_raw.empty()) {
        throw ProviderExecutionError(
            provider_id, "ValueError",
            "no workspace_root/work_dir in the execution context; refusing "
            "to write an output path that cannot be containment-checked");
    }
    const std::filesystem::path root = normalized(expanduser(root_raw));
    std::filesystem::path candidate = expanduser(raw);
    std::filesystem::path resolved =
        candidate.is_absolute() ? normalized(candidate) : normalized(root / candidate);
    // Containment AFTER resolution: relative traversal ("../..") must not
    // escape the workspace either.
    if (!is_under(resolved, root)) {
        throw ProviderExecutionError(
            provider_id, "PermissionError",
            "output path '" + raw + "' resolves outside the execution workspace (" +
                root.generic_string() + ")");
    }
    if (std::filesystem::exists(resolved)) {
        throw ProviderExecutionError(
            provider_id, "FileExistsError",
            "refusing to overwrite existing file " + resolved.generic_string());
    }
    return resolved;
}

}  // namespace pwb::providers
