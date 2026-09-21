#include "posix_shim.hpp"
#include "pwb/catalog/telemetry.hpp"

#include "pwb/project/paths.hpp"

#include <cstdio>
#include <ctime>
#include <fstream>
#include <mutex>

namespace pwb::catalog {

namespace {

// json.dumps(payload, ensure_ascii=False, sort_keys=True): nlohmann::json
// iterates object keys in lexicographic order, matching sort_keys; the
// separators are Python's defaults (", " / ": ").
std::string py_dumps_sorted(const domain::Json& value) {
    // dump() gives compact separators; re-render with Python spacing.
    std::string compact = nlohmann::json(value).dump();
    std::string out;
    bool in_string = false;
    bool escape = false;
    for (char c : compact) {
        if (escape) {
            escape = false;
            out.push_back(c);
            continue;
        }
        if (c == '\\' && in_string) {
            escape = true;
            out.push_back(c);
            continue;
        }
        if (c == '"') in_string = !in_string;
        if (!in_string && (c == ',' || c == ':')) {
            out.push_back(c);
            out.push_back(' ');
            continue;
        }
        out.push_back(c);
    }
    return out;
}

std::mutex& events_mutex() {
    static std::mutex mutex;
    return mutex;
}

}  // namespace

std::filesystem::path catalog_events_path(
    const std::filesystem::path& project_path) {
    return pwb::project::artifact_dir_for(project_path) / "catalog" /
           "events.jsonl";
}

bool record_catalog_event(const std::filesystem::path& project_path,
                          const std::string& event,
                          const domain::Json& detail) {
    try {
        std::filesystem::path path = catalog_events_path(project_path);
        std::error_code ec;
        std::filesystem::create_directories(path.parent_path(), ec);
        if (ec) return false;

        domain::Json payload = domain::Json::object();
        payload["event"] = event;
        std::time_t now = std::time(nullptr);
        std::tm local{};
        posix_shim::localtime_compat(now, &local);
        char stamp[32];
        std::strftime(stamp, sizeof(stamp), "%Y-%m-%dT%H:%M:%S", &local);
        payload["at"] = stamp;
        payload["detail"] = detail.is_object() ? detail : domain::Json::object();

        const std::string line = py_dumps_sorted(payload);
        std::lock_guard<std::mutex> lock(events_mutex());
        std::ofstream file(path, std::ios::app | std::ios::binary);
        if (!file) return false;
        file << line << "\n";
        return static_cast<bool>(file);
    } catch (...) {
        return false;  // telemetry is best-effort by contract
    }
}

std::vector<domain::Json> read_catalog_events(
    const std::filesystem::path& project_path,
    const std::optional<std::string>& event,
    std::optional<std::size_t> limit) {
    std::vector<domain::Json> events;
    std::ifstream file(catalog_events_path(project_path), std::ios::binary);
    if (!file) return events;
    std::string line;
    while (std::getline(file, line)) {
        if (line.empty() || line.find_first_not_of(" \t\r\n") == std::string::npos) {
            continue;
        }
        if (!line.empty() && line.back() == '\r') line.pop_back();
        try {
            domain::Json entry = domain::Json::parse(line);
            if (!entry.is_object()) continue;
            if (!event.has_value() ||
                (entry.contains("event") && entry["event"].is_string() &&
                 entry["event"].get<std::string>() == *event)) {
                events.push_back(std::move(entry));
            }
        } catch (...) {
            // A torn append (crash mid-write) is skipped, not fatal.
        }
    }
    if (limit.has_value() && events.size() > *limit) {
        events.erase(events.begin(), events.end() - static_cast<std::ptrdiff_t>(*limit));
    }
    return events;
}

}  // namespace pwb::catalog
