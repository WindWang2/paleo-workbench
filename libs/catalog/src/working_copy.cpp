// Working-copy lifecycle state machine (conv-31b; service.py 2270-2643 +
// db.py 1335-1425 registry bookkeeping — R5 recon contract, frozen in
// 31b-findings §A-5). Implementation of the frozen working_copy.hpp.
//
// Invariants carried verbatim from Python:
// - Registry truth is the sqlite working_copies table (findings §C-9). The
//   document snapshot is mirrored best-effort AFTER the sqlite write lands
//   (库→内存 order) so an export never shows a stale row, but no judgment
//   ever reads it.
// - Every registry write is best-effort: an error is swallowed (logged via
//   the returned bool only) and NEVER fails a checkout or commit
//   (service.py:2351 parity).
// - The only two persisted writes of `dirty` are commit-failure fallback
//   and crash recovery; read-side dirty_hint never writes.
// - recover judgment order IS semantics: missing-file drops BEFORE the
//   committing branch (the W3 crash window lands in missing_dropped —
//   Python parity, deliberately not "fixed", findings B-23).
// - The staging lease wraps the whole place→save window and is protection,
//   not a gate (acquire failure proceeds pre-lease).
//
// Notable mappings (no C++ exception channel):
// - Python CatalogError "工作副本正在提交中，..." (discard guard) →
//   DataError{InvalidArgument, <byte-identical message>}. There is no
//   generic-CatalogError code in the taxonomy; InvalidArgument is the
//   "request refused in current state" guard precedent (data_suite).
// - Unknown asset/version/run lookups → NotFound with byte-identical texts.
//
// Registration timestamps are local-time ISO seconds (db.py
// datetime.now().isoformat(timespec="seconds")); entity created_at uses
// domain::now_iso8601() (models.py _now_iso, UTC shape).
#include "posix_shim.hpp"
#include "pwb/catalog/working_copy.hpp"

#include "pwb/catalog/dedup.hpp"       // place_managed_file
#include "pwb/catalog/resolve.hpp"     // resolve_payload_path (A6)
#include "pwb/catalog/telemetry.hpp"   // record_catalog_event
#include "pwb/catalog/trash.hpp"       // placement + layout + safe-id gate
#include "pwb/domain/diagnostics.hpp"  // now_iso8601
#include "pwb/domain/ids.hpp"          // make_id
#include "pwb/project/paths.hpp"       // project_dir_for / artifact_dir_for

#include <sys/stat.h>

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <ctime>
#include <thread>
#include <unordered_map>
#include <utility>

namespace pwb::catalog {

using pwb::domain::DataError;
using pwb::domain::ErrorCode;

namespace {

fs::path project_root(const WorkingCopyContext& context) {
    return pwb::project::project_dir_for(context.project_path);
}

// db.py datetime.now().isoformat(timespec="seconds") — LOCAL time, no zone.
std::string local_now_iso() {
    const std::time_t now = std::time(nullptr);
    std::tm local{};
#if !defined(_WIN32)
    localtime_r(&now, &local);
#else
    localtime_s(&local, &now);
#endif
    char buffer[32];
    const std::size_t written =
        std::strftime(buffer, sizeof(buffer), "%Y-%m-%dT%H:%M:%S", &local);
    return std::string(buffer, written);
}

// storage.py safe_unlink parity: clear the read-only bit, unlink, swallow
// every error. trash.cpp has the same logic privately and does not export
// it (R5 ③), so this TU keeps its own copy.
void safe_unlink_best_effort(const fs::path& path) {
    std::error_code ec;
    fs::permissions(path, fs::perms::owner_write, fs::perm_options::add, ec);
    fs::remove(path, ec);
}

// st_mtim ns (findings B-16; Windows maps the 100 ns file-time ticks —
// the second-granular fallback note is superseded by the fs probe, same
// direction as repository.cpp disk_mtime_ns).
std::optional<std::int64_t> mtime_ns_of(const fs::path& path) {
    const posix_shim::FileStat st = posix_shim::stat_path(path);
    if (!st.exists) return std::nullopt;
    return st.mtime_ns;
}

// Python Path.relative_to(project_dir) → posix string; nullopt when the
// path is not under the project dir (ValueError → None parity). Lexical
// only — no symlink resolution, like relative_to.
std::optional<std::string> posix_rel_under(const fs::path& path,
                                           const fs::path& directory) {
    if (path.empty() || directory.empty() || path.is_relative()) {
        return std::nullopt;
    }
    const fs::path rel = path.lexically_relative(directory);
    if (rel.empty() || rel.is_absolute()) return std::nullopt;
    if (rel.begin() != rel.end() && rel.begin()->generic_string() == "..") {
        return std::nullopt;
    }
    return rel.generic_string();
}

// Path.resolve().as_posix() (B-25: weakly_canonical equivalent).
std::string resolved_posix(const fs::path& path) {
    std::error_code ec;
    fs::path resolved = fs::weakly_canonical(path, ec);
    if (ec || resolved.empty()) {
        resolved = path.lexically_normal();
    }
    return resolved.generic_string();
}

std::string format_of(const domain::Json& metadata) {
    const auto it = metadata.find("format");
    if (it != metadata.end() && it->is_string()) {
        return it->get<std::string>();
    }
    return "";
}

// ---- document-snapshot mirroring (bookkeeping only; truth is sqlite) -------

void mirror_row_upsert(WorkingCopyContext& context, const WorkingCopy& row) {
    if (context.document == nullptr) return;
    for (WorkingCopy& existing : context.document->working_copies) {
        if (existing.working_id == row.working_id) {
            existing = row;
            return;
        }
    }
    context.document->working_copies.push_back(row);
}

void mirror_row_state(WorkingCopyContext& context,
                      const std::string& working_id, const std::string& state) {
    if (context.document == nullptr) return;
    for (WorkingCopy& existing : context.document->working_copies) {
        if (existing.working_id == working_id) {
            existing.state = state;
            existing.updated_at = local_now_iso();
            return;
        }
    }
}

void mirror_row_drop(WorkingCopyContext& context,
                     const std::string& working_id) {
    if (context.document == nullptr) return;
    std::erase_if(context.document->working_copies,
                  [&](const WorkingCopy& row) {
                      return row.working_id == working_id;
                  });
}

// service.py _working_copy_status (2357-2394).
WorkingCopyStatus status_from_row(WorkingCopyContext& context,
                                  const WorkingCopy& row) {
    WorkingCopyStatus status;
    status.working_id = row.working_id;
    status.source_version_id = row.source_version_id.str();
    status.display_name = row.display_name;
    status.created_at = row.created_at;
    status.updated_at = row.updated_at;
    status.path = project_root(context) / fs::path(row.path);
    status.state =
        parse_working_copy_state(row.state).value_or(WorkingCopyState::CheckedOut);

    std::error_code ec;
    const bool exists = fs::is_regular_file(status.path, ec);
    std::optional<std::int64_t> mtime_ns;
    std::optional<std::int64_t> size;
    if (exists) {
        mtime_ns = mtime_ns_of(status.path);
        size = static_cast<std::int64_t>(fs::file_size(status.path, ec));
        if (ec) size = std::nullopt;
    }
    status.exists = exists;
    // Conservative dirty hint: any fingerprint drift counts as edited
    // (false positives are safe). committing copies never flag.
    const bool state_hints = row.state == "checked_out" || row.state == "dirty";
    const bool mtime_drift = row.payload_mtime_ns.has_value()
                             && mtime_ns.has_value()
                             && *mtime_ns != *row.payload_mtime_ns;
    const bool size_drift = row.source_size_bytes.has_value() && size.has_value()
                            && *size != *row.source_size_bytes;
    status.dirty_hint = exists && state_hints && (mtime_drift || size_drift);
    status.source_version_known =
        context.document != nullptr
        && context.document->find_version(row.source_version_id) != nullptr;
    return status;
}

// service.py _discard_working_copy_row_and_file (2421-2431): file first,
// row second, both best-effort.
void discard_row_and_file(WorkingCopyContext& context, const WorkingCopy& row,
                          const fs::path& path) {
    safe_unlink_best_effort(path);
    if (context.repo->remove_working_copy(row.working_id).code == ErrorCode::Ok) {
        mirror_row_drop(context, row.working_id);
    }
}

// service.py _rollback payload leg (1588-1608): CAS payloads are shared and
// never unlinked; a consumed working copy goes back where it came from;
// otherwise the placed copy is removed and the empty ancestors pruned.
void rollback_payload(const WorkingCopyContext& context, const fs::path& payload,
                      const fs::path& restore_to) {
    if (is_cas_path(context.project_path, payload.generic_string())) {
        return;  // shared, content-addressed, immutable
    }
    std::error_code ec;
    if (!restore_to.empty() && fs::exists(payload, ec)) {
        fs::rename(payload, restore_to, ec);  // os.replace; errors swallowed
        return;
    }
    safe_unlink_best_effort(payload);
    const fs::path ancestors[2] = {payload.parent_path(),
                                   payload.parent_path().parent_path()};
    for (const fs::path& directory : ancestors) {
        std::error_code remove_ec;
        fs::remove(directory, remove_ec);  // rmdir semantics: non-empty fails
    }
}

// service.py register_version core as consumed by commit_working_copy
// (1729-1835 restricted to move=True + fresh version ids). The in-memory
// document and the one-transaction store write stay in the Python order:
// place bytes (unlocked) → re-validate → mutate memory → commit → on
// failure undo memory + restore the payload.
domain::Result<DataVersion> register_working_version(
    WorkingCopyContext& context, const fs::path& source_path,
    const domain::AssetId& asset_id, domain::DataStage stage,
    const std::vector<domain::VersionId>& parent_version_ids,
    const std::optional<domain::RunId>& run_id, const domain::Json& metadata,
    bool include_asset_row) {
    std::error_code ec;
    if (!fs::is_regular_file(source_path, ec)) {
        return DataError(ErrorCode::NotFound,
                         "Source file not found: " + source_path.string());
    }
    // Locked pre-place validation (1762-1770): the asset and the run must
    // exist before any payload bytes move.
    if (context.document->find_asset(asset_id) == nullptr) {
        return DataError(ErrorCode::NotFound, "Unknown asset: " + asset_id.str());
    }
    if (run_id.has_value() && context.document->find_run(*run_id) == nullptr) {
        return DataError(ErrorCode::NotFound, "Unknown run: " + run_id->str());
    }

    // #1222: the lease covers the whole place→metadata-commit window.
    StagingLeaseGuard lease(
        *context.repo,
        {staging_target(context.project_path, stage, asset_id.str())},
        "register");

    // _build_version (1670-1727).
    const DataAsset* source_asset = context.document->find_asset(asset_id);
    if (!is_safe_entity_id(asset_id.str())) {
        // #1175: asset.id flows into the same storage path segments as
        // version_id.
        return DataError(ErrorCode::UnsafeId,
                         "Unsafe asset id '" + asset_id.str()
                             + "': only [A-Za-z0-9._-] allowed");
    }
    DataVersion version;
    version.id = domain::VersionId(domain::make_id("ver_"));
    version.asset_id = asset_id;
    version.stage = stage;
    version.managed = true;
    version.source_uri = resolved_posix(source_path);
    version.format = format_of(source_asset->metadata);
    version.parent_version_ids = parent_version_ids;
    version.run_id = run_id;
    version.metadata = metadata;
    version.created_at = domain::now_iso8601();

    auto placed = place_managed_file(
        source_path, context.project_path, stage, asset_id.str(),
        version.id.str(),
        PlaceManagedOptions{/*keep_source=*/false, /*known_sha256=*/std::nullopt,
                            /*register_blob=*/false});
    if (!placed.is_ok()) return DataError(placed.error());
    version.path = placed.value().rel_path;
    version.size_bytes = placed.value().size_bytes;
    version.sha256 = placed.value().sha256;

    const fs::path payload = resolve_payload_path(context.project_path, version);

    // Locked re-validation (1789-1812): rollback + error parity.
    DataAsset* asset = context.document->find_asset_mut(asset_id);
    if (asset == nullptr) {
        rollback_payload(context, payload, source_path);
        return DataError(ErrorCode::NotFound, "Unknown asset: " + asset_id.str());
    }
    if (context.document->find_version(version.id) != nullptr) {
        rollback_payload(context, payload, source_path);
        return DataError(ErrorCode::ImmutableVersion,
                         "Version " + version.id.str()
                             + " is already committed and immutable");
    }
    DataRun* run = nullptr;
    if (run_id.has_value()) {
        // models.hpp exposes no find_run_mut; scan the public vector.
        for (DataRun& candidate : context.document->runs) {
            if (candidate.id == *run_id) {
                run = &candidate;
                break;
            }
        }
        if (run == nullptr) {
            rollback_payload(context, payload, source_path);
            return DataError(ErrorCode::NotFound,
                             "Unknown run: " + run_id->str());
        }
    }

    // Commit-time mutation (1813-1825): version number, current pointer,
    // run output linkage — in memory first, then the single transaction.
    version.version_number = context.document->next_version_number(asset_id);
    const std::optional<domain::VersionId> previous_current =
        asset->current_version_id;
    context.document->versions.push_back(version);
    asset->current_version_id = version.id;
    bool run_output_added = false;
    if (run != nullptr
        && std::find(run->output_version_ids.begin(),
                     run->output_version_ids.end(), version.id)
               == run->output_version_ids.end()) {
        run->output_version_ids.push_back(version.id);
        run_output_added = true;
    }

    std::optional<DataAsset> asset_row;
    if (include_asset_row) {
        if (const DataAsset* current = context.document->find_asset(asset_id)) {
            asset_row = *current;  // post-mutation (current pointer set)
        }
    }
    const DataError save_error = context.repo->commit_working_copy_transaction(
        asset_row, version, run_id);
    if (save_error.code != ErrorCode::Ok) {
        if (run != nullptr && run_output_added) {
            std::erase(run->output_version_ids, version.id);
        }
        std::erase_if(context.document->versions, [&](const DataVersion& v) {
            return v.id == version.id;
        });
        if (DataAsset* restore = context.document->find_asset_mut(asset_id)) {
            restore->current_version_id = previous_current;
        }
        rollback_payload(context, payload, source_path);
        return save_error;
    }
    // CONV-31b Wave4 fix (V2-P1-1): Python's register_version persists
    // through service._save, which leaves document revision == store
    // revision == _flushed_revision. This repo transaction bumps the store
    // directly, so the in-memory document must land on the SAME
    // post-transaction revision — otherwise the next core save in this
    // session hits stored != flushed and refuses with a bogus #411
    // "modified by another instance" error. The document revision sync is
    // also the ownership proof the core's flush pre-check keys on
    // (service_core.cpp: a document exactly AT the stored revision while
    // the core baseline lags is OUR transaction; a foreign writer cannot
    // move this document). landed == 0 means the post-commit probe failed
    // — keep the document revision untouched rather than regress it.
    if (context.document != nullptr) {
        const int landed = context.repo->current_revision();
        if (landed > 0) {
            context.document->catalog_revision = landed;
        }
    }
    return version;
}

}  // namespace

std::optional<WorkingCopyState> parse_working_copy_state(
    std::string_view value) {
    if (value == "checked_out") return WorkingCopyState::CheckedOut;
    if (value == "dirty") return WorkingCopyState::Dirty;
    if (value == "committing") return WorkingCopyState::Committing;
    return std::nullopt;
}

// ---- staging lease + target keys (db.py 1227-1331 / service.py 1623-1668) --

StagingLeaseGuard::StagingLeaseGuard(CatalogRepository& repo,
                                     std::vector<std::string> targets,
                                     std::string kind)
    : repo_(&repo) {
    // Best-effort: acquire failure → empty id, pre-lease semantics continue.
    std::optional<std::string> lease = repo.acquire_staging_lease(targets, kind);
    if (lease.has_value()) lease_id_ = std::move(*lease);
}

StagingLeaseGuard::~StagingLeaseGuard() {
    if (repo_ != nullptr && !lease_id_.empty()) {
        repo_->release_staging_lease(lease_id_);  // swallows internally
    }
}

StagingLeaseGuard::StagingLeaseGuard(StagingLeaseGuard&& other) noexcept
    : repo_(other.repo_), lease_id_(std::move(other.lease_id_)) {
    other.repo_ = nullptr;
    other.lease_id_.clear();
}

StagingLeaseGuard& StagingLeaseGuard::operator=(
    StagingLeaseGuard&& other) noexcept {
    if (this != &other) {
        if (repo_ != nullptr && !lease_id_.empty()) {
            repo_->release_staging_lease(lease_id_);
        }
        repo_ = other.repo_;
        lease_id_ = std::move(other.lease_id_);
        other.repo_ = nullptr;
        other.lease_id_.clear();
    }
    return *this;
}

std::string staging_target(const fs::path& project_path,
                           std::optional<domain::DataStage> stage,
                           std::optional<std::string_view> asset_id) {
    std::string target = pwb::project::path_to_u8(
        pwb::project::artifact_dir_for(project_path).filename());
    if (stage.has_value()) {
        // The ON-DISK directory name (OUTPUT → "outputs"), never stage.value.
        target += "/";
        target += stage_dir_name(*stage);
    }
    if (asset_id.has_value()) {
        target += "/";
        target.append(*asset_id);
    }
    return target;
}

std::string blob_staging_target(const fs::path& project_path) {
    return pwb::project::path_to_u8(
               pwb::project::artifact_dir_for(project_path).filename())
        + "/blobs";
}

// ---- checkout (service.py create_working_copy 2270-2353) -------------------

domain::Result<fs::path> create_working_copy(
    WorkingCopyContext& context, const domain::VersionId& source_version_id,
    bool allow_replace) {
    const DataVersion* version = context.document->find_version(source_version_id);
    if (version == nullptr) {
        return DataError(ErrorCode::NotFound,
                         "Unknown version: " + source_version_id.str());
    }

    // Reuse ladder step 1: live row for this source (oldest first, all live
    // states — repository read degrades silently to nullopt).
    const std::optional<WorkingCopy> live =
        context.repo->get_live_working_copy_for_source(source_version_id);
    const bool had_live_row = live.has_value();
    const fs::path dir = project_root(context);
    if (live.has_value()) {
        const fs::path existing = dir / fs::path(live->path);
        std::error_code ec;
        if (fs::is_regular_file(existing, ec)) {
            if (!allow_replace) {
                return existing;  // reuse: never clobber uncommitted edits
            }
            discard_row_and_file(context, *live, existing);
        } else {
            // Dead row (save-as/packaging dropped working/): drop it and
            // check out fresh.
            if (context.repo->remove_working_copy(live->working_id).code
                == ErrorCode::Ok) {
                mirror_row_drop(context, live->working_id);
            }
        }
    }

    const fs::path payload =
        resolve_payload_path(context.project_path, *version);
    std::error_code ec;
    if (!fs::is_regular_file(payload, ec)) {
        return DataError(ErrorCode::NotFound,
                         "Payload not available: " + payload.string());
    }

    // Fail-CLOSED on disk evidence (#1211): the registry is bookkeeping and
    // can degrade, but a file at the target path IS uncommitted user work.
    const fs::path disk_existing = working_dir_for(context.project_path)
                                   / source_version_id.str()
                                   / payload.filename();
    if (fs::is_regular_file(disk_existing, ec) && !had_live_row
        && !allow_replace) {
        return disk_existing;
    }

    // Concurrent same-version checkouts converge on one copy: placement
    // writes identical bytes via temp+replace, and a racing replace can
    // transiently collide on Windows — retry with backoff (4 attempts,
    // 0.05s·(n+1)); the loser's bytes are identical anyway. The C++
    // placement surface reports that collision as IoError
    // "working-copy rename failed" (trash.cpp), the narrowest available
    // equivalent of Python's PermissionError catch.
    fs::path target;
    for (int attempt = 0;; ++attempt) {
        auto placed = create_working_copy(context.project_path, payload,
                                          source_version_id.str());
        if (placed.is_ok()) {
            target = std::move(placed.value());
            break;
        }
        const DataError& error = placed.error();
        const bool rename_collision = error.code == ErrorCode::IoError
                                      && error.message
                                             == "working-copy rename failed";
        if (!rename_collision || attempt == 3) {
            return DataError(error);
        }
        std::this_thread::sleep_for(
            std::chrono::milliseconds(50 * (attempt + 1)));
    }

    // Registration (2339-2352): best-effort bookkeeping, never a checkout
    // gate. A duplicate path (DuplicateOperation) is swallowed just like
    // Python's IntegrityError → pass.
    if (const std::optional<std::string> rel = posix_rel_under(target, dir)) {
        const std::optional<std::int64_t> mtime_ns = mtime_ns_of(target);
        const std::optional<std::int64_t> size = version->size_bytes;
        if (context.repo
                ->register_working_copy(source_version_id, *rel,
                                        payload.filename().string(), mtime_ns,
                                        size)
                .is_ok()) {
            if (auto row = context.repo->get_working_copy_by_path(*rel)) {
                mirror_row_upsert(context, *row);
            }
        }
    }
    return target;
}

// ---- status surface (2396-2419) ---------------------------------------------

std::vector<WorkingCopyStatus> list_working_copies(
    WorkingCopyContext& context) {
    std::vector<WorkingCopyStatus> statuses;
    for (const WorkingCopy& row : context.repo->list_working_copies()) {
        statuses.push_back(status_from_row(context, row));
    }
    return statuses;  // registry read failure already degraded to empty
}

std::optional<WorkingCopyStatus> working_copy_state(
    WorkingCopyContext& context, const fs::path& working_path) {
    const std::optional<std::string> rel =
        posix_rel_under(working_path, project_root(context));
    if (!rel.has_value()) return std::nullopt;
    const std::optional<WorkingCopy> row =
        context.repo->get_working_copy_by_path(*rel);
    if (!row.has_value()) return std::nullopt;
    return status_from_row(context, *row);
}

// ---- discard (2433-2463) -----------------------------------------------------

domain::Result<bool> discard_working_copy(WorkingCopyContext& context,
                                          const fs::path& working_path) {
    const std::optional<WorkingCopyStatus> status =
        working_copy_state(context, working_path);
    if (!status.has_value()) {
        std::error_code ec;
        if (fs::is_regular_file(working_path, ec)) {
            safe_unlink_best_effort(working_path);
            return true;  // unregistered stray file
        }
        return false;     // nothing to discard
    }
    if (status->state == WorkingCopyState::Committing) {
        return DataError(
            ErrorCode::InvalidArgument,
            "工作副本正在提交中，不能丢弃；请等待提交完成或重启后恢复。");
    }
    // Re-read the row by path (Python 2453-2459) — the status may be stale.
    const std::optional<std::string> rel =
        posix_rel_under(status->path, project_root(context));
    std::optional<WorkingCopy> row;
    if (rel.has_value()) {
        row = context.repo->get_working_copy_by_path(*rel);
    }
    if (!row.has_value()) return false;
    discard_row_and_file(context, *row, status->path);
    return true;
}

// ---- crash recovery (2465-2523) ----------------------------------------------

WorkingCopyRecovery recover_working_copies(WorkingCopyContext& context) {
    WorkingCopyRecovery recovery;
    // CONV-31b Wave4 fix (V1-P2-2): Python reads the registry FIRST and a
    // read failure returns [] BEFORE the telemetry call (service.py
    // 2478-2481). Its failure surface (db.py _read_rows/_connect) is:
    // a MISSING file reads as [] (no failure), a schema-less but readable
    // file reads as [] (no failure) — only an EXISTING, UNREADABLE store
    // raises. The repository read face degrades all of those to empty
    // silently (B-2), so probe exactly that one failing case here (one
    // cheap statement over a read-only handle; SQLite defers corruption
    // detection to the first statement) and take Python's early exit: no
    // recovery pass, no event.
    {
        const fs::path& db_path = context.repo->path();
        std::error_code probe_ec;
        if (fs::is_regular_file(db_path, probe_ec)) {
            auto opened = Database::open(db_path, SqliteOpenMode::ReadOnly);
            const bool readable =
                opened.is_ok() &&
                opened.value()
                    .scalar_i64("SELECT COUNT(*) FROM sqlite_master")
                    .is_ok();
            if (!readable) return recovery;  // Python `return []`
        }
    }
    const std::vector<WorkingCopy> rows = context.repo->list_working_copies();
    const fs::path dir = project_root(context);

    // source_uri index over committed versions (last duplicate wins, dict
    // comprehension parity).
    std::unordered_map<std::string, const DataVersion*> source_uris;
    for (const DataVersion& v : context.document->versions) {
        if (v.source_uri.has_value() && !v.source_uri->empty()) {
            source_uris[*v.source_uri] = &v;
        }
    }

    for (const WorkingCopy& row : rows) {
        const fs::path path = dir / fs::path(row.path);
        std::error_code ec;
        // Judgment order IS semantics: a missing file drops the row BEFORE
        // the committing branch is ever considered (the W3 crash window
        // honestly lands here).
        if (!fs::is_regular_file(path, ec)) {
            if (context.repo->remove_working_copy(row.working_id).code
                == ErrorCode::Ok) {
                mirror_row_drop(context, row.working_id);
                ++recovery.missing_dropped;
            }
            continue;
        }
        if (row.state == "committing") {
            const auto committed = source_uris.find(resolved_posix(path));
            if (committed != source_uris.end()) {
                // The commit landed (version exists, payload moved); only
                // the row removal was lost.
                if (context.repo->remove_working_copy(row.working_id).code
                    == ErrorCode::Ok) {
                    mirror_row_drop(context, row.working_id);
                    ++recovery.committing_dropped;
                }
            } else {
                // Interrupted mid-commit: the file never moved (the move is
                // copy-then-unlink), so the user's edits are intact.
                if (context.repo
                        ->set_working_copy_state(
                            row.working_id, std::string(to_string(
                                                WorkingCopyState::Dirty)))
                        .code
                    == ErrorCode::Ok) {
                    mirror_row_state(context, row.working_id,
                                     std::string(to_string(
                                         WorkingCopyState::Dirty)));
                    ++recovery.reverted_to_dirty;
                }
            }
        }
    }

    recovery.surviving = list_working_copies(context);
    domain::Json detail = domain::Json::object();
    detail["committing_dropped"] = recovery.committing_dropped;
    detail["reverted_to_dirty"] = recovery.reverted_to_dirty;
    detail["missing_dropped"] = recovery.missing_dropped;
    detail["surviving"] = static_cast<std::int64_t>(recovery.surviving.size());
    record_catalog_event(context.project_path, "working_copy.recovery", detail);
    return recovery;
}

// ---- commit orchestration (2525-2643) ----------------------------------------

domain::Result<DataVersion> commit_working_copy(
    WorkingCopyContext& context, const fs::path& working_path,
    const CommitWorkingCopyRequest& request) {
    // Parent inference (2548-2554): the working-copy directory created by
    // create_working_copy is the source version id.
    std::vector<domain::VersionId> parents;
    if (request.parent_version_ids.has_value()) {
        parents = *request.parent_version_ids;
    } else {
        const std::string candidate = working_path.parent_path()
                                          .filename()
                                          .generic_string();
        if (context.document->find_version(domain::VersionId(candidate))
            != nullptr) {
            parents.push_back(domain::VersionId(candidate));
        }
    }

    // Registry transition (#1211): checked_out/dirty → committing BEFORE the
    // payload moves; legacy copies without a row commit with pre-registry
    // semantics. Crash here is healed by recover_working_copies.
    std::optional<std::string> working_id;
    if (const auto status = working_copy_state(context, working_path)) {
        working_id = status->working_id;
    }
    if (working_id.has_value()) {
        (void)mark_committing(context, working_path);  // best-effort
    }

    domain::Result<DataVersion> committed = [&] {
        if (!request.asset_id.has_value()) {
            // #1218: the payload move+hash must not run under the service
            // lock. The new asset is appended to the in-memory document
            // first (register resolves it), rolled back on failure; the
            // unlocked zero-version window is protected by
            // pending_commit_assets (shared with purge's zombie judgment).
            DataAsset asset;
            asset.id = domain::AssetId(domain::make_id("asset_"));
            asset.name = !request.name.empty()
                             ? request.name
                             : working_path.stem().string();
            asset.type = "unknown";
            asset.metadata = request.metadata;
            asset.created_at = domain::now_iso8601();
            asset.updated_at = domain::now_iso8601();
            context.document->assets.push_back(asset);
            if (context.pending_commit_assets != nullptr) {
                context.pending_commit_assets->insert(asset.id.str());
            }
            auto result = register_working_version(
                context, working_path, asset.id, request.stage, parents,
                request.run_id, request.metadata,
                /*include_asset_row=*/true);
            if (!result.is_ok()) {
                std::erase_if(context.document->assets,
                              [&](const DataAsset& candidate) {
                                  return candidate.id == asset.id;
                              });
            }
            if (context.pending_commit_assets != nullptr) {
                context.pending_commit_assets->erase(asset.id.str());
            }
            return result;
        }
        // Existing asset: name is version metadata["name"] (empty writes no
        // key), so the New Version dialog's input survives persistence.
        domain::Json version_metadata = request.metadata;
        if (!request.name.empty()) {
            version_metadata["name"] = request.name;
        }
        return register_working_version(context, working_path,
                                        *request.asset_id, request.stage,
                                        parents, request.run_id,
                                        version_metadata,
                                        /*include_asset_row=*/false);
    }();

    if (!committed.is_ok()) {
        // The move is atomic inside placement: on failure the file is back
        // at (or never left) the working path — the copy is still live user
        // work, so the row goes back to dirty.
        if (working_id.has_value()) {
            (void)revert_to_dirty(context, *working_id);  // best-effort
        }
        return committed;
    }
    // Success: the payload moved into managed storage and the copy no
    // longer exists — drop the registry row.
    if (working_id.has_value()) {
        (void)drop_row(context, *working_id);  // best-effort
    }
    return committed;
}

// ---- transition primitives (2560-2593; bundle commits reuse these) ----------

bool mark_committing(WorkingCopyContext& context, const fs::path& working_path) {
    const auto status = working_copy_state(context, working_path);
    if (!status.has_value()) return false;
    const std::string state = std::string(to_string(WorkingCopyState::Committing));
    if (context.repo->set_working_copy_state(status->working_id, state).code
        != ErrorCode::Ok) {
        return false;
    }
    mirror_row_state(context, status->working_id, state);
    return true;
}

bool revert_to_dirty(WorkingCopyContext& context,
                     const std::string& working_id) {
    const std::string state = std::string(to_string(WorkingCopyState::Dirty));
    if (context.repo->set_working_copy_state(working_id, state).code
        != ErrorCode::Ok) {
        return false;
    }
    mirror_row_state(context, working_id, state);
    return true;
}

bool drop_row(WorkingCopyContext& context, const std::string& working_id) {
    if (context.repo->remove_working_copy(working_id).code != ErrorCode::Ok) {
        return false;
    }
    mirror_row_drop(context, working_id);
    return true;
}

}  // namespace pwb::catalog
