#include "pwb/data/commit_coordinator.hpp"

#include "pwb/domain/sha256.hpp"

#include <algorithm>
#include <chrono>
#include <fstream>
#include <sstream>

namespace pwb::data {

using pwb::catalog::CatalogDocument;
using pwb::catalog::DataVersion;
using pwb::domain::DataError;
using pwb::domain::Diagnostic;
using pwb::domain::ErrorCode;
using pwb::domain::Json;
using pwb::domain::Result;

namespace fs = std::filesystem;

namespace {

std::optional<std::string> read_file_text(const fs::path& file) {
    std::ifstream stream(file, std::ios::binary);
    if (!stream) return std::nullopt;
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    if (stream.bad()) return std::nullopt;
    return buffer.str();
}

bool write_file_bytes(const fs::path& file, std::string_view bytes) {
    std::ofstream stream(file, std::ios::binary | std::ios::trunc);
    if (!stream) return false;
    stream.write(bytes.data(),
                 static_cast<std::streamsize>(bytes.size()));
    stream.flush();
    return static_cast<bool>(stream);
}

// Streams source → destination while hashing (place_managed_file parity,
// without the CAS/blob fast path — round 1 scope).
struct PlacedPayload {
    fs::path final_path;
    std::string rel_path;      // project-relative POSIX
    std::uintmax_t size = 0;
    std::string sha256;
};

domain::Result<PlacedPayload> place_payload(const fs::path& source,
                                            const fs::path& project_path,
                                            domain::DataStage stage,
                                            const domain::AssetId& asset_id,
                                            const domain::VersionId& version_id) {
    using R = domain::Result<PlacedPayload>;
    if (!domain::is_safe_storage_segment(asset_id.str()) ||
        !domain::is_safe_storage_segment(version_id.str())) {
        return DataError(ErrorCode::UnsafeId,
                         "asset/version id unsafe as storage segment");
    }
    const fs::path artifacts = pwb::project::artifact_dir_for(project_path);
    const char* stage_dir = stage == domain::DataStage::Raw
                                ? "raw"
                                : (stage == domain::DataStage::Derived
                                       ? "derived"
                                       : (stage == domain::DataStage::Intermediate
                                              ? "intermediate"
                                              : "outputs"));
    const fs::path target_dir =
        artifacts / stage_dir / asset_id.str() / version_id.str();
    std::error_code ec;
    fs::create_directories(target_dir, ec);
    if (ec) {
        return DataError(ErrorCode::IoError,
                         "cannot create payload dir: " + ec.message());
    }
    const fs::path target = target_dir / source.filename();
    if (fs::exists(target, ec)) {
        return DataError(ErrorCode::ImmutableVersion,
                         "managed payload already exists: " +
                             pwb::project::path_to_u8(target));
    }
    const fs::path tmp = target_dir / (".place-" + std::to_string(
        std::chrono::steady_clock::now().time_since_epoch().count()));
    {
        std::ifstream in(source, std::ios::binary);
        if (!in) {
            return DataError(ErrorCode::InvalidArgument,
                             "staged source unreadable: " +
                                 pwb::project::path_to_u8(source));
        }
        std::ofstream out(tmp, std::ios::binary | std::ios::trunc);
        if (!out) {
            return DataError(ErrorCode::IoError, "cannot create payload tmp");
        }
        pwb::domain::Sha256 digest;
        std::string buffer(1 << 20, '\0');
        PlacedPayload placed;
        while (in) {
            in.read(buffer.data(), static_cast<std::streamsize>(buffer.size()));
            const std::streamsize got = in.gcount();
            if (got > 0) {
                out.write(buffer.data(), got);
                digest.update(buffer.data(), static_cast<std::size_t>(got));
                placed.size += static_cast<std::uintmax_t>(got);
            }
        }
        if (in.bad() || !out) {
            std::error_code remove_ec;
            fs::remove(tmp, remove_ec);
            return DataError(ErrorCode::IoError, "payload copy failed");
        }
        placed.sha256 = digest.hex_digest();
        placed.final_path = target;
        // Windows: an open handle (even read-only) blocks rename — the
        // streams must close before the atomic tmp → final move.
        out.close();
        in.close();
        fs::rename(tmp, target, ec);
        if (ec) {
            std::error_code remove_ec;
            fs::remove(tmp, remove_ec);
            return DataError(ErrorCode::IoError, "payload rename failed: " +
                                                     ec.message());
        }
        const fs::path project_dir =
            pwb::project::project_dir_for(project_path);
        placed.rel_path = pwb::project::path_to_u8(fs::weakly_canonical(target, ec)
                              .lexically_relative(
                                  pwb::project::project_dir_for(project_path)));

        if (ec || placed.rel_path.empty()) {
            placed.rel_path = pwb::project::path_to_u8(target);
        }
        return placed;
    }
}

}  // namespace

CommitCoordinator::CommitCoordinator(
    project::ProjectManager& manager, pwb::catalog::CatalogRepository& repository,
    fs::path journal_dir)
    : manager_(manager), repository_(repository),
      journal_dir_(std::move(journal_dir)) {}

std::vector<CommitCoordinator::JournalRecord>
CommitCoordinator::load_journals() const {
    std::vector<JournalRecord> records;
    std::error_code ec;
    if (!fs::is_directory(journal_dir_, ec)) return records;
    for (const auto& entry : fs::directory_iterator(journal_dir_, ec)) {
        if (!entry.is_regular_file(ec)) continue;
        const std::string name = entry.path().filename().generic_string();
        if (name.size() < 5 ||
            name.compare(name.size() - 5, 5, ".json") != 0) {
            continue;
        }
        auto text = read_file_text(entry.path());
        if (!text) continue;
        Json parsed = Json::parse(*text, nullptr, false);
        if (parsed.is_discarded() || !parsed.is_object()) continue;
        JournalRecord record;
        record.json = parsed;
        record.operation_id = parsed.value("operation_id", "");
        record.new_version_id =
            domain::VersionId(parsed.value("new_version_id", ""));
        const std::string phase = parsed.value("phase", "invalid");
        for (int probe = static_cast<int>(JournalPhase::Invalid);
             probe <= static_cast<int>(JournalPhase::CleanedUp); ++probe) {
            if (to_string(static_cast<JournalPhase>(probe)) == phase) {
                record.phase = static_cast<JournalPhase>(probe);
                break;
            }
        }
        if (parsed.contains("receipt") && parsed["receipt"].is_object()) {
            const Json& receipt = parsed["receipt"];
            record.receipt.operation_id =
                domain::OperationId(record.operation_id);
            record.receipt.new_version_id = record.new_version_id;
            record.receipt.version_number = receipt.value("version_number", 0);
            record.receipt.sha256 = receipt.value("sha256", "");
            record.receipt.size_bytes =
                receipt.value("size_bytes", static_cast<std::uintmax_t>(0));
            const std::string status = receipt.value("status", "failed");
            if (status == "committed") {
                record.receipt.status = CommitStatus::Committed;
            } else if (status == "duplicate") {
                record.receipt.status = CommitStatus::Duplicate;
            } else if (status == "rolled_back") {
                record.receipt.status = CommitStatus::RolledBack;
            }
        }
        // Request fragments needed to RESUME an interrupted operation.
        // Note: value() only defaults MISSING keys — explicit nulls throw,
        // so optional fragments are read null-safely here.
        const auto run_it = parsed.find("run_id");
        if (run_it != parsed.end() && run_it->is_string() &&
            !run_it->get<std::string>().empty()) {
            record.resumed_run_id =
                domain::RunId(run_it->get<std::string>());
        }
        const auto rebind_it = parsed.find("rebind_layer");
        if (rebind_it != parsed.end() && rebind_it->is_string() &&
            !rebind_it->get<std::string>().empty()) {
            record.resumed_rebind_layer =
                domain::LayerId(rebind_it->get<std::string>());
        }
        if (parsed.contains("parent_version_ids") &&
            parsed["parent_version_ids"].is_array()) {
            for (const auto& parent : parsed["parent_version_ids"]) {
                if (parent.is_string()) {
                    record.resumed_parents.emplace_back(
                        parent.get<std::string>());
                }
            }
        }
        if (parsed.contains("format")) {
            record.resumed_format = parsed.value("format", "");
        }
        records.push_back(std::move(record));
    }
    std::sort(records.begin(), records.end(),
              [](const JournalRecord& a, const JournalRecord& b) {
                  return a.operation_id < b.operation_id;
              });
    return records;
}

std::optional<CommitCoordinator::JournalRecord>
CommitCoordinator::find_journal(const domain::OperationId& operation_id) const {
    for (const auto& record : load_journals()) {
        if (record.operation_id == operation_id.str()) return record;
    }
    return std::nullopt;
}

Json CommitCoordinator::journal_json(const CommitRequestV1& request,
                                     const DataVersion& version,
                                     const CommitReceiptV1& receipt,
                                     JournalPhase phase) const {
    Json journal = Json::object();
    journal["journal_version"] = 1;
    journal["operation_id"] = request.operation_id.str();
    journal["phase"] = to_string(phase);
    journal["updated_at"] = now();
    journal["asset_id"] = request.asset_id.str();
    journal["base_version_id"] = request.base_version_id.str();
    journal["new_version_id"] = version.id.str();
    journal["stage"] = std::string(domain::to_string(version.stage));
    journal["payload_rel_path"] = version.path;
    journal["source_uri"] = version.source_uri.value_or("");
    journal["format"] = version.format;
    journal["parent_version_ids"] = Json::array();
    for (const auto& parent : version.parent_version_ids) {
        journal["parent_version_ids"].push_back(parent.str());
    }
    journal["run_id"] = request.run_id.has_value()
                            ? Json(request.run_id->str())
                            : Json(nullptr);
    journal["rebind_layer"] = request.rebind_layer.has_value()
                                  ? Json(request.rebind_layer->str())
                                  : Json(nullptr);
    Json receipt_json = Json::object();
    receipt_json["status"] = to_string(receipt.status);
    receipt_json["version_number"] = receipt.version_number;
    receipt_json["sha256"] = receipt.sha256;
    receipt_json["size_bytes"] = receipt.size_bytes;
    journal["receipt"] = std::move(receipt_json);
    return journal;
}

domain::DataError CommitCoordinator::write_journal(const Json& journal) {
    std::error_code ec;
    fs::create_directories(journal_dir_, ec);
    const fs::path file =
        journal_dir_ / (journal.value("operation_id", "") + ".json");
    // Atomic journal write: tmp + rename, fsync'd via flush.
    const fs::path tmp = journal_dir_ /
                         ("." + journal.value("operation_id", "") + ".tmp");
    if (!write_file_bytes(tmp, journal.dump(2))) {
        return DataError(ErrorCode::IoError, "journal write failed");
    }
    fs::rename(tmp, file, ec);
    if (ec) {
        return DataError(ErrorCode::IoError,
                         "journal rename failed: " + ec.message());
    }
    return DataError(ErrorCode::Ok, "");
}

Result<CommitReceiptV1> CommitCoordinator::commit(
    const CommitRequestV1& request, project::ProjectDocument& document) {
    // ---- Idempotency: same operation id → replay the recorded receipt.
    if (auto existing = find_journal(request.operation_id)) {
        CommitReceiptV1 receipt = existing->receipt;
        if (existing->phase == JournalPhase::Completed ||
            existing->phase == JournalPhase::CleanedUp) {
            if (receipt.status == CommitStatus::Committed) {
                receipt.status = CommitStatus::Duplicate;
                receipt.diagnostics.push_back(Diagnostic::info(
                    "operation_replayed",
                    "operation id already committed — receipt replayed, no "
                    "second version"));
            }
            return receipt;
        }
        if (existing->phase == JournalPhase::Written ||
            existing->phase == JournalPhase::PayloadStaged ||
            existing->phase == JournalPhase::CatalogCommitted) {
            // Unfinished journal from an earlier crash: resume it now.
            CommitRequestV1 resumed = request;
            return finish_journal(*existing, resumed, document);
        }
        if (receipt.status == CommitStatus::RolledBack) {
            receipt.diagnostics.push_back(Diagnostic::info(
                "operation_rolled_back",
                "previous attempt was rolled back — new attempt proceeds"));
        }
    }

    // ---- Validation gate.
    CommitReceiptV1 receipt;
    receipt.operation_id = request.operation_id;
    if (document.read_only()) {
        receipt.diagnostics.push_back(Diagnostic::error(
            "read_only", "project is read-only (future schema)"));
        return receipt;
    }
    if (!fs::is_regular_file(request.staged.source_path)) {
        receipt.diagnostics.push_back(Diagnostic::error(
            "staged_missing",
            "staged asset does not exist: " +
                pwb::project::path_to_u8(request.staged.source_path)));
        return receipt;
    }
    if (request.staged.sha256.has_value()) {
        const auto digest =
            domain::Sha256::of_file(request.staged.source_path);
        if (!digest.has_value() || *digest != *request.staged.sha256) {
            receipt.diagnostics.push_back(Diagnostic::error(
                "staged_hash_mismatch",
                "staged asset hash mismatch (expected " +
                    *request.staged.sha256 + ")"));
            return receipt;
        }
    }

    auto document_result = repository_.open_read_only();
    if (!document_result.is_ok()) {
        receipt.diagnostics.push_back(Diagnostic::error(
            "catalog_unavailable", document_result.error().message));
        return receipt;
    }
    CatalogDocument catalog = std::move(document_result.value());
    const pwb::catalog::DataAsset* asset =
        catalog.find_asset(request.asset_id);
    if (asset == nullptr) {
        receipt.diagnostics.push_back(Diagnostic::error(
            "unknown_asset", "asset not found: " + request.asset_id.str()));
        return receipt;
    }
    // ---- Optimistic lock: base must be the asset's current version.
    if (!asset->current_version_id.has_value() ||
        *asset->current_version_id != request.base_version_id) {
        receipt.status = CommitStatus::Conflict;
        receipt.diagnostics.push_back(Diagnostic::error(
            "base_version_conflict",
            "base version is not the asset's current version",
            Json{{"base", request.base_version_id.str()},
                 {"current",
                  asset->current_version_id.has_value()
                      ? asset->current_version_id->str()
                      : ""}}));
        return receipt;
    }

    DataVersion version;
    version.id = domain::VersionId(domain::make_id("ver_"));
    version.asset_id = request.asset_id;
    version.stage = request.stage;
    version.managed = true;
    version.source_uri =
        pwb::project::path_to_u8(fs::weakly_canonical(request.staged.source_path));
    version.format = request.staged.format;
    version.run_id = request.run_id;
    version.metadata = Json::object();
    if (!request.version_name.empty()) {
        version.metadata["name"] = request.version_name;
    }
    version.created_at = now();
    version.parent_version_ids = request.parent_version_ids;

    // Phase 1: journal durable BEFORE anything else.
    version.version_number = catalog.next_version_number(request.asset_id);
    version.path = "";  // filled after placement
    receipt.status = CommitStatus::Failed;
    receipt.new_version_id = version.id;
    auto error = write_journal(
        journal_json(request, version, receipt, JournalPhase::Written));
    if (error.code != ErrorCode::Ok) {
        receipt.diagnostics.push_back(
            Diagnostic::error("journal_failure", error.message));
        return receipt;
    }
    if (fault_hook_) {
        if (auto fault = fault_hook_(JournalPhase::Written)) {
            receipt.diagnostics.push_back(Diagnostic::error(
                "fault_injected", fault->message));
            return receipt;
        }
    }

    // Phase 2: payload placement (outside catalog transaction).
    auto placed = place_payload(request.staged.source_path,
                                manager_.path(), request.stage,
                                request.asset_id, version.id);
    if (!placed.is_ok()) {
        receipt.diagnostics.push_back(
            Diagnostic::error("payload_failure", placed.error().message));
        write_journal(
            journal_json(request, version, receipt, JournalPhase::Written));
        return receipt;
    }
    version.path = placed.value().rel_path;
    version.size_bytes =
        static_cast<std::int64_t>(placed.value().size);
    version.sha256 = placed.value().sha256;
    receipt.sha256 = placed.value().sha256;
    receipt.size_bytes = placed.value().size;
    error = write_journal(journal_json(request, version, receipt,
                                       JournalPhase::PayloadStaged));
    if (fault_hook_) {
        if (auto fault = fault_hook_(JournalPhase::PayloadStaged)) {
            receipt.diagnostics.push_back(Diagnostic::error(
                "fault_injected", fault->message));
            return receipt;
        }
    }

    // Phase 3: catalog transaction (single SQLite transaction).
    auto writable = repository_.open_read_write();
    if (!writable.is_ok()) {
        receipt.diagnostics.push_back(Diagnostic::error(
            "catalog_unavailable", writable.error().message));
        return receipt;
    }
    error = repository_.commit_version_transaction(
        version, request.asset_id, request.run_id);
    if (error.code != ErrorCode::Ok) {
        receipt.diagnostics.push_back(Diagnostic::error(
            "catalog_commit_failure", error.message));
        return receipt;
    }
    receipt.version_number = version.version_number;
    receipt.status = CommitStatus::Committed;
    error = write_journal(journal_json(request, version, receipt,
                                       JournalPhase::CatalogCommitted));
    if (fault_hook_) {
        if (auto fault = fault_hook_(JournalPhase::CatalogCommitted)) {
            receipt.diagnostics.push_back(Diagnostic::error(
                "fault_injected", fault->message));
            return receipt;
        }
    }

    return finish_journal_phase4(request, version, receipt, document);
}

Result<CommitReceiptV1> CommitCoordinator::finish_journal_phase4(
    const CommitRequestV1& request, const DataVersion& version,
    CommitReceiptV1 receipt, project::ProjectDocument& document) {
    // Phase 4: project file (atomic replace via ProjectManager).
    apply_rebind(request, version, document);
    auto saved = manager_.save(document);
    if (!saved.is_ok()) {
        receipt.status = CommitStatus::Failed;
        receipt.diagnostics.push_back(Diagnostic::error(
            "project_save_failure", saved.error().message));
        return receipt;
    }
    write_journal(
        journal_json(request, version, receipt, JournalPhase::ProjectSaved));
    if (fault_hook_) {
        if (auto fault = fault_hook_(JournalPhase::ProjectSaved)) {
            receipt.status = CommitStatus::Failed;
            receipt.diagnostics.push_back(Diagnostic::error(
                "fault_injected", fault->message));
            return receipt;
        }
    }

    write_journal(
        journal_json(request, version, receipt, JournalPhase::Rebound));
    write_journal(
        journal_json(request, version, receipt, JournalPhase::Completed));
    write_journal(
        journal_json(request, version, receipt, JournalPhase::CleanedUp));

    // Terminal journal removal: Completed is the durable success marker;
    // the journal file itself is evidence and stays until cleanup removes
    // it after the receipt was observed. Round 1: keep the file (audit
    // trail), mark CleanedUp.
    receipts_[request.operation_id.str()] = receipt;
    return receipt;
}

void CommitCoordinator::apply_rebind(const CommitRequestV1& request,
                                     const DataVersion& version,
                                     project::ProjectDocument& document) {
    if (!request.rebind_layer.has_value()) return;
    workspace::ensure_mapping_workspace(document.root());
    domain::Json& ws = document.root()["mapping_workspace"];
    if (ws.contains("memberships") &&
        ws["memberships"].contains(request.rebind_layer->str())) {
        domain::Json& membership =
            ws["memberships"][request.rebind_layer->str()];
        membership["source_asset_id"] = request.asset_id.str();
        membership["source_version_id"] = version.id.str();
        membership["binding_kind"] = "catalog_version";
        membership["bound_at"] = now();
    }
}

Result<CommitReceiptV1> CommitCoordinator::finish_journal(
    JournalRecord& record, const CommitRequestV1& caller_request,
    project::ProjectDocument& document) {
    // Resume from the recorded phase: everything before it already happened.
    // The journal's own fragments win over the caller's input — a recovery
    // pass has no original request at all.
    CommitRequestV1 request = caller_request;
    request.operation_id = domain::OperationId(record.operation_id);
    request.asset_id = domain::AssetId(record.json.value("asset_id", ""));
    request.base_version_id =
        domain::VersionId(record.json.value("base_version_id", ""));
    if (record.resumed_run_id.has_value()) {
        request.run_id = record.resumed_run_id;
    }
    if (record.resumed_rebind_layer.has_value()) {
        request.rebind_layer = record.resumed_rebind_layer;
    }
    if (!record.resumed_parents.empty()) {
        request.parent_version_ids = record.resumed_parents;
    }

    DataVersion version;
    version.id = record.new_version_id;
    version.asset_id = request.asset_id;
    version.path = record.json.value("payload_rel_path", "");
    version.source_uri = record.json.value("source_uri", "");
    version.format = record.resumed_format;
    version.parent_version_ids = request.parent_version_ids;
    const auto stage = domain::data_stage_from_string(
        record.json.value("stage", "derived"));
    version.stage = stage.value_or(domain::DataStage::Derived);
    version.created_at = record.json.value("updated_at", now());

    CommitReceiptV1 receipt = record.receipt;
    receipt.operation_id = domain::OperationId(record.operation_id);
    if (record.phase == JournalPhase::CatalogCommitted ||
        record.phase == JournalPhase::ProjectSaved ||
        record.phase == JournalPhase::Rebound) {
        // Everything durable already happened (SQLite row + payload, and
        // possibly the project file too) → finalize the journals only.
        receipt.status = CommitStatus::Committed;
        if (record.phase != JournalPhase::Rebound &&
            request.rebind_layer.has_value()) {
            apply_rebind(request, version, document);
            auto saved = manager_.save(document);
            if (!saved.is_ok()) {
                receipt.status = CommitStatus::Failed;
                receipt.diagnostics.push_back(Diagnostic::error(
                    "project_save_failure", saved.error().message));
                return receipt;
            }
        }
        write_journal(journal_json(request, version, receipt,
                                   JournalPhase::ProjectSaved));
        write_journal(journal_json(request, version, receipt,
                                   JournalPhase::Rebound));
        write_journal(journal_json(request, version, receipt,
                                   JournalPhase::Completed));
        write_journal(journal_json(request, version, receipt,
                                   JournalPhase::CleanedUp));
        return receipt;
    }
    if (record.phase == JournalPhase::PayloadStaged) {
        // Payload landed, catalog not → finish the catalog transaction.
        auto writable = repository_.open_read_write();
        if (!writable.is_ok()) {
            receipt.diagnostics.push_back(Diagnostic::error(
                "catalog_unavailable", writable.error().message));
            return receipt;
        }
        auto reloaded = repository_.open_read_only();
        if (reloaded.is_ok()) {
            version.version_number =
                reloaded.value().next_version_number(version.asset_id);
            if (const DataVersion* existing =
                    reloaded.value().find_version(version.id)) {
                version.version_number = existing->version_number;
            }
        }
        version.size_bytes =
            static_cast<std::int64_t>(receipt.size_bytes);
        version.sha256 = receipt.sha256;
        auto error = repository_.commit_version_transaction(
            version, version.asset_id, request.run_id);
        if (error.code != ErrorCode::Ok) {
            receipt.diagnostics.push_back(Diagnostic::error(
                "catalog_commit_failure", error.message));
            return receipt;
        }
        receipt.version_number = version.version_number;
        receipt.status = CommitStatus::Committed;
        write_journal(journal_json(request, version, receipt,
                                   JournalPhase::CatalogCommitted));
        return finish_journal_phase4(request, version, receipt, document);
    }
    if (record.phase == JournalPhase::Written) {
        // Only the journal exists → nothing durable happened → roll back.
        return rollback_journal(record);
    }
    return rollback_journal(record);
}

Result<CommitReceiptV1> CommitCoordinator::rollback_journal(
    JournalRecord& record) {
    CommitReceiptV1 receipt = record.receipt;
    receipt.operation_id = domain::OperationId(record.operation_id);
    receipt.status = CommitStatus::RolledBack;
    // Payload staged but catalog never committed → remove the payload dir
    // (it is owned by this operation alone) and the journal marker.
    const std::string rel = record.json.value("payload_rel_path", "");
    if (record.phase == JournalPhase::PayloadStaged && !rel.empty()) {
        std::error_code ec;
        const fs::path project_dir =
            pwb::project::project_dir_for(manager_.path());
        const fs::path payload = fs::weakly_canonical(project_dir / pwb::project::path_from_u8(rel), ec);
        if (fs::is_directory(payload.parent_path(), ec)) {
            std::error_code remove_ec;
            fs::remove_all(payload.parent_path(), remove_ec);
        }
    }
    Json journal = record.json;
    journal["phase"] = to_string(JournalPhase::CleanedUp);
    Json receipt_json = Json::object();
    receipt_json["status"] = to_string(CommitStatus::RolledBack);
    receipt_json["version_number"] = receipt.version_number;
    receipt_json["sha256"] = receipt.sha256;
    receipt_json["size_bytes"] = receipt.size_bytes;
    journal["receipt"] = std::move(receipt_json);
    write_journal(journal);
    receipt.diagnostics.push_back(Diagnostic::warning(
        "journal_rolled_back",
        "interrupted operation " + record.operation_id +
            " rolled back; staged payload removed",
        Json{{"payload", rel}}));
    return receipt;
}

RecoveryReportV1 CommitCoordinator::recover(
    project::ProjectDocument& document) {
    RecoveryReportV1 report;
    for (auto& record : load_journals()) {
        if (record.phase == JournalPhase::Completed ||
            record.phase == JournalPhase::CleanedUp) {
            if (record.receipt.status == CommitStatus::RolledBack) {
                report.rolled_back.push_back(record.operation_id);
            } else {
                report.continued.push_back(record.operation_id);
            }
            continue;
        }
        CommitRequestV1 request;
        request.operation_id = domain::OperationId(record.operation_id);
        request.asset_id =
            domain::AssetId(record.json.value("asset_id", ""));
        request.base_version_id = domain::VersionId(
            record.json.value("base_version_id", ""));
        request.run_id = std::nullopt;
        request.rebind_layer = std::nullopt;
        auto outcome = finish_journal(record, request, document);
        if (outcome.is_ok() &&
            (outcome.value().status == CommitStatus::Committed ||
             outcome.value().status == CommitStatus::RolledBack)) {
            if (outcome.value().status == CommitStatus::RolledBack) {
                report.rolled_back.push_back(record.operation_id);
            } else {
                report.continued.push_back(record.operation_id);
            }
        } else {
            report.pending.push_back(record.operation_id);
            report.diagnostics.push_back(Diagnostic::warning(
                "recovery_pending",
                "journal " + record.operation_id +
                    " could not be auto-resolved — awaiting decision"));
        }
    }
    return report;
}

}  // namespace pwb::data
