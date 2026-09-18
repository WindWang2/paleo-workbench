#pragma once

// Catalog repository seam for the workflow runtime (CONV-26).
//
// Python's workflow orchestration (freshness / recompute / constraint
// lifecycle / provenance) reaches the catalog through DataCatalogService
// (SQLite-backed). The full catalog store belongs to the Data branch; this
// header defines ONLY the repository surface the runtime needs, plus a
// deterministic in-memory implementation (RuntimeStore) used by tests and
// as the provenance sink of the WorkflowRuntimeService.
//
// The interface mirrors the catalog.service API subset the Python modules
// call: list/resolve assets+versions+runs, register_run /
// register_result_asset / register_version / update_run_status, asset
// current pointer, verify_integrity. Payload transport is string-based
// (Python writes a temp file and hands the path; the payload BYTES are the
// identity, the file location is incidental — documented divergence).
//
// Threading: thread-confined by contract (the SQLite-backed catalog
// adapter owned by the Data branch enforces its own ownership rules);
// RuntimeStore carries no locks.
//
// Qt-free, Python-free.

#include <pwb/domain/json.hpp>

#include <functional>
#include <map>
#include <optional>
#include <string>
#include <vector>

namespace pwb::workflow_runtime {

using pwb::domain::Json;

struct AssetRecord {
    std::string id;
    std::string name;
    std::string type;
    std::string format;
    std::optional<std::string> current_version_id;
    Json metadata = Json::object();
};

// Extended version mirror (catalog.types DataVersionRef fields the runtime
// surfaces read): payload checksum, trash tombstone, payload path,
// creation time. "" == None/unknown for the optional strings.
struct VersionRecord {
    std::string asset_id;
    std::string version_id;
    std::string name;
    std::optional<std::string> producing_run_id;
    std::string checksum;
    bool trashed = false;
    std::string path;
    std::string created_at;
    Json metadata = Json::object();
    std::string payload_json;  // payload text (string transport seam)
};

struct RunRecord {
    std::string run_id;
    std::string operation;
    std::vector<std::string> input_version_ids;
    std::vector<std::string> output_version_ids;
    Json parameters = Json::object();
    std::optional<std::string> generator_version;
    std::optional<std::string> domain_task_id;
    std::optional<std::string> input_snapshot_hash;
    std::string status = "running";
    std::optional<std::string> started_at;
    std::optional<std::string> finished_at;
    std::optional<std::string> actor;
    Json run_metadata = Json::object();
};

struct RegisteredAssetVersion {
    std::string asset_id;
    std::string version_id;
};

// Callback bundle mirroring the Python catalog access points freshness
// uses beyond the graph snapshot (resolve_version / verify_integrity /
// payload existence). All callbacks are best-effort: nullopt means
// unknown. Optional members may be empty (no callback installed).
struct CatalogSeam {
    std::function<std::optional<VersionRecord>(const std::string& id)>
        resolve_version;
    // "verified" | "modified" | ... — Python IntegrityStatus value string.
    std::function<std::optional<std::string>(const std::string& id)>
        verify_integrity;
    std::function<bool(const std::string& path)> file_exists;
};

class CatalogRepository {
public:
    virtual ~CatalogRepository() = default;

    // ---- listing / resolution (lazy-safe per-asset paths first) ----
    virtual std::vector<AssetRecord> list_assets() = 0;
    virtual std::optional<AssetRecord> resolve_asset(
        const std::string& asset_id) = 0;
    // Versions of one asset, version-sorted (oldest → latest).
    virtual std::vector<VersionRecord> list_versions(
        const std::string& asset_id) = 0;
    virtual std::optional<VersionRecord> resolve_version(
        const std::string& version_id) = 0;
    virtual std::vector<RunRecord> list_runs() = 0;
    virtual std::optional<RunRecord> resolve_run(
        const std::string& run_id) = 0;

    // ---- mutations (the sanctioned atomic paths) ----
    // Returns the new run id.
    virtual std::string register_run(
        const std::string& operation,
        const std::vector<std::string>& input_version_ids,
        const Json& parameters,
        const std::optional<std::string>& generator_version,
        const std::string& status = "running",
        const std::optional<std::string>& domain_task_id = std::nullopt,
        const std::optional<std::string>& input_snapshot_hash = std::nullopt,
        const std::optional<std::string>& actor = std::nullopt) = 0;

    // First commit shape: asset + first version + run linkage in one
    // atomic operation (register_result_asset).
    virtual RegisteredAssetVersion register_result_asset(
        const std::string& name, const std::string& type,
        const std::string& format, const Json& asset_metadata,
        const std::string& payload_json, const std::string& stage,
        const std::string& run_id, const Json& version_metadata) = 0;

    // Append an immutable version to an existing asset; returns version id.
    virtual std::string register_version(
        const std::string& asset_id, const std::string& payload_json,
        const std::string& stage,
        const std::vector<std::string>& parent_version_ids,
        const std::string& run_id, const Json& metadata) = 0;

    virtual void update_run_status(const std::string& run_id,
                                   const std::string& status) = 0;

    // Wire a produced version into its run's output_version_ids (the
    // Python catalog does this inside register_*; the seam keeps it
    // explicit so the provenance publish path stays visible).
    virtual void attach_run_output(const std::string& run_id,
                                   const std::string& version_id) = 0;

    // Project selection pointer (asset tip).
    virtual void set_current_version(const std::string& asset_id,
                                     const std::string& version_id) = 0;

    // Integrity dimension: re-hash payload vs recorded checksum →
    // "verified" | "modified" (Python IntegrityStatus value string).
    virtual std::optional<std::string> verify_integrity(
        const std::string& version_id) = 0;
};

// Deterministic in-memory repository. Ids are sequential counters
// ("asset_000001", "ver_000001", "run_000001"), checksums are the payload's
// SHA-256 and timestamps come from the injected clock (default: fixed base
// + 1s per registration) — byte-stable across runs, mirroring the fake
// catalogs of the Python oracle.
class RuntimeStore : public CatalogRepository {
public:
    using Clock = std::function<std::string()>;

    explicit RuntimeStore(Clock clock = nullptr);

    std::vector<AssetRecord> list_assets() override;
    std::optional<AssetRecord> resolve_asset(
        const std::string& asset_id) override;
    std::vector<VersionRecord> list_versions(
        const std::string& asset_id) override;
    std::optional<VersionRecord> resolve_version(
        const std::string& version_id) override;
    std::vector<RunRecord> list_runs() override;
    std::optional<RunRecord> resolve_run(
        const std::string& run_id) override;

    std::string register_run(
        const std::string& operation,
        const std::vector<std::string>& input_version_ids,
        const Json& parameters,
        const std::optional<std::string>& generator_version,
        const std::string& status = "running",
        const std::optional<std::string>& domain_task_id = std::nullopt,
        const std::optional<std::string>& input_snapshot_hash = std::nullopt,
        const std::optional<std::string>& actor = std::nullopt) override;

    RegisteredAssetVersion register_result_asset(
        const std::string& name, const std::string& type,
        const std::string& format, const Json& asset_metadata,
        const std::string& payload_json, const std::string& stage,
        const std::string& run_id, const Json& version_metadata) override;

    std::string register_version(
        const std::string& asset_id, const std::string& payload_json,
        const std::string& stage,
        const std::vector<std::string>& parent_version_ids,
        const std::string& run_id, const Json& metadata) override;

    void update_run_status(const std::string& run_id,
                           const std::string& status) override;
    void set_current_version(const std::string& asset_id,
                             const std::string& version_id) override;
    std::optional<std::string> verify_integrity(
        const std::string& version_id) override;

    // Wire the producing run's output_version_ids (Python's catalog does
    // this inside register_result_asset / register_version; the runtime
    // keeps it explicit so the provenance publish path is visible).
    void attach_run_output(const std::string& run_id,
                           const std::string& version_id) override;

    [[nodiscard]] const std::vector<VersionRecord>& versions() const {
        return versions_;
    }
    [[nodiscard]] const std::vector<RunRecord>& runs() const {
        return runs_;
    }
    [[nodiscard]] const std::vector<AssetRecord>& assets() const {
        return assets_;
    }

private:
    std::string next_time();

    std::vector<AssetRecord> assets_;
    std::vector<VersionRecord> versions_;
    std::vector<RunRecord> runs_;
    std::map<std::string, std::size_t> asset_index_;
    std::map<std::string, std::size_t> version_index_;
    std::map<std::string, std::size_t> run_index_;
    std::map<std::string, std::vector<std::size_t>> asset_versions_index_;
    unsigned long next_asset_ = 0;
    unsigned long next_version_ = 0;
    unsigned long next_run_ = 0;
    long tick_ = 0;
    Clock clock_;
};

}  // namespace pwb::workflow_runtime
