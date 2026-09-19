// Typed catalog models (catalog/models.py parity, schema_version=1).
//
// CONV-31b additions (contract freeze): the model registry DTOs Model /
// ModelVersion (models.py parity, one field per declared Python attribute,
// same order) and their JSON codecs. to_dict() reproduces the pydantic
// model_dump key ORDER (domain::Json is ordered_json, so the manifest
// round-trips in declaration order); from_dict() is strict-typed — a
// missing required field or a wrong-typed value is an error (callers such
// as load_manifest treat that as the corrupt-manifest branch), absent
// optional fields fall back to the same defaults pydantic declares.
// ModelVersion.status intentionally defaults to "production" (the
// row/DTO-load default of models.py:230 so old documents load verbatim);
// register_model_version passes "demo" explicitly — the two defaults must
// stay separate (R7 recon ⑥-2).
#pragma once

#include "pwb/domain/errors.hpp"
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

// One derivation edge (versions.parent_version_ids normalized into rows).
struct LineageEdge {
    std::string parent_version_id;
    std::string child_version_id;
};

// One staging lease row (single-writer admission; written by B's gates).
struct StagingLease {
    std::string lease_id;
    std::string target;
    std::string kind;
    std::string acquired_at;
    std::string heartbeat_at;
};

// A logical computation model registered in the catalog (models.py Model;
// no ML-framework binding). model_id is the stable logical id, capability
// what the model does, provider the backend name, status one of
// demo/production/archived — only "production" is found by
// find_production_model.
struct Model {
    std::string id;                 // make_id("model") shape: model_<12hex>
    std::string model_id;
    std::string model_name;
    std::string model_type = "unknown";  // heuristic | demo | ml | ...
    std::string capability;
    std::string provider;
    std::string status = "demo";
    domain::Json metadata = domain::Json::object();
    std::string created_at;
    domain::Json provenance = domain::Json::object();

    domain::Json to_dict() const;
    static domain::Result<Model> from_dict(const domain::Json& data);
};

// A concrete registered version of a Model (models.py ModelVersion).
// checksum hashes the artifact when one exists; demo_only marks a version
// that must never be presented as production output.
struct ModelVersion {
    std::string id;                 // make_id("mver") shape: mver_<12hex>
    std::string model_id;
    std::string model_version = "1";
    std::string artifact_uri;
    std::optional<std::string> checksum;
    domain::Json input_schema = domain::Json::object();
    domain::Json output_schema = domain::Json::object();
    std::string preprocessing_version;
    std::string runtime;
    bool deterministic = true;
    bool demo_only = false;
    std::string status = "production";  // DTO/row-load default (models.py:230);
                                        // registration passes "demo" explicitly
    domain::Json metadata = domain::Json::object();
    std::string created_at;
    domain::Json provenance = domain::Json::object();

    domain::Json to_dict() const;
    static domain::Result<ModelVersion> from_dict(const domain::Json& data);
};

// The materialized catalog document (all canonical tables).
struct CatalogDocument {
    int schema_version = kCatalogSchemaVersion;  // manifest schema_version
    int catalog_revision = 0;
    std::vector<DataAsset> assets;
    std::vector<DataVersion> versions;
    std::vector<DataRun> runs;
    std::vector<Tag> tags;
    // Model registry (models.py:289): additive lists — old documents load
    // without them (defaults stay empty).
    std::vector<Model> models;
    std::vector<ModelVersion> model_versions;
    std::vector<std::pair<std::string, std::string>> asset_tags;
    std::vector<std::pair<std::string, std::string>> version_tags;
    std::vector<WorkingCopy> working_copies;
    std::vector<LineageEdge> lineage;
    std::vector<StagingLease> staging_leases;

    const DataAsset* find_asset(const domain::AssetId& id) const;
    const DataVersion* find_version(const domain::VersionId& id) const;
    const DataRun* find_run(const domain::RunId& id) const;
    DataAsset* find_asset_mut(const domain::AssetId& id);
    DataVersion* find_version_mut(const domain::VersionId& id);
    int next_version_number(const domain::AssetId& asset_id) const;

    // Registry lookups (service.py _model_or_raise / get_model_version:
    // linear scans matching Model.model_id / (model_id, model_version) / id).
    const Model* find_model(const std::string& model_id) const;
    const ModelVersion* find_model_version(const std::string& model_id,
                                           const std::string& model_version) const;
    const ModelVersion* find_model_version_by_id(const std::string& id) const;
    Model* find_model_mut(const std::string& model_id);
    ModelVersion* find_model_version_mut(const std::string& model_id,
                                         const std::string& model_version);
    ModelVersion* find_model_version_by_id_mut(const std::string& id);
};

// sha256("rel_path:sha256\n"...) over (ordinal, name)-sorted members —
// models.py aggregate_member_sha256. Null when no member carries a digest.
std::optional<std::string> aggregate_member_sha256(
    const std::vector<VersionMember>& members);

}  // namespace pwb::catalog
