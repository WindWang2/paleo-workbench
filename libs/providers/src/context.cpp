#include <pwb/providers/context.hpp>

#include <pwb/providers/errors.hpp>

#include <cstdlib>
#include <filesystem>  // NOLINT(misc-include-cleaner): path containment
#include <memory>
#include <mutex>
#include <string>

namespace pwb::providers {

namespace {
std::mutex& sink_mutex() {
    static std::mutex mutex;
    return mutex;
}
std::shared_ptr<const LogSink>& sink_slot() {
    static std::shared_ptr<const LogSink> slot = std::make_shared<const LogSink>();
    return slot;
}
}  // namespace

void set_log_sink(LogSink sink) {
    std::lock_guard<std::mutex> lock(sink_mutex());
    sink_slot() = std::make_shared<const LogSink>(std::move(sink));
}

void log_event(const char* level, const std::string& message) {
    std::shared_ptr<const LogSink> sink;
    {
        std::lock_guard<std::mutex> lock(sink_mutex());
        sink = sink_slot();
    }
    if (sink && *sink) (*sink)(level, message);
}

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

std::filesystem::path normalized(const std::filesystem::path& p,
                                 const std::string& provider_id) {
    // weakly_canonical resolves the existing prefix (symlinks included) and
    // normalizes the rest — the Python Path.resolve(strict=False) semantics
    // this port needs. A resolution failure fails CLOSED: a security check
    // must not degrade to lexical normalization.
    std::error_code ec;
    auto canonical = std::filesystem::weakly_canonical(p, ec);
    if (ec) {
        throw ProviderExecutionError(
            provider_id, "ValueError",
            "cannot resolve output path '" + p.generic_string() + "': " + ec.message());
    }
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
    const std::filesystem::path root = normalized(expanduser(root_raw), provider_id);
    std::filesystem::path candidate = expanduser(raw);
    std::filesystem::path resolved =
        candidate.is_absolute() ? normalized(candidate, provider_id)
                                : normalized(root / candidate, provider_id);
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
