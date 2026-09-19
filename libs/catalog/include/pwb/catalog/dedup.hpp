// Content-address store + managed payload placement (conv-15; dedup.py /
// storage.py place_managed_file parity, single-file subset).
//
// Blob layout: `<project>.artifacts/blobs/<digest[:2]>/<digest>`, placed
// atomically (temp + fsync + rename), read-only, idempotent by content
// address. A blob is referenced iff a managed version record carries its
// digest — that keep-set is the reachability GC contract, so a reachable
// committed DataVersion can never lose its payload here.
//
// place_managed_file mirrors storage.py: safe-id gate, O(1) copy-free
// adoption of an existing blob only with content proof (re-hash — the C++
// side has no in-process "hash is fresh" channel), honest caller-digest
// rejection, optional same-read blob registration. Error strings are
// byte-identical to Python (15-decisions.md D9).
#pragma once

#include "pwb/catalog/models.hpp"
#include "pwb/domain/errors.hpp"

#include <filesystem>
#include <map>
#include <optional>
#include <string>
#include <vector>

namespace pwb::catalog {

namespace fs = std::filesystem;

fs::path blob_dir_for(const fs::path& project_path);
fs::path blob_path_for(const fs::path& project_path, const std::string& digest);
bool has_blob(const fs::path& project_path, const std::string& digest);
std::int64_t blob_size(const fs::path& project_path, const std::string& digest);

struct BlobPlacement {
    bool newly_placed = false;
    std::string digest;
};

// Register *source*'s content in the store. When *digest* is given it is
// trusted (the caller already hashed the bytes); otherwise the source is
// streamed once. An already-present digest copies nothing.
domain::Result<BlobPlacement> place_blob(
    const fs::path& project_path, const fs::path& source,
    const std::optional<std::string>& digest = std::nullopt);

// Every blob digest on disk → size (shard directories only; a crash temp at
// the blobs root is invisible to the store, exactly like scan_blobs).
std::map<std::string, std::int64_t> scan_blobs(const fs::path& project_path);

// Managed, digest-carrying versions — the GC keep-set (sorted).
std::vector<std::string> referenced_digests(const CatalogDocument& document);

// On-disk blobs not reachable from any version record (sorted).
std::vector<std::string> plan_blob_gc(const fs::path& project_path,
                                      const CatalogDocument& document);

// Deletes unreferenced blobs (best-effort per file: missing → skip, other
// errors → skip and retry next sweep); *removed receives the digests.
domain::DataError sweep_unreferenced_blobs(
    const fs::path& project_path, const CatalogDocument& document,
    std::vector<std::string>* removed);

struct BlobMetrics {
    std::int64_t blobs_on_disk = 0;
    std::int64_t bytes_on_disk = 0;
    std::int64_t referenced_digests = 0;   // keep ∩ blobs
    std::int64_t unreferenced_blobs = 0;   // blobs − keep
    // Σ size×(refs−1); refs counted only over blobs present on disk (D12).
    std::int64_t bytes_deduped = 0;
};

BlobMetrics blob_metrics(const fs::path& project_path,
                         const CatalogDocument& document);

struct PlaceManagedOptions {
    bool keep_source = true;
    std::optional<std::string> known_sha256;
    bool register_blob = false;
};

struct PlacedFile {
    std::string rel_path;      // project-dir-relative POSIX
    std::int64_t size_bytes = 0;
    std::string sha256;
};

// Copy *source* into `{stage_dir}/{asset_id}/{version_id}/` atomically,
// hashing in one pass. Dedup fast path: a caller digest naming an existing
// blob of equal size is proven by re-hashing the source, then adopted
// copy-free (the version's path points at the shared read-only blob).
// Errors (domain::DataError): unsafe_id / immutable_version (target exists) /
// invalid_argument (caller digest mismatch) — messages byte-identical to the
// Python texts.
domain::Result<PlacedFile> place_managed_file(
    const fs::path& source, const fs::path& project_path,
    domain::DataStage stage, const std::string& asset_id,
    const std::string& version_id,
    const PlaceManagedOptions& options = {});

// ---- place_managed_tree (storage.py 542-615; conv-31b) ----------------------
// V11 bundle placement: every regular file under *source_dir* lands under
// `{stage_dir}/{asset_id}/{version_id}/`, each member atomic (mkstemp
// ".place-" → streaming copy+hash → fsync → rename → dir fsync →
// read-only). All-members-or-nothing: any mid-loop failure rmtree's the
// target and re-raises. Branch ladder (order is contract): safe-id gate
// BEFORE any directory exists → ensure layout → a NON-EMPTY existing
// target is refused ("Managed payload already exists: <dir>", the
// place_managed_file code) while an empty one is tolerated → source-not-
// a-directory (bare-call shape; the orchestrator pre-checks it) →
// per-member placement → an empty result set ("Bundle source directory
// is empty: <dir>") → keep_source=false rmtree's the source only after
// every member landed (copy-then-delete, P1-2).
//
// Divergences from place_managed_file: bundle members NEVER enter the
// CAS blob store, and there is no caller-digest fast path. Member order
// = Python's Path-component-tuple sort (findings B-30: implement the
// component-vector comparison, do not fall back to native string order).
// CONV-31b: implemented in Wave2-A8.
struct PlacedTreeMember {
    std::string rel_path;  // project-dir-relative POSIX, version-dir prefix
                           // included
    std::int64_t size_bytes = 0;
    std::string sha256;
};
domain::Result<std::vector<PlacedTreeMember>> place_managed_tree(
    const fs::path& source_dir, const fs::path& project_path,
    domain::DataStage stage, const std::string& asset_id,
    const std::string& version_id, bool keep_source = true);

}  // namespace pwb::catalog
