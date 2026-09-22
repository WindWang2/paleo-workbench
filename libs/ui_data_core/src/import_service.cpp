#include "pwb/ui_data_core/import_service.hpp"

#include <algorithm>
#include <chrono>
#include <cctype>
#include <fstream>
#include <future>
#include <optional>
#include <set>
#include <sstream>
#include <unordered_set>

#include <pwb/ingest/classifier.hpp>
#include <pwb/ingest/py_compat.hpp>
#include <pwb/project/paths.hpp>

#include "pwb/ui_data_core/facies_groups.hpp"
#include "pwb/ui_data_core/scanner.hpp"

namespace pwb::ui_data_core {

using domain::Json;

namespace {

// ---------------------------------------------------------------------------
// _path_key / _existing_path_keys / _filter_new
// ---------------------------------------------------------------------------

fs::path expand_user(const fs::path& path) {
    const std::string s = path.string();
    if (!s.empty() && s.front() == '~') {
        if (const char* home = std::getenv("HOME")) {
            return fs::path(home + s.substr(1));
        }
    }
    return path;
}

// Path(path).expanduser(); absolute → resolve; relative → anchored at the
// project FILE's parent (project_path.parent) then resolved.
std::string path_key(const fs::path& path, const fs::path* project_path) {
    const fs::path candidate = expand_user(path);
    std::error_code ec;
    if (candidate.is_absolute()) {
        const auto resolved = fs::weakly_canonical(candidate, ec);
        return (ec ? candidate : resolved).generic_string();
    }
    if (project_path != nullptr) {
        const auto resolved =
            fs::weakly_canonical(project_path->parent_path() / candidate,
                                 ec);
        return (ec ? (project_path->parent_path() / candidate) : resolved)
            .generic_string();
    }
    const auto resolved = fs::weakly_canonical(candidate, ec);
    return (ec ? candidate : resolved).generic_string();
}

std::unordered_set<std::string> existing_path_keys(
    const std::vector<ResourceItem>& existing, const fs::path* project_path) {
    std::unordered_set<std::string> keys;
    for (const auto& r : existing) {
        if (!r.path.empty()) keys.insert(path_key(r.path, project_path));
    }
    return keys;
}

ImportReport filter_new(const std::vector<ResourceItem>& candidates,
                        const std::vector<ResourceItem>& existing,
                        const fs::path* project_path) {
    ImportReport report;
    auto path_keys = existing_path_keys(existing, project_path);
    for (const auto& resource : candidates) {
        const fs::path candidate_path(resource.path);
        const std::string resolved = path_key(candidate_path, project_path);
        if (path_keys.count(resolved)) {
            report.skipped_path.push_back(candidate_path);
            continue;
        }
        report.added.push_back(resource);
        path_keys.insert(resolved);
    }
    return report;
}

// ---------------------------------------------------------------------------
// _probe_summary
// ---------------------------------------------------------------------------

// datetime.fromtimestamp(mtime, UTC).isoformat() — microseconds only when
// nonzero; always "+00:00".
std::string isoformat_utc(std::int64_t sec, std::int64_t usec) {
    const std::time_t t = static_cast<std::time_t>(sec);
    std::tm tm{};
#ifdef _WIN32
    gmtime_s(&tm, &t);
#else
    gmtime_r(&t, &tm);
#endif
    char buf[64];
    std::snprintf(buf, sizeof(buf), "%04d-%02d-%02dT%02d:%02d:%02d",
                  tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday, tm.tm_hour,
                  tm.tm_min, tm.tm_sec);
    std::string out(buf);
    if (usec != 0) {
        char frac[16];
        std::snprintf(frac, sizeof(frac), ".%06lld",
                      static_cast<long long>(usec));
        out += frac;
    }
    out += "+00:00";
    return out;
}

Json probe_summary(const fs::path& path, const std::string& resource_type,
                   const std::string& resource_format) {
    Json summary = Json::object();
    std::error_code ec;
    const auto size = fs::file_size(path, ec);
    if (ec) return summary;
    summary["size_bytes"] = static_cast<long long>(size);
    const auto mtime = fs::last_write_time(path, ec);
    if (!ec) {
        // file_time → sys_time → epoch seconds+microseconds.
        const auto sys = std::chrono::time_point_cast<std::chrono::microseconds>(
            std::chrono::system_clock::now() +
            (mtime - fs::file_time_type::clock::now()));
        const auto us = sys.time_since_epoch().count();
        summary["mtime"] = isoformat_utc(us / 1000000, us % 1000000);
    }
    summary["extension"] = resource_format;
    const auto& labels = ingest::type_labels();
    const auto lit = labels.find(resource_type);
    summary["type_label"] =
        lit == labels.end() ? resource_type : lit->second;

    static const std::unordered_set<std::string> kTextProbes = {
        "csv", "txt", "md", "json", "geojson"};
    try {
        if (kTextProbes.count(resource_format) && size < 2000000) {
            std::ifstream in(path, std::ios::binary);
            std::ostringstream ss;
            ss << in.rdbuf();
            // Python read_text(encoding="utf-8", errors="replace").
            const std::string decoded =
                ingest::decode_utf8(ss.str(), /*strict=*/false)
                    .value_or(ss.str());
            long long lines = 0;
            for (const char c : decoded) lines += c == '\n';
            if (!decoded.empty() && decoded.back() != '\n') ++lines;
            summary["line_count"] = lines;
            if (resource_format == "json" || resource_format == "geojson") {
                Json data = Json::parse(decoded);  // throws → outer catch
                if (data.is_object()) {
                    summary["json_type"] =
                        data.contains("type") ? data["type"] : Json("object");
                    const auto tit = data.find("type");
                    const bool is_fc =
                        tit != data.end() && tit->is_string() &&
                        tit->get<std::string>() == "FeatureCollection";
                    if (is_fc) {
                        // len(data.get("features") or []) — non-container
                        // values count 0; arrays/objects count their size.
                        const auto fit = data.find("features");
                        summary["feature_count"] =
                            fit != data.end() &&
                                    (fit->is_array() || fit->is_object())
                                ? static_cast<long long>(fit->size())
                                : 0;
                    }
                }
                const auto tit = data.find("type");
                const bool is_fc =
                    data.is_object() && tit != data.end() &&
                    tit->is_string() &&
                    tit->get<std::string>() == "FeatureCollection";
                if (resource_format == "geojson" || is_fc) {
                    summary.update(geojson_document_summary(
                        data, path.filename().string()));
                } else if (data.is_array()) {
                    summary["json_type"] = "array";
                    summary["row_count"] =
                        static_cast<long long>(data.size());
                }
            }
        }
    } catch (const Json::parse_error&) {
        if (resource_format == "geojson") {
            summary["geojson_valid"] = false;
            summary["geojson_error"] = "JSONDecodeError";
        }
    } catch (const std::exception&) {
        if (resource_format == "geojson") {
            summary["geojson_valid"] = false;
            summary["geojson_error"] = "OSError";
        }
    }
    return summary;
}

// ---------------------------------------------------------------------------
// _collect_resource / _collect_entry / _map_collect / _collect_folder
// ---------------------------------------------------------------------------

std::string read_file_bytes(const fs::path& path) {
    std::ifstream in(path, std::ios::binary);
    std::ostringstream ss;
    ss << in.rdbuf();
    return ss.str();
}

std::optional<ResourceItem> collect_resource(const fs::path& path,
                                             const fs::path* project_path,
                                             bool preferred_only) {
    std::string ext = path.extension().string();
    if (!ext.empty() && ext.front() == '.') ext.erase(ext.begin());
    for (char& c : ext)
        c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    if (preferred_only && !ext.empty() &&
        !ingest::is_preferred_import_extension(ext)) {
        return std::nullopt;
    }
    // XML content sniff (classify_import_path reads the file only for .xml).
    std::string content;
    if (ext == "xml") content = read_file_bytes(path);
    const auto cls =
        ingest::classify_import_path(path.generic_string(), content);
    std::string resource_type = cls.type;
    const std::string& resource_format = cls.format;
    const std::string& status = cls.status;

    std::error_code ec;
    const fs::path resolved = fs::weakly_canonical(path, ec);
    const fs::path& resolved_path = ec ? path : resolved;
    Json summary =
        probe_summary(resolved_path, resource_type, resource_format);
    if (summary.value("geojson_valid", false) == true) {
        resource_type = "geojson";
        summary["type_label"] = ingest::type_labels().at("geojson");
    }
    std::string stored = resolved_path.generic_string();
    bool external = false;
    if (project_path != nullptr) {
        const auto rel = project::relativize_path(path, *project_path);
        stored = rel.stored;
        external = rel.external;
    }
    const auto& roles = ingest::role_by_type();
    const auto rit = roles.find(resource_type);
    const std::optional<std::string> role =
        rit == roles.end() ? std::nullopt
                           : std::optional<std::string>(rit->second);

    ResourceItem item;
    item.name = path.filename().string();
    item.path = stored;
    item.type = resource_type;
    item.format = resource_format;
    item.status = status;
    item.source = "import";
    item.parsed_summary = std::move(summary);
    item.external = external;
    item.artifact_role = role;
    if (role.has_value()) item.tags.push_back(*role);
    return item;
}

struct CollectEntry {
    std::optional<ResourceItem> item;
    std::optional<std::string> warning;
    std::optional<fs::path> filtered;
};

CollectEntry collect_entry(const fs::path& path, const fs::path* project_path,
                           bool preferred_only, bool explicit_file) {
    std::error_code ec;
    if (!fs::is_regular_file(path, ec) || ec) {
        if (explicit_file) {
            return {std::nullopt, path.string() + ": 不是文件",
                    std::nullopt};
        }
        return {};
    }
    if (!explicit_file &&
        path.filename().string().starts_with("._")) {
        return {};
    }
    const auto fsize = fs::file_size(path, ec);
    if (ec) {
        // Python: path.stat() OSError → f"{path}: {exc}" warning.
        return {std::nullopt, path.string() + ": " + ec.message(),
                std::nullopt};
    }
    if (fsize == 0) {
        return {std::nullopt, path.string() + ": 空文件已跳过", path};
    }
    auto item = collect_resource(path, project_path, preferred_only);
    if (!item.has_value()) return {std::nullopt, std::nullopt, path};
    return {std::move(item), std::nullopt, std::nullopt};
}

struct CollectResult {
    std::vector<ResourceItem> candidates;
    std::vector<std::string> warnings;
    std::vector<fs::path> filtered;
};

CollectResult map_collect(const std::vector<fs::path>& paths,
                          const fs::path* project_path,
                          const ImportOptions& options, bool explicit_file) {
    const int workers = std::max(
        1, std::min(options.workers > 0
                        ? options.workers
                        : default_scan_workers(options.io_slots),
                    static_cast<int>(paths.size())));
    std::vector<CollectEntry> entries(paths.size());
    for (std::size_t base = 0; base < paths.size();
         base += static_cast<std::size_t>(workers)) {
        const std::size_t limit =
            std::min(paths.size(),
                     base + static_cast<std::size_t>(workers));
        std::vector<std::future<CollectEntry>> batch;
        batch.reserve(limit - base);
        for (std::size_t i = base; i < limit; ++i) {
            batch.push_back(std::async(std::launch::async, [&, i]() {
                return collect_entry(paths[i], project_path,
                                     options.preferred_only, explicit_file);
            }));
        }
        for (std::size_t i = 0; i < batch.size(); ++i) {
            entries[base + i] = batch[i].get();
        }
    }
    CollectResult result;
    for (auto& e : entries) {
        if (e.item.has_value())
            result.candidates.push_back(std::move(*e.item));
        if (e.warning.has_value()) result.warnings.push_back(*e.warning);
        if (e.filtered.has_value()) result.filtered.push_back(*e.filtered);
    }
    return result;
}

CollectResult collect_folder(const fs::path& root,
                             const fs::path* project_path,
                             const ImportOptions& options) {
    std::vector<fs::path> paths;
    std::error_code ec;
    for (fs::recursive_directory_iterator it(root, ec), end;
         !ec && it != end; it.increment(ec)) {
        paths.push_back(it->path());
    }
    if (ec && paths.empty()) {
        return {{}, {root.string() + ": " + ec.message()}, {}};
    }
    std::sort(paths.begin(), paths.end());
    return map_collect(paths, project_path, options, /*explicit_file=*/false);
}

ImportReport finish_report(CollectResult&& collected,
                           const std::vector<ResourceItem>& existing,
                           const fs::path* project_path) {
    ImportReport report =
        filter_new(collected.candidates, existing, project_path);
    // annotate needs pointer views into report.added + existing.
    std::vector<ResourceItem*> added_ptrs;
    for (auto& r : report.added) added_ptrs.push_back(&r);
    std::vector<ResourceItem*> existing_ptrs;
    for (const auto& r : existing)
        existing_ptrs.push_back(const_cast<ResourceItem*>(&r));
    auto group_warnings =
        annotate_facies_product_groups(added_ptrs, existing_ptrs);
    report.warnings.insert(report.warnings.end(), group_warnings.begin(),
                           group_warnings.end());
    report.warnings.insert(report.warnings.end(),
                           collected.warnings.begin(),
                           collected.warnings.end());
    report.skipped_filter.insert(report.skipped_filter.end(),
                                collected.filtered.begin(),
                                collected.filtered.end());
    return report;
}

}  // namespace

// ---------------------------------------------------------------------------
// ImportReport members
// ---------------------------------------------------------------------------

std::map<std::string, int> ImportReport::by_type() const {
    std::map<std::string, int> counts;
    for (const auto& r : added) ++counts[r.type];
    return counts;
}

std::size_t ImportReport::facies_product_count() const {
    std::set<std::string> groups;
    for (const auto& r : added) {
        const Json gid =
            r.parsed_summary.value("facies_product_group_id", Json(nullptr));
        if (r.parsed_summary.value("facies_product_complete", false) &&
            gid.is_string() && !gid.get<std::string>().empty()) {
            groups.insert(gid.get<std::string>());
        }
    }
    return groups.size();
}

std::string ImportReport::summary_text() const {
    std::vector<std::string> parts;
    parts.push_back("新增 " + std::to_string(added_count()));
    if (!skipped_path.empty())
        parts.push_back("路径重复跳过 " +
                        std::to_string(skipped_path.size()));
    if (!skipped_filter.empty())
        parts.push_back("过滤跳过 " +
                        std::to_string(skipped_filter.size()));
    if (!warnings.empty())
        parts.push_back("警告 " + std::to_string(warnings.size()));
    if (!added.empty()) {
        // top-4 by count desc; Counter iteration order (first-seen) for
        // ties — track first-seen order alongside the map.
        const auto counts = by_type();
        std::vector<std::string> order;
        for (const auto& r : added) {
            if (std::find(order.begin(), order.end(), r.type) ==
                order.end()) {
                order.push_back(r.type);
            }
        }
        std::stable_sort(order.begin(), order.end(),
                         [&](const std::string& a, const std::string& b) {
                             return counts.at(a) > counts.at(b);
                         });
        std::string labels;
        const auto& type_labels = ingest::type_labels();
        for (std::size_t i = 0; i < order.size() && i < 4; ++i) {
            if (i) labels += ", ";
            const auto it = type_labels.find(order[i]);
            labels += (it == type_labels.end() ? order[i] : it->second) +
                      " " + std::to_string(counts.at(order[i]));
        }
        parts.push_back("类型: " + labels);
    }
    if (facies_product_count()) {
        parts.push_back("相图成果 " +
                        std::to_string(facies_product_count()) +
                        " 组（相/亚相/微相）");
    }
    std::string out;
    for (std::size_t i = 0; i < parts.size(); ++i) {
        if (i) out += " · ";
        out += parts[i];
    }
    return out;
}

// ---------------------------------------------------------------------------
// Public entry points
// ---------------------------------------------------------------------------

ImportReport import_files(const std::vector<fs::path>& paths,
                          const std::vector<ResourceItem>& existing,
                          const fs::path* project_path,
                          const ImportOptions& options) {
    return finish_report(
        map_collect(paths, project_path, options, /*explicit_file=*/true),
        existing, project_path);
}

ImportReport import_folder(const fs::path& root,
                           const std::vector<ResourceItem>& existing,
                           const fs::path* project_path,
                           const ImportOptions& options) {
    return finish_report(collect_folder(root, project_path, options),
                         existing, project_path);
}

}  // namespace pwb::ui_data_core
