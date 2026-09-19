// Working-copy lifecycle state machine (conv-31b; service.py 2270-2643 +
// db.py working-copy/staging-lease bookkeeping — R5 recon contract,
// frozen in 31b-findings).
//
// States: checked_out / dirty / committing. committed and abandoned are
// TERMINAL and have no row (success deletes it). The only two persisted
// writes of `dirty` are commit-failure fallback and crash recovery;
// `dirty_hint` on the read side is advisory and never written. Registry
// writes are ALL best-effort (errors surface in diagnostics, never fail
// a checkout or commit — service.py:2351 parity). Registry truth is the
// sqlite table, never the document snapshot (findings §C-9).
//
// The W3 crash window (payload copied+unlinked, metadata not yet
// committed → recover reports missing_dropped) is Python-parity and is
// deliberately NOT "fixed" (findings B-23).
//
// CONV-31b: implemented in Wave2-A5 (src/working_copy.cpp).
#pragma once

#include "pwb/catalog/models.hpp"
#include "pwb/catalog/repository.hpp"
#include "pwb/domain/errors.hpp"

#include <filesystem>
#include <optional>
#include <set>
#include <string>
#include <string_view>
#include <vector>

namespace pwb::catalog {

namespace fs = std::filesystem;

// db.py:512-528 state literals.
enum class WorkingCopyState { CheckedOut, Dirty, Committing };

inline constexpr std::string_view to_string(WorkingCopyState state) noexcept {
    switch (state) {
        case WorkingCopyState::CheckedOut: return "checked_out";
        case WorkingCopyState::Dirty: return "dirty";
        case WorkingCopyState::Committing: return "committing";
    }
    return "checked_out";
}
std::optional<WorkingCopyState> parse_working_copy_state(
    std::string_view value);

// service.py _working_copy_status (2357-2394): the full status shape the
// edit-session/UI consumers read.
struct WorkingCopyStatus {
    std::string working_id;
    std::string source_version_id;
    std::string display_name;
    std::string created_at;
    std::string updated_at;
    fs::path path;                      // absolute = project_dir / row.path
    WorkingCopyState state = WorkingCopyState::CheckedOut;
    bool exists = false;
    bool dirty_hint = false;            // fingerprint drift (mtime or size)
    bool source_version_known = false;  // source still in the document
};

// Single-writer context (GcContext precedent). pending_commit_assets is
// shared with the purge zombie guard (#1218) — add/discard must be
// mutually exclusive with purge's live-asset judgment.
struct WorkingCopyContext {
    fs::path project_path;              // the .paleo.json project FILE
    CatalogRepository* repo = nullptr;  // registry + lease write side
    CatalogDocument* document = nullptr;  // version/asset lookups +
                                          // source_uri recovery index
    std::set<std::string>* pending_commit_assets = nullptr;
};

// service.py create_working_copy (2270): the reuse ladder in order —
// live row + file + !allow_replace → return existing path silently;
// allow_replace → discard row+file first; live row + missing file → dead
// row, delete and re-checkout; NO row but file on disk → fail-closed
// reuse (#1211); PermissionError rename retry ×4 with backoff. The
// source payload missing → NotFound "Payload not available: <abs path>"
// (byte-identical). Registration is best-effort.
domain::Result<fs::path> create_working_copy(WorkingCopyContext& context,
                                             const domain::VersionId&
                                                 source_version_id,
                                             bool allow_replace = false);

// Registry read failure → empty (swallow parity).
std::vector<WorkingCopyStatus> list_working_copies(WorkingCopyContext& context);

// Path outside the project dir or no row → nullopt.
std::optional<WorkingCopyStatus> working_copy_state(
    WorkingCopyContext& context, const fs::path& working_path);

// service.py discard_working_copy (2433). A committing copy refuses with
// the byte-identical Chinese message
//   "工作副本正在提交中，不能丢弃；请等待提交完成或重启后恢复。"
// Returns true when a registered copy (or an unregistered file) was
// removed, false when there was nothing to discard.
domain::Result<bool> discard_working_copy(WorkingCopyContext& context,
                                          const fs::path& working_path);

// service.py recover_working_copies (2465) + telemetry event
// (working_copy.recovery). Judgment order IS semantics: missing-file
// drops BEFORE the committing branch. committing + committed version
// (source_uri hit, both sides resolved posix) → row deleted;
// committing + no landing → back to dirty (the move is copy-then-unlink,
// an un-moved file is intact).
struct WorkingCopyRecovery {
    int committing_dropped = 0;
    int reverted_to_dirty = 0;
    int missing_dropped = 0;
    std::vector<WorkingCopyStatus> surviving;
};
WorkingCopyRecovery recover_working_copies(WorkingCopyContext& context);

// ---- commit orchestration (service.py 2525-2643) ---------------------------
struct CommitWorkingCopyRequest {
    // nullopt = NEW asset (#1218 lock-free window; the caller seeds
    // pending_commit_assets around the payload move).
    std::optional<domain::AssetId> asset_id;
    // New asset → asset name; existing asset → version metadata["name"]
    // (an empty string writes no key).
    std::string name;
    domain::DataStage stage = domain::DataStage::Derived;
    // nullopt → infer from the parent directory name when it is a known
    // version id, else empty.
    std::optional<std::vector<domain::VersionId>> parent_version_ids;
    std::optional<domain::RunId> run_id;
    domain::Json metadata = domain::Json::object();
};
domain::Result<DataVersion> commit_working_copy(
    WorkingCopyContext& context, const fs::path& working_path,
    const CommitWorkingCopyRequest& request);

// ---- transition primitives (bundle commits reuse these — R8) ----------------
// All best-effort (swallow parity); return whether the row landed. They
// keep the sqlite row and the caller's document snapshot consistent.
bool mark_committing(WorkingCopyContext& context, const fs::path& working_path);
bool revert_to_dirty(WorkingCopyContext& context,
                     const std::string& working_id);
bool drop_row(WorkingCopyContext& context, const std::string& working_id);

// ---- staging lease (db.py 1227-1331 write side; gc.hpp has the read side) --
// RAII: acquire failure → empty id (pre-lease semantics continue); the
// destructor releases and swallows errors.
class StagingLeaseGuard {
public:
    StagingLeaseGuard(CatalogRepository& repo,
                      std::vector<std::string> targets,
                      std::string kind = "register");
    ~StagingLeaseGuard();
    StagingLeaseGuard(StagingLeaseGuard&& other) noexcept;
    StagingLeaseGuard& operator=(StagingLeaseGuard&& other) noexcept;
    StagingLeaseGuard(const StagingLeaseGuard&) = delete;
    StagingLeaseGuard& operator=(const StagingLeaseGuard&) = delete;

    // Empty = not acquired (best-effort contract).
    const std::string& id() const noexcept { return lease_id_; }

private:
    CatalogRepository* repo_ = nullptr;
    std::string lease_id_;
};

// service.py _staging_target (1623-1639): "<project>.artifacts/<stage dir
// name>/<asset_id>" as a project-relative posix string. The stage segment
// is the ON-DISK directory name (OUTPUT → "outputs", NOT stage.value) —
// gc derives its prefixes from the real layout, a value-shaped key never
// prefix-matches. Single source of truth: promote/bundle/gc all consume
// this (findings §C-7).
std::string staging_target(const fs::path& project_path,
                           std::optional<domain::DataStage> stage,
                           std::optional<std::string_view> asset_id);
// service.py 1641-1642: blob imports additionally lease
// "<project>.artifacts/blobs".
std::string blob_staging_target(const fs::path& project_path);

}  // namespace pwb::catalog
