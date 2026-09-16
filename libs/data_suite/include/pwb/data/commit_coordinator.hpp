// CommitCoordinator — the single write path turning staged payloads into
// new DataVersions (contracts.md §7): validate → journal → place payload →
// catalog transaction → project save → rebind, with crash recovery via the
// journal directory. Unknown callers (A/C layers) only ever submit
// CommitRequestV1 with already-placed files — never QGIS/Qt/Python types.
#pragma once

#include "pwb/catalog/models.hpp"
#include "pwb/catalog/repository.hpp"
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
enum class JournalPhase {
    Invalid,
    Written,
    PayloadStaged,
    CatalogCommitted,
    ProjectSaved,
    Rebound,
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
        case JournalPhase::Completed: return "completed";
        case JournalPhase::CleanedUp: return "cleaned_up";
    }
    return "invalid";
};

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
        CommitReceiptV1 receipt;
        std::optional<domain::RunId> resumed_run_id;
        std::optional<domain::LayerId> resumed_rebind_layer;
        std::vector<domain::VersionId> resumed_parents;
        std::string resumed_format;
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

    // Resume/roll back every unfinished journal. Must run at startup before
    // any new commit. Never guesses silently: unresolvable journals land in
    // RecoveryReportV1::pending.
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

    project::ProjectManager& manager_;
    catalog::CatalogRepository& repository_;
    fs::path journal_dir_;
    FaultHook fault_hook_;
    std::map<std::string, CommitReceiptV1> receipts_;
};

}  // namespace pwb::data
