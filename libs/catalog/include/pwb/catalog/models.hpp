// Typed catalog models (catalog/models.py parity, schema_version=1).
#pragma once

#include "pwb/domain/ids.hpp"
#include "pwb/domain/json.hpp"
#include "pwb/domain/stage.hpp"

#include <optional>
#include <string>
#include <vector>

namespace pwb::catalog {

inline constexpr int kCatalogSchemaVersion = 1;    // sync_state schema_version
inline constexpr int kStoreSchemaVersion = 5;      // index_schema_version
inline constexpr const char* kStageDirs[] = {"raw", "derived", "intermediate",
                                             "outputs"};

struct VersionMember {
    std::string name;
    std::string rel_path;
    std::string member_role;
    int ordinal = 0;
    bool required = true;
    std::optional<std::string> sha256;
    std::optional<std::int64_t> size_bytes;
};

struct RunPort {
    std::string direction;  // "input" | "output"
    std::string role;
    domain::VersionId version_id;
    int ordinal = 0;
    bool required = true;
    std::string entity_type;
    std::string entity_id;
    std::string note;
};

struct DataAsset {
    domain::AssetId id;
    std::string name;
    std::string type = "unknown";
    std::string description;
    std::optional<domain::VersionId> current_version_id;
    std::optional<std::string> legacy_resource_id;
    domain::Json metadata = domain::Json::object();
    std::string created_at;
    std::string updated_at;
    bool trashed = false;
    std::optional<std::string> trashed_at;
};

struct DataVersion {
    domain::VersionId id;
    domain::AssetId asset_id;
    int version_number = 0;
    domain::DataStage stage = domain::DataStage::Raw;
    bool managed = true;
    std::string path;                       // project-relative POSIX / absolute
    std::optional<std::string> source_uri;
    std::string format;
    std::optional<std::int64_t> size_bytes;
    std::optional<std::string> sha256;
    std::optional<domain::RunId> run_id;
    domain::Json metadata = domain::Json::object();
    std::string created_at;
    bool trashed = false;
    std::optional<std::string> trashed_at;
    std::vector<domain::VersionId> parent_version_ids;
    std::vector<VersionMember> members;
};

struct DataRun {
    domain::RunId id;
    std::string operation;
    std::vector<domain::VersionId> input_version_ids;
    std::vector<domain::VersionId> output_version_ids;
    std::vector<RunPort> input_ports;
    std::vector<RunPort> output_ports;
    domain::Json parameters = domain::Json::object();
    std::string generator;
    std::string status = "completed";
    std::optional<domain::Json> model_ref;
    std::string created_at;
};

struct Tag {
    std::string id;
    std::string name;
    std::optional<std::string> display_name;
    domain::Json metadata = domain::Json::object();
};

struct WorkingCopy {
    std::string working_id;
    domain::VersionId source_version_id;
    std::string path;
    std::string state = "checked_out";
    std::string display_name;
    std::string created_at;
    std::string updated_at;
    std::optional<std::int64_t> payload_mtime_ns;
    std::optional<std::int64_t> source_size_bytes;
};

// The materialized catalog document (all canonical tables).
struct CatalogDocument {
    int catalog_revision = 0;
    std::vector<DataAsset> assets;
    std::vector<DataVersion> versions;
    std::vector<DataRun> runs;
    std::vector<Tag> tags;
    std::vector<std::pair<std::string, std::string>> asset_tags;
    std::vector<std::pair<std::string, std::string>> version_tags;
    std::vector<WorkingCopy> working_copies;

    const DataAsset* find_asset(const domain::AssetId& id) const;
    const DataVersion* find_version(const domain::VersionId& id) const;
    const DataRun* find_run(const domain::RunId& id) const;
    DataAsset* find_asset_mut(const domain::AssetId& id);
    DataVersion* find_version_mut(const domain::VersionId& id);
    int next_version_number(const domain::AssetId& asset_id) const;
};

// sha256("rel_path:sha256\n"...) over (ordinal, name)-sorted members —
// models.py aggregate_member_sha256. Null when no member carries a digest.
std::optional<std::string> aggregate_member_sha256(
    const std::vector<VersionMember>& members);

}  // namespace pwb::catalog
