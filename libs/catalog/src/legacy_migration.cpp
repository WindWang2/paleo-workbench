#include "pwb/catalog/legacy_migration.hpp"
#include "pwb/catalog/refs.hpp"
#include "pwb/catalog/trash.hpp"
#include "pwb/project/paths.hpp"

#include <set>
#include <sys/stat.h>

namespace pwb::catalog {

namespace {
std::string py_repr(std::string_view text) {
    std::string out = "'";
    for (char c : text) {
        if (c == '\\' || c == '\'') out.push_back('\\');
        out.push_back(c);
    }
    out.push_back('\'');
    return out;
}

std::filesystem::path project_dir_of(const std::filesystem::path& project_path) {
    std::error_code ec;
    return std::filesystem::weakly_canonical(project_path.parent_path(), ec);
}

std::string absolute_posix(const std::string& path,
                           const std::filesystem::path& project_dir) {
    std::filesystem::path raw(path);
    if (raw.is_absolute()) return raw.string();
    std::error_code ec;
    return std::filesystem::weakly_canonical(project_dir / raw, ec).string();
}
}  // namespace

LegacyResourceRow LegacyResourceRow::from_json(const domain::Json& row) {
    LegacyResourceRow out;
    out.id = row.value("id", std::string());
    out.name = row.value("name", std::string());
    out.type = row.value("type", std::string());
    out.path = row.value("path", std::string());
    out.format = row.value("format", std::string());
    if (row.contains("checksum") && row["checksum"].is_string()) {
        out.checksum = row["checksum"].get<std::string>();
    }
    if (row.contains("tags") && row["tags"].is_array()) {
        for (const auto& tag : row["tags"]) {
            if (tag.is_string()) out.tags.push_back(tag.get<std::string>());
        }
    }
    if (row.contains("parsed_summary") && row["parsed_summary"].is_object()) {
        out.parsed_summary = row["parsed_summary"];
    }
    auto read_str = [&row](const char* key) {
        return (row.contains(key) && row[key].is_string())
                   ? std::optional<std::string>(row[key].get<std::string>())
                   : std::nullopt;
    };
    out.status = read_str("status");
    out.source = read_str("source");
    out.artifact_role = read_str("artifact_role");
    out.crs = read_str("crs");
    return out;
}

namespace {
std::set<std::string> existing_resource_ids(const CatalogDocument& document) {
    // Projected assets (id == legacy resource id) AND adapter-bridged
    // assets (legacy_resource_id recorded) — without the latter the
    // migration would project a second phantom asset.
    std::set<std::string> ids;
    for (const auto& asset : document.assets) {
        ids.insert(asset.id.str());
        if (asset.legacy_resource_id.has_value()) {
            ids.insert(*asset.legacy_resource_id);
        }
    }
    return ids;
}

domain::Json legacy_metadata_of(const LegacyResourceRow& resource) {
    domain::Json metadata = domain::Json::object();
    domain::Json tag_list = domain::Json::array();
    for (const auto& tag : resource.tags) tag_list.push_back(tag);
    metadata["legacy_tags"] = std::move(tag_list);
    if (resource.status.has_value()) metadata["status"] = *resource.status;
    if (resource.source.has_value()) metadata["source"] = *resource.source;
    if (resource.artifact_role.has_value()) {
        metadata["artifact_role"] = *resource.artifact_role;
    }
    if (resource.crs.has_value()) metadata["crs"] = *resource.crs;
    return metadata;
}
}  // namespace

MigrationReport migrate_resources(const std::vector<LegacyResourceRow>& resources,
                                  const std::filesystem::path& project_path,
                                  CatalogDocument* document,
                                  const std::function<std::string()>& now) {
    MigrationReport report;
    const std::filesystem::path project_dir = project_dir_of(project_path);
    std::set<std::string> existing = existing_resource_ids(*document);

    for (const auto& resource : resources) {
        if (existing.count(resource.id)) {
            report.skipped_count += 1;
            continue;
        }
        const std::filesystem::path file_path =
            std::filesystem::path(resource.path).is_absolute()
                ? std::filesystem::path(resource.path)
                : project_dir / resource.path;
        struct ::stat probe {};
        if (::stat(file_path.c_str(), &probe) != 0) {
            std::error_code ec;
            report.warnings.push_back(
                "resource " + resource.id + ": file not found at " +
                std::filesystem::weakly_canonical(file_path, ec).string());
        }
        // Pure metadata projection: never managed (#396/C34).
        const bool managed = false;
        const std::string stored_path = absolute_posix(resource.path, project_dir);

        domain::Json legacy = legacy_metadata_of(resource);
        const std::string timestamp = now ? now() : utc_now_iso();
        std::string asset_id = resource.id;
        if (!is_safe_entity_id(asset_id)) {
            asset_id = new_ref_id("asset");
            report.warnings.push_back(
                "resource " + resource.id +
                ": id unsafe as storage path segment; migrated under sanitized "
                "asset id " +
                asset_id);
        }

        std::optional<std::int64_t> size_bytes;
        domain::Json stat_fingerprint;
        if (resource.parsed_summary.contains("size_bytes")) {
            const auto& raw_size = resource.parsed_summary["size_bytes"];
            if (raw_size.is_number_integer()) {
                size_bytes = raw_size.get<std::int64_t>();
            } else if (raw_size.is_string()) {
                // Python int(value) accepts decimal strings.
                try {
                    size_bytes = std::stoll(raw_size.get<std::string>());
                } catch (...) {
                }
            }
        }
        // #1221: an external version with NO identity facts backfills a stat
        // fingerprint (size + mtime_ns) — cheap, no hashing, enough for the
        // relink stat-proof tier. The digest is never guessed.
        if (!managed && !resource.checksum.has_value() && !size_bytes.has_value()) {
            struct ::stat st {};
            if (::stat(file_path.c_str(), &st) == 0) {
                size_bytes = st.st_size;
                stat_fingerprint = domain::Json::object();
                stat_fingerprint["size"] = st.st_size;
                stat_fingerprint["mtime_ns"] =
                    static_cast<std::int64_t>(st.st_mtim.tv_nsec);
            }
        }
        domain::Json metadata = legacy;
        if (!stat_fingerprint.is_null()) {
            metadata["external_stat"] = stat_fingerprint;
        }

        std::optional<std::string> source_uri;
        if (!resource.path.empty() &&
            std::filesystem::path(resource.path).is_absolute()) {
            source_uri = std::filesystem::path(resource.path).string();
        } else {
            for (const char* key : {"source_path", "absolute_path", "path"}) {
                if (resource.parsed_summary.contains(key) &&
                    resource.parsed_summary[key].is_string()) {
                    const std::string value =
                        resource.parsed_summary[key].get<std::string>();
                    if (!value.empty() &&
                        std::filesystem::path(value).is_absolute()) {
                        source_uri = value;
                        break;
                    }
                }
            }
        }

        DataVersion version;
        version.id = domain::VersionId("ver_" + asset_id);
        version.asset_id = domain::AssetId(asset_id);
        version.version_number = 1;
        version.stage = domain::DataStage::Raw;
        version.managed = managed;
        version.path = stored_path;
        version.source_uri = source_uri;
        version.format = resource.format;
        version.size_bytes = size_bytes;
        version.sha256 = resource.checksum;
        version.metadata = std::move(metadata);
        version.created_at = timestamp;

        DataAsset asset;
        asset.id = domain::AssetId(asset_id);
        asset.name = resource.name;
        asset.type = resource.type;
        asset.current_version_id = version.id;
        asset.legacy_resource_id = resource.id;
        asset.metadata = legacy;
        asset.created_at = timestamp;
        asset.updated_at = timestamp;

        document->assets.push_back(std::move(asset));
        document->versions.push_back(std::move(version));
        existing.insert(resource.id);
        report.migrated_count += 1;
        report.asset_ids.push_back(asset_id);
    }
    return report;
}

std::vector<LegacyResourceRow> needs_migration(
    const std::vector<LegacyResourceRow>& resources,
    const CatalogDocument& document) {
    const std::set<std::string> existing = existing_resource_ids(document);
    std::vector<LegacyResourceRow> out;
    for (const auto& resource : resources) {
        if (!existing.count(resource.id)) out.push_back(resource);
    }
    return out;
}

std::string legacy_bridge_id(const DataAsset& asset) {
    return asset.legacy_resource_id.value_or(asset.id.str());
}

int remove_legacy_resources_for_assets(domain::Json* project_root,
                                       const std::vector<DataAsset>& assets) {
    std::vector<std::string> bridge_ids;
    for (const auto& asset : assets) bridge_ids.push_back(legacy_bridge_id(asset));
    return remove_legacy_resources_by_ids(project_root, bridge_ids);
}

int remove_legacy_resources_by_ids(domain::Json* project_root,
                                   const std::vector<std::string>& ids) {
    if (ids.empty()) return 0;
    const std::set<std::string> target(ids.begin(), ids.end());
    if (!project_root->is_object()) return 0;
    int before = 0;
    int after = 0;
    for (const char* key : {"resources", "export_artifacts"}) {
        if (!project_root->contains(key) || !(*project_root)[key].is_array()) {
            continue;
        }
        domain::Json& rows = (*project_root)[key];
        before += static_cast<int>(rows.size());
        domain::Json kept = domain::Json::array();
        for (const auto& row : rows) {
            const std::string id = row.value("id", std::string());
            if (target.count(id)) continue;
            kept.push_back(row);
        }
        rows = std::move(kept);
        after += static_cast<int>((*project_root)[key].size());
    }
    return before - after;
}

bool upsert_legacy_resource(domain::Json* project_root,
                            const domain::Json& item_row) {
    if (!project_root->is_object()) return false;
    if (!project_root->contains("resources") ||
        !(*project_root)["resources"].is_array()) {
        (*project_root)["resources"] = domain::Json::array();
    }
    domain::Json& rows = (*project_root)["resources"];
    const std::string id = item_row.value("id", std::string());
    for (auto& row : rows) {
        if (row.value("id", std::string()) == id) {
            row = item_row;
            return true;
        }
    }
    rows.push_back(item_row);
    return true;
}

}  // namespace pwb::catalog
