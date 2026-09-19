// Run lifecycle + single-result publish (v3-contracts.md §3/§5/§6) over
// the SAME CommitCoordinator journal machinery: validate → journal →
// payload → catalog transaction → project save → run terminal → complete.
// The run row only turns terminal after payload, catalog rows and project
// bindings are all durable.
#include "pwb/data/commit_coordinator.hpp"

#include "coordinator_detail.hpp"

#include <algorithm>

namespace pwb::data {

using pwb::catalog::CatalogDocument;
using pwb::catalog::DataAsset;
using pwb::catalog::DataRun;
using pwb::catalog::DataVersion;
using pwb::domain::DataError;
using pwb::domain::Diagnostic;
using pwb::domain::ErrorCode;
using pwb::domain::Json;
using pwb::domain::Result;

namespace fs = std::filesystem;

namespace {

RunStateV1 project_run(const DataRun& run) {
    RunStateV1 state;
    state.run_id = run.id;
    state.operation = run.operation;
    state.generator = run.generator;
    state.status = run.status;
    state.input_version_ids = run.input_version_ids;
    state.output_version_ids = run.output_version_ids;
    state.input_ports = run.input_ports;
    state.output_ports = run.output_ports;
    state.parameters = run.parameters;
    state.model_ref = run.model_ref;
    state.created_at = run.created_at;
    return state;
}

Json asset_row_json(const DataAsset& asset) {
    Json json = Json::object();
    json["id"] = asset.id.str();
    json["name"] = asset.name;
    json["type"] = asset.type;
    json["description"] = asset.description;
    json["metadata"] = asset.metadata;
    json["created_at"] = asset.created_at;
    json["updated_at"] = asset.updated_at;
    return json;
}

DataAsset asset_from_json(const Json& json, const domain::AssetId& fallback) {
    DataAsset asset;
    asset.id = domain::AssetId(json.value("id", fallback.str()));
    asset.name = json.value("name", "");
    asset.type = json.value("type", "unknown");
    asset.description = json.value("description", "");
    if (json.contains("metadata") && json["metadata"].is_object()) {
        asset.metadata = json["metadata"];
    }
    asset.created_at = json.value("created_at", "");
    asset.updated_at = json.value("updated_at", "");
    return asset;
}

// Runs carry no ports of their own in the publish path; inputs resolve
// from the run row at publish time (parents = run.input_version_ids).
bool run_has_pending_journal(const std::vector<
    CommitCoordinator::JournalRecord>& journals,
                             const domain::RunId& run_id) {
    for (const auto& record : journals) {
        const auto& field = record.json["run_id"];
        if (!field.is_string() || field.get<std::string>() != run_id.str()) {
            continue;
        }
        if (record.phase == JournalPhase::Written ||
            record.phase == JournalPhase::PayloadStaged ||
            record.phase == JournalPhase::CatalogCommitted ||
            record.phase == JournalPhase::ProjectSaved ||
            record.phase == JournalPhase::Rebound ||
            record.phase == JournalPhase::RunCompleted) {
            return true;
        }
    }
    return false;
}

}  // namespace

Json run_state_to_json(const RunStateV1& state) {
    Json json = Json::object();
    json["run_id"] = state.run_id.str();
    json["operation"] = state.operation;
    json["generator"] = state.generator;
    json["status"] = state.status;
    json["input_version_ids"] = Json::array();
    for (const auto& input : state.input_version_ids) {
        json["input_version_ids"].push_back(input.str());
    }
    json["output_version_ids"] = Json::array();
    for (const auto& output : state.output_version_ids) {
        json["output_version_ids"].push_back(output.str());
    }
    json["input_ports"] = Json::array();
    for (const auto& port : state.input_ports) {
        json["input_ports"].push_back(
            {{"role", port.role},
             {"version_id", port.version_id.str()},
             {"ordinal", port.ordinal},
             {"required", port.required},
             {"entity_type", port.entity_type},
             {"entity_id", port.entity_id},
             {"note", port.note}});
    }
    json["output_ports"] = Json::array();
    for (const auto& port : state.output_ports) {
        json["output_ports"].push_back(
            {{"role", port.role},
             {"version_id", port.version_id.str()},
             {"ordinal", port.ordinal},
             {"required", port.required},
             {"entity_type", port.entity_type},
             {"entity_id", port.entity_id},
             {"note", port.note}});
    }
    json["parameters"] = state.parameters;
    json["model_ref"] =
        state.model_ref.has_value() ? *state.model_ref : Json(nullptr);
    json["created_at"] = state.created_at;
    return json;
}

// ---------------------------------------------------------------------------
// register_run / run_state / finish_run
// ---------------------------------------------------------------------------

Result<RunStateV1> CommitCoordinator::register_run(
    const RunRegistrationV1& registration) {
    const std::lock_guard<std::recursive_mutex> lock(mutex_);
    if (registration.run_id.empty()) {
        return DataError(ErrorCode::InvalidArgument, "run_id is required");
    }
    if (registration.operation.empty()) {
        return DataError(ErrorCode::InvalidArgument,
                         "run operation is required");
    }
    // Port ⊆ input invariant (single-writer core, adapter.py parity).
    for (const auto& port : registration.input_ports) {
        const bool member = std::any_of(
            registration.input_version_ids.begin(),
            registration.input_version_ids.end(),
            [&](const domain::VersionId& id) { return id == port.version_id; });
        if (!member) {
            return DataError(
                ErrorCode::InvalidArgument,
                "input port version " + port.version_id.str() +
                    " is not a member of input_version_ids");
        }
    }

    // Idempotent on run_id: an existing row is returned, never duplicated.
    if (auto existing = run_state(registration.run_id)) {
        RunStateV1 state = *existing;
        if (state.status == std::string(kRunStatusRunning)) {
            state.parameters["run_registered_earlier"] = true;
        } else {
            state.parameters["run_registered_earlier"] =
                "terminal:" + state.status;
        }
        return state;
    }

    DataRun run;
    run.id = registration.run_id;
    run.operation = registration.operation;
    run.generator = registration.generator;
    run.parameters = registration.parameters;
    run.input_version_ids = registration.input_version_ids;
    run.input_ports = registration.input_ports;
    run.model_ref = registration.model_ref;
    run.status = kRunStatusRunning;
    run.created_at = now();

    auto writable = repository_.open_read_write();
    if (!writable.is_ok()) {
        return writable.error();
    }
    auto error = repository_.upsert_run(run);
    if (error.code != ErrorCode::Ok) return error;
    return project_run(run);
}

std::optional<RunStateV1> CommitCoordinator::run_state(
    const domain::RunId& run_id) const {
    const std::lock_guard<std::recursive_mutex> lock(mutex_);
    auto catalog = repository_.open_read_only();
    if (!catalog.is_ok()) return std::nullopt;
    const DataRun* run = catalog.value().find_run(run_id);
    if (run == nullptr) return std::nullopt;
    return project_run(*run);
}

Result<RunStateV1> CommitCoordinator::finish_run(
    const domain::RunId& run_id, RunTerminalStatus terminal,
    Json extra_parameters) {
    const std::lock_guard<std::recursive_mutex> lock(mutex_);
    auto current = run_state(run_id);
    if (!current.has_value()) {
        return DataError(ErrorCode::NotFound, "run not found: " + run_id.str());
    }
    // A publish journal still holding this run must be resolved first.
    if (run_has_pending_journal(load_journals(), run_id)) {
        return DataError(ErrorCode::RecoveryRequired,
                         "unfinished publish journal holds run " +
                             run_id.str() + " — recover() first");
    }
    const std::string target(to_string(terminal));
    if (is_run_status_terminal(current->status)) {
        if (current->status == target) {
            current->parameters["finish_run_earlier"] = target;
            return *current;  // idempotent replay of the same terminal state
        }
        return DataError(ErrorCode::ConflictBaseVersion,
                         "cannot change terminal run " + run_id.str() +
                             " from '" + current->status + "' to '" + target +
                             "' (retry creates a new run)");
    }
    if (!current->output_version_ids.empty()) {
        return DataError(ErrorCode::ImmutableVersion,
                         "run " + run_id.str() +
                             " already published outputs — cannot turn it " +
                             target);
    }
    if (!extra_parameters.is_object()) extra_parameters = Json::object();
    extra_parameters["_finished_at"] = now();
    auto writable = repository_.open_read_write();
    if (!writable.is_ok()) return writable.error();
    auto error =
        repository_.finish_run_transaction(run_id, target, extra_parameters);
    if (error.code != ErrorCode::Ok) return error;
    auto after = run_state(run_id);
    if (!after.has_value()) {
        return DataError(ErrorCode::Unknown, "run vanished after finish");
    }
    return *after;
}

// ---------------------------------------------------------------------------
// publish_run_result
// ---------------------------------------------------------------------------

namespace {

Json publish_journal_json(const PublishRequestV1& request,
                          const domain::AssetId& resolved_asset,
                          bool asset_created, const DataAsset* new_asset,
                          const DataVersion& version,
                          const PublishReceiptV1& receipt,
                          JournalPhase phase) {
    Json journal = Json::object();
    journal["journal_version"] = 1;
    journal["kind"] = to_string(JournalKind::RunPublish);
    journal["operation_id"] = request.operation_id.str();
    journal["phase"] = to_string(phase);
    journal["updated_at"] = now();
    journal["new_version_id"] = version.id.str();
    journal["asset_id"] = resolved_asset.str();
    journal["asset_created"] = asset_created;
    if (asset_created && new_asset != nullptr) {
        journal["asset_json"] = asset_row_json(*new_asset);
    }
    journal["run_id"] = request.run_id.str();
    journal["stage"] = std::string(domain::to_string(version.stage));
    journal["payload_rel_path"] = version.path;
    journal["source_uri"] = version.source_uri.value_or("");
    journal["format"] = version.format;
    journal["parent_version_ids"] = Json::array();
    for (const auto& parent : version.parent_version_ids) {
        journal["parent_version_ids"].push_back(parent.str());
    }
    journal["result_metadata"] =
        version.metadata;  // verbatim resume fragment
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

PublishReceiptV1 publish_receipt_from_journal(
    const CommitCoordinator::JournalRecord& record) {
    PublishReceiptV1 receipt;
    receipt.operation_id = domain::OperationId(record.operation_id);
    receipt.run_id = domain::RunId(record.json.value("run_id", ""));
    receipt.asset_id = domain::AssetId(record.json.value("asset_id", ""));
    receipt.asset_created = record.asset_created;
    receipt.new_version_id = record.new_version_id;
    if (record.json.contains("receipt") &&
        record.json["receipt"].is_object()) {
        const Json& saved = record.json["receipt"];
        receipt.version_number = saved.value("version_number", 0);
        receipt.sha256 = saved.value("sha256", "");
        receipt.size_bytes =
            saved.value("size_bytes", static_cast<std::uintmax_t>(0));
    }
    return receipt;
}

}  // namespace

Result<PublishReceiptV1> CommitCoordinator::publish_run_result(
    const PublishRequestV1& request, project::ProjectDocument& document) {
    const std::lock_guard<std::recursive_mutex> lock(mutex_);
    // ---- Validation gate: NOTHING is written before every check passes.
    PublishReceiptV1 receipt;
    receipt.operation_id = request.operation_id;
    receipt.run_id = request.run_id;
    if (request.products.size() != 1) {
        receipt.diagnostics.push_back(Diagnostic::error(
            "publish_requires_single_product",
            "publish accepts exactly one result artifact this round (got " +
                std::to_string(request.products.size()) + ")",
            Json{{"product_count", request.products.size()}}));
        return receipt;
    }
    if (!domain::is_safe_storage_segment(request.operation_id.str())) {
        receipt.diagnostics.push_back(Diagnostic::error(
            "unsafe_operation_id",
            "operation id is used as the journal file name and must match "
            "[A-Za-z0-9._-] without a leading dot"));
        return receipt;
    }
    if (document.read_only()) {
        receipt.diagnostics.push_back(Diagnostic::error(
            "read_only", "project is read-only (future schema)"));
        return receipt;
    }

    // ---- Idempotency: same operation id → replay or resume.
    if (auto existing = find_journal(request.operation_id)) {
        if (existing->kind != JournalKind::RunPublish) {
            receipt.diagnostics.push_back(Diagnostic::error(
                "operation_id_kind_mismatch",
                "operation id belongs to an edit_commit journal"));
            return receipt;
        }
        if (existing->phase == JournalPhase::Completed ||
            existing->phase == JournalPhase::CleanedUp) {
            const std::string prior_status =
                existing->json.contains("receipt") &&
                        existing->json["receipt"].is_object()
                    ? existing->json["receipt"].value("status", "")
                    : "";
            if (prior_status == "rolled_back") {
                // The id is free again: a new attempt proceeds below with a
                // fresh version id (the journal is rewritten).
            } else {
                PublishReceiptV1 replay =
                    publish_receipt_from_journal(*existing);
                replay.status =
                    prior_status == "published"
                        ? PublishStatus::Duplicate
                        : PublishStatus::Failed;
                replay.diagnostics.push_back(Diagnostic::info(
                    "operation_replayed",
                    "publish operation already finished (" + prior_status +
                        ") — receipt replayed, no second version"));
                return replay;
            }
        } else {
            // Unfinished publish journal (crash): resume with the journal's
            // own fragments — recovery semantics, not a fresh attempt.
            return finish_publish_journal(*existing, document);
        }
    }

    // ---- Run state checks.
    auto current_run = run_state(request.run_id);
    if (!current_run.has_value()) {
        receipt.status = PublishStatus::Conflict;
        receipt.diagnostics.push_back(Diagnostic::error(
            "unknown_run", "run not found: " + request.run_id.str()));
        return receipt;
    }
    if (current_run->status != std::string(kRunStatusRunning)) {
        receipt.status = PublishStatus::Conflict;
        receipt.diagnostics.push_back(Diagnostic::error(
            "run_not_running",
            "run " + request.run_id.str() + " is '" + current_run->status +
                "' — only a running run can publish (retry creates a new "
                "run)"));
        return receipt;
    }
    if (!current_run->output_version_ids.empty()) {
        receipt.status = PublishStatus::Conflict;
        receipt.diagnostics.push_back(Diagnostic::error(
            "run_already_published",
            "run " + request.run_id.str() +
                " already carries its single result version"));
        return receipt;
    }

    // ---- Target asset resolution.
    domain::AssetId target_asset;
    bool asset_created = false;
    DataAsset new_asset;
    if (request.target_asset_id.has_value() &&
        !request.target_asset_id->empty()) {
        target_asset = *request.target_asset_id;
        auto catalog = repository_.open_read_only();
        if (!catalog.is_ok() ||
            catalog.value().find_asset(target_asset) == nullptr) {
            receipt.status = PublishStatus::Conflict;
            receipt.diagnostics.push_back(Diagnostic::error(
                "unknown_asset",
                "target asset not found: " + target_asset.str()));
            return receipt;
        }
    } else {
        if (request.new_asset_name.empty()) {
            receipt.diagnostics.push_back(Diagnostic::error(
                "missing_asset_name",
                "new_asset_name is required when no target asset is given"));
            return receipt;
        }
        asset_created = true;
        new_asset.id = domain::AssetId(domain::make_id("asset_"));
        new_asset.name = request.new_asset_name;
        new_asset.type = request.new_asset_type;
        new_asset.created_at = now();
        new_asset.updated_at = new_asset.created_at;
        target_asset = new_asset.id;
    }

    // ---- Pending journal gate (overlapping asset/run/layer).
    if (auto conflict = pending_conflict(request.operation_id, target_asset,
                                         request.run_id,
                                         request.rebind_layer)) {
        receipt.status = PublishStatus::Failed;
        receipt.diagnostics.push_back(std::move(*conflict));
        return receipt;
    }

    const StagedAssetV1& staged = request.products.front();
    if (!fs::is_regular_file(staged.source_path)) {
        receipt.diagnostics.push_back(Diagnostic::error(
            "staged_missing",
            "staged asset does not exist: " +
                pwb::project::path_to_u8(staged.source_path)));
        return receipt;
    }
    if (staged.sha256.has_value()) {
        const auto digest = domain::Sha256::of_file(staged.source_path);
        if (!digest.has_value() || *digest != *staged.sha256) {
            receipt.diagnostics.push_back(Diagnostic::error(
                "staged_hash_mismatch",
                "staged asset hash mismatch (expected " + *staged.sha256 +
                    ")"));
            return receipt;
        }
    }

    // ---- Version row (parents = run inputs; metadata = result_metadata).
    DataVersion version;
    version.id = domain::VersionId(domain::make_id("ver_"));
    version.asset_id = target_asset;
    version.stage = request.stage;
    version.managed = true;
    version.source_uri = pwb::project::path_to_u8(
        fs::weakly_canonical(staged.source_path));
    version.format = staged.format;
    version.run_id = request.run_id;
    version.metadata = request.result_metadata;
    version.created_at = now();
    version.parent_version_ids = current_run->input_version_ids;
    receipt.asset_id = target_asset;
    receipt.asset_created = asset_created;
    receipt.new_version_id = version.id;
    receipt.status = PublishStatus::Failed;

    // Phase 1: journal durable BEFORE anything else.
    {
        auto catalog = repository_.open_read_only();
        if (catalog.is_ok()) {
            if (catalog.value().find_version(version.id) != nullptr) {
                receipt.diagnostics.push_back(Diagnostic::error(
                    "immutable_version",
                    "version id already exists: " + version.id.str()));
                return receipt;
            }
            version.version_number =
                catalog.value().next_version_number(target_asset);
        } else {
            version.version_number = 1;
        }
    }
    auto error = write_journal(publish_journal_json(
        request, target_asset, asset_created,
        asset_created ? &new_asset : nullptr, version, receipt,
        JournalPhase::Written));
    if (error.code != ErrorCode::Ok) {
        receipt.diagnostics.push_back(
            Diagnostic::error("journal_failure", error.message));
        return receipt;
    }
    if (fault_hook_) {
        if (auto fault = fault_hook_(JournalPhase::Written)) {
            receipt.diagnostics.push_back(
                Diagnostic::error("fault_injected", fault->message));
            return receipt;
        }
    }

    // Phase 2: payload placement.
    auto placed = detail::place_payload(staged.source_path, manager_.path(),
                                        request.stage, target_asset,
                                        version.id);
    if (!placed.is_ok()) {
        receipt.diagnostics.push_back(
            Diagnostic::error("payload_failure", placed.error().message));
        write_journal(publish_journal_json(
            request, target_asset, asset_created,
            asset_created ? &new_asset : nullptr, version, receipt,
            JournalPhase::Written));
        return receipt;
    }
    version.path = placed.value().rel_path;
    version.size_bytes = static_cast<std::int64_t>(placed.value().size);
    version.sha256 = placed.value().sha256;
    receipt.sha256 = placed.value().sha256;
    receipt.size_bytes = placed.value().size;
    error = write_journal(publish_journal_json(
        request, target_asset, asset_created,
        asset_created ? &new_asset : nullptr, version, receipt,
        JournalPhase::PayloadStaged));
    if (fault_hook_) {
        if (auto fault = fault_hook_(JournalPhase::PayloadStaged)) {
            receipt.diagnostics.push_back(
                Diagnostic::error("fault_injected", fault->message));
            return receipt;
        }
    }

    // Phase 3: catalog transaction (asset row? + version + linkage; the
    // run stays "running" until bindings are durable).
    {
        auto writable = repository_.open_read_write();
        if (!writable.is_ok()) {
            receipt.diagnostics.push_back(Diagnostic::error(
                "catalog_unavailable", writable.error().message));
            return receipt;
        }
        auto commit_error = repository_.publish_result_transaction(
            asset_created ? std::make_optional(new_asset)
                          : std::optional<DataAsset>(),
            version, request.run_id);
        if (commit_error.code != ErrorCode::Ok) {
            receipt.diagnostics.push_back(Diagnostic::error(
                "catalog_commit_failure", commit_error.message));
            return receipt;
        }
    }
    receipt.version_number = version.version_number;
    error = write_journal(publish_journal_json(
        request, target_asset, asset_created,
        asset_created ? &new_asset : nullptr, version, receipt,
        JournalPhase::CatalogCommitted));
    if (fault_hook_) {
        if (auto fault = fault_hook_(JournalPhase::CatalogCommitted)) {
            receipt.diagnostics.push_back(
                Diagnostic::error("fault_injected", fault->message));
            return receipt;
        }
    }

    // Phase 4: project file (rebind + atomic replace).
    apply_rebind_to(target_asset, version.id, request.rebind_layer, document);
    auto saved = manager_.save(document);
    if (!saved.is_ok()) {
        receipt.diagnostics.push_back(Diagnostic::error(
            "project_save_failure", saved.error().message));
        return receipt;
    }
    write_journal(publish_journal_json(
        request, target_asset, asset_created,
        asset_created ? &new_asset : nullptr, version, receipt,
        JournalPhase::ProjectSaved));
    if (fault_hook_) {
        if (auto fault = fault_hook_(JournalPhase::ProjectSaved)) {
            receipt.diagnostics.push_back(
                Diagnostic::error("fault_injected", fault->message));
            return receipt;
        }
    }
    write_journal(publish_journal_json(
        request, target_asset, asset_created,
        asset_created ? &new_asset : nullptr, version, receipt,
        JournalPhase::Rebound));
    if (fault_hook_) {
        if (auto fault = fault_hook_(JournalPhase::Rebound)) {
            receipt.diagnostics.push_back(
                Diagnostic::error("fault_injected", fault->message));
            return receipt;
        }
    }

    // Phase 5: run terminal — ONLY now is the success state durable.
    {
        Json finished;
        finished["_finished_at"] = now();
        auto writable = repository_.open_read_write();
        if (!writable.is_ok()) {
            receipt.diagnostics.push_back(Diagnostic::error(
                "catalog_unavailable", writable.error().message));
            return receipt;
        }
        auto finish_error = repository_.finish_run_transaction(
            request.run_id, std::string(kRunStatusComplete), finished);
        if (finish_error.code != ErrorCode::Ok) {
            receipt.diagnostics.push_back(Diagnostic::error(
                "run_completion_failure", finish_error.message));
            return receipt;
        }
    }
    write_journal(publish_journal_json(
        request, target_asset, asset_created,
        asset_created ? &new_asset : nullptr, version, receipt,
        JournalPhase::RunCompleted));
    if (fault_hook_) {
        if (auto fault = fault_hook_(JournalPhase::RunCompleted)) {
            receipt.diagnostics.push_back(
                Diagnostic::error("fault_injected", fault->message));
            return receipt;
        }
    }

    receipt.status = PublishStatus::Published;
    write_journal(publish_journal_json(
        request, target_asset, asset_created,
        asset_created ? &new_asset : nullptr, version, receipt,
        JournalPhase::Completed));
    write_journal(publish_journal_json(
        request, target_asset, asset_created,
        asset_created ? &new_asset : nullptr, version, receipt,
        JournalPhase::CleanedUp));
    return receipt;
}

// ---------------------------------------------------------------------------
// publish resume / rollback (recovery)
// ---------------------------------------------------------------------------

Result<PublishReceiptV1> CommitCoordinator::finish_publish_journal(
    JournalRecord& record, project::ProjectDocument& document) {
    // All resume fragments come from the journal itself — a recovery pass
    // has no original request.
    PublishRequestV1 request;
    request.operation_id = domain::OperationId(record.operation_id);
    request.run_id = domain::RunId(record.json.value("run_id", ""));
    const auto layer_field = record.json.find("rebind_layer");
    if (layer_field != record.json.end() && layer_field->is_string() &&
        !layer_field->get<std::string>().empty()) {
        request.rebind_layer =
            domain::LayerId(layer_field->get<std::string>());
    }

    domain::AssetId target_asset(
        record.json.value("asset_id", ""));
    const bool asset_created = record.asset_created;
    DataAsset new_asset;
    if (asset_created) {
        new_asset = asset_from_json(record.asset_json, target_asset);
    }

    DataVersion version;
    version.id = record.new_version_id;
    version.asset_id = target_asset;
    version.path = record.json.value("payload_rel_path", "");
    version.source_uri = record.json.value("source_uri", "");
    version.format = record.resumed_format;
    version.parent_version_ids = record.resumed_parents;
    const auto stage = domain::data_stage_from_string(
        record.json.value("stage", "derived"));
    version.stage = stage.value_or(domain::DataStage::Derived);
    version.created_at = record.json.value("updated_at", now());
    version.metadata = record.result_metadata;
    version.run_id = request.run_id;

    PublishReceiptV1 receipt = publish_receipt_from_journal(record);

    // Everything from CatalogCommitted on is durable: finish the tail.
    if (record.phase == JournalPhase::CatalogCommitted ||
        record.phase == JournalPhase::ProjectSaved ||
        record.phase == JournalPhase::Rebound ||
        record.phase == JournalPhase::RunCompleted) {
        if (record.phase == JournalPhase::CatalogCommitted) {
            apply_rebind_to(target_asset, version.id, request.rebind_layer,
                            document);
            auto saved = manager_.save(document);
            if (!saved.is_ok()) {
                receipt.diagnostics.push_back(Diagnostic::error(
                    "project_save_failure", saved.error().message));
                return receipt;
            }
            write_journal(publish_journal_json(
                request, target_asset, asset_created,
                asset_created ? &new_asset : nullptr, version, receipt,
                JournalPhase::ProjectSaved));
        }
        if (record.phase != JournalPhase::RunCompleted) {
            Json finished;
            finished["_finished_at"] = now();
            auto writable = repository_.open_read_write();
            if (!writable.is_ok()) {
                receipt.diagnostics.push_back(Diagnostic::error(
                    "catalog_unavailable", writable.error().message));
                return receipt;
            }
            auto finish_error = repository_.finish_run_transaction(
                request.run_id, std::string(kRunStatusComplete), finished);
            if (finish_error.code != ErrorCode::Ok) {
                receipt.diagnostics.push_back(Diagnostic::error(
                    "run_completion_failure", finish_error.message));
                return receipt;
            }
        }
        receipt.status = PublishStatus::Published;
        write_journal(publish_journal_json(
            request, target_asset, asset_created,
            asset_created ? &new_asset : nullptr, version, receipt,
            JournalPhase::Completed));
        write_journal(publish_journal_json(
            request, target_asset, asset_created,
            asset_created ? &new_asset : nullptr, version, receipt,
            JournalPhase::CleanedUp));
        return receipt;
    }
    if (record.phase == JournalPhase::PayloadStaged) {
        // Payload landed, catalog not → finish the catalog transaction.
        {
            auto writable = repository_.open_read_write();
            if (!writable.is_ok()) {
                receipt.diagnostics.push_back(Diagnostic::error(
                    "catalog_unavailable", writable.error().message));
                return receipt;
            }
            auto reloaded = repository_.open_read_only();
            if (reloaded.is_ok()) {
                if (const DataVersion* existing =
                        reloaded.value().find_version(version.id)) {
                    version.version_number = existing->version_number;
                } else {
                    version.version_number =
                        reloaded.value().next_version_number(target_asset);
                }
            }
            version.size_bytes =
                static_cast<std::int64_t>(receipt.size_bytes);
            version.sha256 = receipt.sha256;
            auto commit_error = repository_.publish_result_transaction(
                asset_created ? std::make_optional(new_asset)
                              : std::optional<DataAsset>(),
                version, request.run_id);
            if (commit_error.code != ErrorCode::Ok) {
                receipt.diagnostics.push_back(Diagnostic::error(
                    "catalog_commit_failure", commit_error.message));
                return receipt;
            }
        }
        receipt.version_number = version.version_number;
        write_journal(publish_journal_json(
            request, target_asset, asset_created,
            asset_created ? &new_asset : nullptr, version, receipt,
            JournalPhase::CatalogCommitted));
        // Continue the durable tail: project save → run complete.
        record.phase = JournalPhase::CatalogCommitted;
        return finish_publish_journal(record, document);
    }
    // Only the journal exists → nothing durable happened → roll back.
    return rollback_publish_journal(record);
}

Result<PublishReceiptV1> CommitCoordinator::rollback_publish_journal(
    JournalRecord& record) {
    PublishReceiptV1 receipt = publish_receipt_from_journal(record);
    receipt.status = PublishStatus::RolledBack;
    // Payload staged but catalog never committed → remove the payload dir
    // (owned by this operation alone). The journal stays as evidence.
    const std::string rel = record.json.value("payload_rel_path", "");
    if (record.phase == JournalPhase::PayloadStaged && !rel.empty()) {
        std::error_code ec;
        const fs::path project_dir =
            pwb::project::project_dir_for(manager_.path());
        const fs::path payload = fs::weakly_canonical(
            project_dir / pwb::project::path_from_u8(rel), ec);
        if (fs::is_directory(payload.parent_path(), ec)) {
            std::error_code remove_ec;
            fs::remove_all(payload.parent_path(), remove_ec);
        }
    }
    Json journal = record.json;
    journal["kind"] = to_string(JournalKind::RunPublish);
    journal["phase"] = to_string(JournalPhase::CleanedUp);
    Json receipt_json = Json::object();
    receipt_json["status"] = to_string(PublishStatus::RolledBack);
    receipt_json["version_number"] = receipt.version_number;
    receipt_json["sha256"] = receipt.sha256;
    receipt_json["size_bytes"] = receipt.size_bytes;
    journal["receipt"] = std::move(receipt_json);
    write_journal(journal);
    receipt.diagnostics.push_back(Diagnostic::warning(
        "journal_rolled_back",
        "interrupted publish " + record.operation_id +
            " rolled back; staged payload removed; run stays 'running' "
            "(retry the same operation id, or finish_run)",
        Json{{"payload", rel}, {"run_id", receipt.run_id.str()}}));
    return receipt;
}

}  // namespace pwb::data
