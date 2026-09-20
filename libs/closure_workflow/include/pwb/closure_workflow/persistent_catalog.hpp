#pragma once

// cpp-close-02 — FileCatalogRepository: the file-backed CatalogRepository
// for workflow provenance persistence (重开恢复).
//
// Python's workflow orchestration reaches a SQLite-backed DataCatalogService
// (paleo_workbench/catalog); the C++ catalog store belongs to the data
// line. Until that host binding lands, the workflow closure must still be
// able to PERSIST its provenance rail — runs / versions / assets / current
// pointers — across process restarts, or the acceptance loop (execute →
// modify input → stale → recompute → REOPEN → recovery) has no real
// recovery path and reuse is store-limited forever.
//
// Design:
//   * subclasses RuntimeStore — every semantic (sequential ids, payload
//     sha256 checksums, stage metadata, integrity verification, run
//     output attachment) has ONE implementation;
//   * every mutating operation re-serializes the whole store and writes
//     it atomically (tmp file + rename, `store_version` first key — the
//     workflow store convention);
//   * open() on a missing file yields an empty store; a corrupt file
//     throws (fail-closed: refuse to open over provenance with a silent
//     reset);
//   * flush() is explicit for read-only callers that mutated through a
//     base-class reference bypassing the overrides (defensive symmetry);
//     the normal path persists on every mutation.
//
// Durability bound (honest): the store is a single JSON document —
// atomic per write, not crash-proof mid-transaction across records.
// Python's SQLite gives per-statement transactions; a torn multi-record
// sequence in C++ leaves the LAST atomic state, which the run status
// discipline (booked RUNNING → completed after registration, #1219) is
// designed to survive.
//
// Qt-free, Python-free.

#include <pwb/workflow_runtime/catalog_seam.hpp>

#include <filesystem>

namespace pwb::closure_workflow {

class FileCatalogRepository : public pwb::workflow_runtime::RuntimeStore {
public:
    using RuntimeStore::RuntimeStore;

    // Load `<root>.json` (missing → empty store); throws std::runtime_error
    // on a corrupt / wrong-store_version file.
    void open(const std::filesystem::path& root);

    // Atomic write of the full store to `<root>.json` (tmp + rename).
    void flush();

    [[nodiscard]] const std::filesystem::path& file() const noexcept {
        return file_;
    }

    // ---- CatalogRepository mutators: persist after the base mutation ----
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

    void set_current_version(const std::string& asset_id,
                             const std::string& version_id) override;

    void attach_run_output(const std::string& run_id,
                           const std::string& version_id) override;

private:
    std::filesystem::path file_;
};

}  // namespace pwb::closure_workflow
