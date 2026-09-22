// cpp-close-03 — CatalogClosureAdapter: the workflow_runtime
// CatalogRepository seam backed by the canonical deep catalog
// (pwb::catalog::CatalogRepository → catalog.sqlite), replacing the
// temporary JSON-backed FileCatalogRepository rail for native workflow
// provenance.
//
// Semantics follow paleo_workbench/catalog/service.py + adapter.py (the
// frozen Python oracle), not RuntimeStore's in-memory shortcuts:
//
// - Writes go through the repository's atomic transactions
//   (upsert_run / publish_result_transaction / commit_version_transaction /
//   import_raw_transaction / finish_run_transaction / set_current_version /
//   upsert_asset / upsert_run) — one transaction + revision bump each,
//   db.py write discipline.
// - Payloads are managed files: the seam's string transport is staged to a
//   temp file and committed via place_managed_file (atomic copy + SHA-256 +
//   artifact layout); on a failed commit the placed bytes are rolled back.
// - register_input mirrors adapter.py: managed RAW dedup by
//   (source_uri, sha256), external-link dedup by exact resolved path, the
//   stable legacy-resource bridge, and trashed versions never being dedup
//   targets.
// - The run's private bridge keys (_domain_task_id / _input_snapshot_hash /
//   _finished_at / _actor) ride inside parameters, exactly like the Python
//   adapter; reads filter underscore keys back out (adapter._run_ref
//   parity).
// - Open is fail-closed: a corrupt or unreadable catalog.sqlite throws
//   domain::DataException from the constructor; try_open reports the error
//   so the app can decide to keep the FileCatalogRepository fallback.
//
// Threading: thread-confined by contract (same as the seam). Qt-free,
// Python-free.
#pragma once

#include <pwb/catalog/repository.hpp>
#include <pwb/domain/errors.hpp>
#include <pwb/workflow_runtime/catalog_seam.hpp>

#include <filesystem>
#include <optional>
#include <string>

namespace pwb::closure_workflow {

class CatalogClosureAdapter final
    : public pwb::workflow_runtime::CatalogRepository {
public:
    // project_path is the .paleo.json FILE path — the anchor for payload
    // placement (artifact layout) and version.path resolution
    // (resolve_payload_path). sqlite_path defaults to
    // pwb::project::catalog_sqlite_for(project_path); a missing store is
    // initialized (schema seeded). Corrupt/unreadable stores throw
    // domain::DataException — provenance is never silently reset.
    explicit CatalogClosureAdapter(
        std::filesystem::path project_path,
        std::filesystem::path sqlite_path = {});
    ~CatalogClosureAdapter() override;

    CatalogClosureAdapter(CatalogClosureAdapter&&) noexcept;
    CatalogClosureAdapter& operator=(CatalogClosureAdapter&&) noexcept;
    CatalogClosureAdapter(const CatalogClosureAdapter&) = delete;
    CatalogClosureAdapter& operator=(const CatalogClosureAdapter&) = delete;

    // Non-throwing open for the app's fallback decision: nullopt +
    // *error_out* describe why the deep catalog refused to open (the caller
    // keeps FileCatalogRepository in that case — provenance is never
    // silently dropped).
    static std::optional<CatalogClosureAdapter> try_open(
        const std::filesystem::path& project_path,
        std::filesystem::path sqlite_path = {},
        std::string* error_out = nullptr);

    // ---- CatalogRepository seam (SQLite-backed) --------------------------
    std::vector<pwb::workflow_runtime::AssetRecord> list_assets() override;
    std::optional<pwb::workflow_runtime::AssetRecord> resolve_asset(
        const std::string& asset_id) override;
    std::vector<pwb::workflow_runtime::VersionRecord> list_versions(
        const std::string& asset_id) override;
    std::optional<pwb::workflow_runtime::VersionRecord> resolve_version(
        const std::string& version_id) override;
    std::vector<pwb::workflow_runtime::RunRecord> list_runs() override;
    std::optional<pwb::workflow_runtime::RunRecord> resolve_run(
        const std::string& run_id) override;

    std::string register_run(
        const std::string& operation,
        const std::vector<std::string>& input_version_ids,
        const pwb::domain::Json& parameters,
        const std::optional<std::string>& generator_version,
        const std::string& status = "running",
        const std::optional<std::string>& domain_task_id = std::nullopt,
        const std::optional<std::string>& input_snapshot_hash = std::nullopt,
        const std::optional<std::string>& actor = std::nullopt) override;

    pwb::workflow_runtime::RegisteredAssetVersion register_result_asset(
        const std::string& name, const std::string& type,
        const std::string& format, const pwb::domain::Json& asset_metadata,
        const std::string& payload_json, const std::string& stage,
        const std::string& run_id,
        const pwb::domain::Json& version_metadata) override;

    std::string register_version(
        const std::string& asset_id, const std::string& payload_json,
        const std::string& stage,
        const std::vector<std::string>& parent_version_ids,
        const std::string& run_id,
        const pwb::domain::Json& metadata) override;

    void update_run_status(const std::string& run_id,
                           const std::string& status) override;
    void update_run_status(const std::string& run_id,
                           const std::string& status,
                           const pwb::domain::Json& extra_parameters) override;
    void attach_run_output(const std::string& run_id,
                           const std::string& version_id) override;
    void set_run_ports(const std::string& run_id,
                       const pwb::domain::Json& input_ports,
                       const pwb::domain::Json& output_ports) override;
    void set_current_version(const std::string& asset_id,
                             const std::string& version_id) override;
    std::optional<pwb::workflow_runtime::VersionRecord>
    resolve_legacy_resource(const std::string& resource_id) override;
    std::optional<std::string> verify_integrity(
        const std::string& version_id) override;

    // ---- adapter.py register_input parity (beyond the seam) ----------------
    // Managed import (external=false): dedup on (resolved path, sha256);
    // *checksum* may be empty — the file is hashed once here. External link
    // (external=true): dedup on the exact resolved path; no copy, no hash.
    // Returns the resolved/existing-or-new VersionRecord. legacy_resource_id
    // bridges the legacy resource id per adapter.py (exact-id wins, first
    // bridge wins, a trashed bridge is treated as unbridged).
    pwb::workflow_runtime::VersionRecord register_input(
        const std::string& name, const std::string& path,
        const std::optional<std::string>& checksum, const std::string& kind,
        const std::string& format, bool external,
        const std::optional<std::string>& legacy_resource_id = std::nullopt);

    [[nodiscard]] const std::filesystem::path& project_path() const {
        return project_path_;
    }
    [[nodiscard]] const std::filesystem::path& sqlite_path() const {
        return repo_.path();
    }
    // Diagnostics/fallback: the store health probe (status() parity).
    [[nodiscard]] pwb::catalog::StoreStatus store_status() const {
        return repo_.status();
    }

private:
    std::filesystem::path project_path_;  // the .paleo.json FILE path
    pwb::catalog::CatalogRepository repo_;
};

}  // namespace pwb::closure_workflow
