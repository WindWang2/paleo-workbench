// CommitCoordinator — the single write path turning staged payloads into
// new DataVersions (contracts.md §7): validate → journal → place payload →
// catalog transaction → project save → rebind, with crash recovery via the
// journal directory. Unknown callers (A/C layers) only ever submit
// CommitRequestV1 with already-placed files — never QGIS/Qt/Python types.
#pragma once

#include "pwb/catalog/models.hpp"
#include "pwb/catalog/repository.hpp"
#include "pwb/data/run_contracts.hpp"
#include "pwb/domain/diagnostics.hpp"
#include "pwb/domain/errors.hpp"
#include "pwb/domain/ids.hpp"
#include "pwb/domain/json.hpp"
#include "pwb/domain/stage.hpp"
#include "pwb/project/document.hpp"
#include "pwb/project/manager.hpp"
#include "pwb/project/paths.hpp"
#include "pwb/workspace/state.hpp"

#include <cstdint>
#include <filesystem>
#include <functional>
#include <map>
#include <optional>
#include <string>
#include <vector>

namespace pwb::data {

namespace fs = std::filesystem;

enum class CommitStatus {
    Committed,
    Duplicate,
    Conflict,
    Failed,
    RolledBack,
};

inline constexpr std::string_view to_string(CommitStatus status) {
    switch (status) {
        case CommitStatus::Committed: return "committed";
        case CommitStatus::Duplicate: return "duplicate";
        case CommitStatus::Conflict: return "conflict";
        case CommitStatus::Failed: return "failed";
        case CommitStatus::RolledBack: return "rolled_back";
    }
    return "failed";
}

// Durable phases of one commit operation (journal["phase"] vocabulary).
// RunCompleted sits between Rebound and Completed for run_publish journals:
// the run row only turns terminal AFTER payload, catalog rows and project
// bindings are all durable (v3-contracts.md §6).
enum class JournalPhase {
    Invalid,
    Written,
    PayloadStaged,
    CatalogCommitted,
    ProjectSaved,
    Rebound,
    RunCompleted,
    Completed,
    CleanedUp,
};

inline constexpr std::string_view to_string(JournalPhase phase) {
    switch (phase) {
        case JournalPhase::Invalid: return "invalid";
        case JournalPhase::Written: return "written";
        case JournalPhase::PayloadStaged: return "payload_staged";
        case JournalPhase::CatalogCommitted: return "catalog_committed";
        case JournalPhase::ProjectSaved: return "project_saved";
        case JournalPhase::Rebound: return "rebound";
        case JournalPhase::RunCompleted: return "run_completed";
        case JournalPhase::Completed: return "completed";
        case JournalPhase::CleanedUp: return "cleaned_up";
    }
    return "invalid";
};

// Journal discriminator (v3). Absent in v1 journals → EditCommit.
enum class JournalKind { EditCommit, RunPublish };

inline constexpr std::string_view to_string(JournalKind kind) {
    return kind == JournalKind::RunPublish ? "run_publish" : "edit_commit";
}

// An already-placed producer file handed to B (never a live QGIS feature).
struct StagedAssetV1 {
    fs::path source_path;  // must already exist
    std::optional<std::string> sha256;  // verified when provided
    std::string format;
};

struct CommitRequestV1 {
    domain::OperationId operation_id;  // idempotency key (caller-generated)
    domain::AssetId asset_id;  // target asset (must exist)
    domain::VersionId base_version_id;  // optimistic lock
    domain::DataStage stage = domain::DataStage::Derived;
    StagedAssetV1 staged;
    std::vector<domain::VersionId> parent_version_ids;
    std::optional<domain::RunId> run_id;  // manual_edit run (optional)
    std::optional<domain::LayerId> rebind_layer;  // rebind after success
    std::string version_name;  // → version.metadata["name"] (empty = skip)
};

struct CommitReceiptV1 {
    domain::OperationId operation_id;
    domain::VersionId new_version_id;
    int version_number = 0;
    std::string sha256;  // measured payload hash
    std::uintmax_t size_bytes = 0;
    CommitStatus status = CommitStatus::Failed;
    domain::DiagnosticList diagnostics;
};

enum class PublishStatus {
    Published,
    Duplicate,
    Conflict,
    Failed,
    RolledBack,
};

inline constexpr std::string_view to_string(PublishStatus status) {
    switch (status) {
        case PublishStatus::Published: return "published";
        case PublishStatus::Duplicate: return "duplicate";
        case PublishStatus::Conflict: return "conflict";
        case PublishStatus::Failed: return "failed";
        case PublishStatus::RolledBack: return "rolled_back";
    }
    return "failed";
}

// Single-result publish of one algorithm run (v3-contracts.md §6). The
// products vector mirrors the producer's result set: exactly ONE artifact
// is accepted this round — zero or multiple products are rejected with
// invalid_argument BEFORE any write, never silently trimmed.
struct PublishRequestV1 {
    domain::OperationId operation_id;  // publish idempotency key
    domain::RunId run_id;  // must exist and be "running"
    // Existing target asset; when empty a NEW result asset is created from
    // new_asset_name/new_asset_type (callers never pre-create it).
    std::optional<domain::AssetId> target_asset_id;
    std::string new_asset_name;  // required when target_asset_id is empty
    std::string new_asset_type = "unknown";
    domain::DataStage stage = domain::DataStage::Derived;
    std::vector<StagedAssetV1> products;  // size MUST be 1 this round
    // Descriptive result metadata stored verbatim into version.metadata —
    // units, approximation flags, display hints. B owns the bytes and the
    // transaction, never the numeric encoding (that stays with A).
    domain::Json result_metadata = domain::Json::object();
    std::optional<domain::LayerId> rebind_layer;  // optional workspace rebind
};

struct PublishReceiptV1 {
    domain::OperationId operation_id;
    domain::RunId run_id;
    domain::AssetId asset_id;  // created or existing target
    bool asset_created = false;
    domain::VersionId new_version_id;
    int version_number = 0;
    std::string sha256;  // measured payload hash
    std::uintmax_t size_bytes = 0;
    PublishStatus status = PublishStatus::Failed;
    domain::DiagnosticList diagnostics;
};

struct RecoveryReportV1 {
    std::vector<std::string> continued;  // operation ids resumed to success
    std::vector<std::string> rolled_back;  // operation ids rolled back
    std::vector<std::string> pending;  // awaiting an operator decision
    domain::DiagnosticList diagnostics;
};

// Wall-clock timestamp for journal records (ISO-8601, domain convention).
inline std::string now() { return domain::now_iso8601(); }

class CommitCoordinator {
public:
    // One parsed journal file plus the resume fragments it carries.
    struct JournalRecord {
        domain::Json json = domain::Json::object();
        std::string operation_id;
        domain::VersionId new_version_id;
        JournalPhase phase = JournalPhase::Invalid;
        JournalKind kind = JournalKind::EditCommit;
        CommitReceiptV1 receipt;
        std::optional<domain::RunId> resumed_run_id;
        std::optional<domain::LayerId> resumed_rebind_layer;
        std::vector<domain::VersionId> resumed_parents;
        std::string resumed_format;
        // run_publish fragments needed to resume a publish transaction.
        bool asset_created = false;
        domain::Json asset_json = domain::Json::object();  // new-asset row
        domain::Json result_metadata = domain::Json::object();
    };

    // Fault injection for recovery tests: return an error to abort the
    // commit right AFTER the given phase became durable.
    using FaultHook =
        std::function<std::optional<domain::DataError>(JournalPhase)>;

    CommitCoordinator(project::ProjectManager& manager,
                      catalog::CatalogRepository& repository,
                      fs::path journal_dir);

    domain::Result<CommitReceiptV1> commit(const CommitRequestV1& request,
                                           project::ProjectDocument& document);

    // ---- run lifecycle (v3) ------------------------------------------------
    // Durable "running" registration; idempotent on run_id.
    domain::Result<RunStateV1> register_run(
        const RunRegistrationV1& registration);
    // Explicit algorithm-failure / user-cancel terminal transition. Refused
    // while an unfinished publish journal holds the run (recover first) and
    // refused for runs that already published outputs.
    domain::Result<RunStateV1> finish_run(
        const domain::RunId& run_id, RunTerminalStatus terminal,
        domain::Json extra_parameters);
    // Single-result publish through the same journal machinery. The run
    // turns "complete" only after payload, catalog rows and bindings are
    // all durable; replaying the operation id returns the same receipt.
    domain::Result<PublishReceiptV1> publish_run_result(
        const PublishRequestV1& request,
        project::ProjectDocument& document);
    // Read-only projection of one run row (nullopt when absent).
    std::optional<RunStateV1> run_state(const domain::RunId& run_id) const;

    // Resume/roll back every unfinished journal. Must run at startup before
    // any new commit. Never guesses silently: unresolvable journals land in
    // RecoveryReportV1::pending and BLOCK conflicting new writes until an
    // operator resolves them (the journal file is never auto-deleted).
    RecoveryReportV1 recover(project::ProjectDocument& document);

    std::vector<JournalRecord> load_journals() const;
    std::optional<JournalRecord> find_journal(
        const domain::OperationId& operation_id) const;

    void set_fault_hook(FaultHook hook) { fault_hook_ = std::move(hook); }

private:
    domain::Json journal_json(const CommitRequestV1& request,
                              const catalog::DataVersion& version,
                              const CommitReceiptV1& receipt,
                              JournalPhase phase) const;
    domain::DataError write_journal(const domain::Json& journal);
    domain::Result<CommitReceiptV1> finish_journal_phase4(
        const CommitRequestV1& request, const catalog::DataVersion& version,
        CommitReceiptV1 receipt, project::ProjectDocument& document);
    void apply_rebind(const CommitRequestV1& request,
                      const catalog::DataVersion& version,
                      project::ProjectDocument& document);
    domain::Result<CommitReceiptV1> finish_journal(
        JournalRecord& record, const CommitRequestV1& caller_request,
        project::ProjectDocument& document);
    domain::Result<CommitReceiptV1> rollback_journal(JournalRecord& record);
    // Rejects a new operation when an unfinished journal holds an
    // overlapping target (same asset, run or rebind layer). The same
    // operation id resumes instead — that path is handled by the caller.
    std::optional<domain::Diagnostic> pending_conflict(
        const domain::OperationId& own_operation_id,
        const std::optional<domain::AssetId>& asset_id,
        const std::optional<domain::RunId>& run_id,
        const std::optional<domain::LayerId>& rebind_layer) const;

    project::ProjectManager& manager_;
    catalog::CatalogRepository& repository_;
    fs::path journal_dir_;
    FaultHook fault_hook_;
    std::map<std::string, CommitReceiptV1> receipts_;
};

}  // namespace pwb::data
