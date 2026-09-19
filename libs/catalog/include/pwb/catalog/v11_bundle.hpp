// V11 bundle registration orchestration (conv-31b; service_v11.py 216-586
// — R8 recon contract, frozen in 31b-findings).
//
// The decision core (member-name pool with ~N disambiguation, ports⊆flat,
// retention vocabulary) is already delivered in v11_policy.hpp and stays
// pure — this header adds the IO orchestration: Phase A validation (A1-A7,
// all failures BEFORE any byte lands), the staged tree placement via
// dedup.hpp place_managed_tree (all-members-or-nothing, never CAS), member
// assembly (member_rel by string slicing off the version-dir prefix;
// version_dir_rel derived from the LAYOUT, never from the sorted file
// list — P1-1), and the Phase E commit with the rollback ladder.
// copy-then-delete (P1-2): move=true consumes the source directory only
// AFTER the metadata commit succeeds.
//
// Seams (findings §C-2/§D-12): persistence goes through the unified
// SaveHook (dirty = assets + versions [+ runs], one revision); the lease
// pair is best-effort (acquire failure → nullopt, proceed); the
// working-copy registry is the shared WorkingCopyContext (R5's state
// machine — no parallel registry interface).
//
// CONV-31b: implemented in Wave2-A8 (src/v11_bundle.cpp).
#pragma once

#include "pwb/catalog/apply_changes.hpp"  // SaveHook
#include "pwb/catalog/document_index.hpp"
#include "pwb/catalog/models.hpp"
#include "pwb/catalog/v11_policy.hpp"
#include "pwb/catalog/working_copy.hpp"
#include "pwb/domain/errors.hpp"

#include <filesystem>
#include <functional>
#include <map>
#include <optional>
#include <string>
#include <vector>

namespace pwb::catalog {

namespace fs = std::filesystem;

// ---- rel-path guard (service_v11.py 408-415, messages byte-identical) ------
// Rejects exactly: absolute paths, any ".." path component, empty strings.
// On POSIX a backslash is NOT a separator and "C:\x" is NOT absolute —
// byte-faithful behavior, do not normalize. Error:
//   Unsafe member rel_path '<rel>': must stay inside the version payload
//   directory   (single space at the implicit join, Python repr quotes)
domain::DataError validate_member_rel_path(const std::string& rel_path);

// member_path pure core: payload_base (resolve_payload_path result,
// injected by the orchestrator) / rel, re-validated here.
domain::Result<fs::path> bundle_member_path(const fs::path& payload_base,
                                            const std::string& rel_path);

// ---- registration: two-phase composable + one-step wrapper -----------------
// Phase A+B product (pure + read-only IO): specs normalized to posix rels,
// the source file inventory (posix rels, string-sorted), and the
// v11_policy name pool. A1-A7 failures land here with byte-identical
// messages (A1's "<dir>" placeholder backfilled with the real path).
struct BundleRegistrationPlan {
    std::map<std::string, VersionMember> spec_by_rel;
    std::vector<std::string> source_files;
    BundleMemberPlan names;
};
domain::Result<BundleRegistrationPlan> plan_bundle_registration(
    const fs::path& source_dir,
    const std::vector<VersionMember>& member_specs);

// The orchestrator injection points.
struct BundleSeams {
    // #1222 staging lease (best-effort): acquire failure → nullopt and
    // registration proceeds (pre-lease behavior).
    std::function<std::optional<std::string>(const std::string& target)>
        acquire_lease;
    std::function<void(const std::string& lease_id)> release_lease;
    // Phase E single-transaction persistence; dirty = assets{asset} +
    // versions{version} + runs{run} when one was linked.
    SaveHook save;
};

// Phase D+E: place the tree, assemble members (aggregate_member_sha256,
// size sum), assign version_number via next_version_number INSIDE the
// commit window, update the current pointer, run-output backfill — then
// on failure run the rollback ladder (run backfill undo → version remove
// → current restore → tree rmtree; move's delete half only after
// success). *version arrives as a half-built row (caller-generated id,
// source_uri, parent ids); the landed row is returned.
domain::Result<DataVersion> commit_bundle_registration(
    CatalogDocument* document, const DocumentIndex& index,
    const fs::path& project_path, const domain::AssetId& asset_id,
    domain::DataStage stage, const BundleRegistrationPlan& plan,
    const fs::path& source_dir, DataVersion version,
    std::optional<domain::RunId> run_id, bool move,
    const BundleSeams& seams);

// One-step wrapper (tests / already-locked callers): plan + commit. The
// two-phase form is the production path — placement happens OUTSIDE the
// service lock (Python's two-lock structure).
domain::Result<DataVersion> register_bundle_version(
    CatalogDocument* document, const DocumentIndex& index,
    const fs::path& project_path, const domain::AssetId& asset_id,
    const fs::path& source_dir, domain::DataStage stage,
    const std::vector<VersionMember>& member_specs,
    const std::vector<domain::VersionId>& parent_version_ids,
    std::optional<domain::RunId> run_id, domain::Json metadata, bool move,
    const BundleSeams& seams);

// ---- verify (service_v11.py 425-461) ----------------------------------------
// Member statuses: missing / unknown (no recorded digest) / modified /
// verified; rank verified < unknown < modified < missing; only "modified"
// entries carry actual_sha256. Tail check: all-verified + a non-null
// recomputed aggregate that differs from version.sha256 → overall
// "modified". payload_base comes from resolve_payload_path.
struct BundleMemberReport {
    std::string name;
    std::string rel_path;
    std::string status;  // verified|unknown|modified|missing
    std::optional<std::string> actual_sha256;  // only when modified
};
struct BundleIntegrityReport {
    bool bundle = false;
    std::string status = "unknown";
    std::vector<BundleMemberReport> members;
};
BundleIntegrityReport verify_bundle_integrity(const DataVersion& version,
                                              const fs::path& payload_base);

// ---- bundle working copies (service_v11.py 463-586, over R5's machine) -----
// C1-C8: not-a-bundle / payload-not-a-directory / reuse ladder (live row +
// dir, unregistered non-empty target reused, allow_replace clears) /
// member-only copy / register with null mtime+size (directory stat is
// noise — dirty_hint stays meaningful). Error texts byte-identical
// ("Version <id> is not a bundle", "Bundle payload not available: <dir>").
domain::Result<fs::path> create_bundle_working_copy(
    const DataVersion& version, const fs::path& payload_base,
    const fs::path& project_path, bool allow_replace,
    WorkingCopyContext& registry);

// M1-M8: working dir lookup, parent inference from the wc row (M3),
// committing transition, optional NEW asset via *new_asset* (the caller
// seeds pending_commit_assets around it), failure → row back to dirty,
// success → row removed.
domain::Result<DataVersion> commit_bundle_working_copy(
    CatalogDocument* document, const DocumentIndex& index,
    const fs::path& project_path, const fs::path& working_dir,
    std::optional<domain::AssetId> asset_id, std::optional<std::string> name,
    domain::DataStage stage,
    const std::vector<domain::VersionId>* parent_version_ids,  // null → M3
    std::optional<domain::RunId> run_id, domain::Json metadata,
    WorkingCopyContext& registry, const BundleSeams& seams,
    const std::function<domain::AssetId(const std::string&, domain::Json)>&
        new_asset);

// ---- private section (CONV-31b A8; service_core glue) ------------------------
// migrate_run_ports persistence half (service_v11.py 745-782): the
// v11_policy decision core runs over document.runs (it only mutates run
// fields, so a snapshot index stays valid), then ONE save whose dirty set
// is exactly the runs that gained ports. The lock stays with the caller.
// A failed save surfaces the error with the in-memory ports left mutated
// (Python parity — _save failure does not undo the backfill there).
struct PortMigrationOutcome {
    PortBackfillCounts counts;               // v11_policy core result
    std::vector<std::string> touched_run_ids;  // document order
    domain::DataError error =
        domain::DataError(domain::ErrorCode::Ok, "");
};
PortMigrationOutcome migrate_run_ports_persist(CatalogDocument* document,
                                               const DocumentIndex& index,
                                               const SaveHook& save);

}  // namespace pwb::catalog
