// catalog_closure_adapter.cpp — see
// include/pwb/closure_workflow/catalog_closure_adapter.hpp.
//
// Every behavior here cites the frozen Python oracle (service.py /
// adapter.py / db.py) it mirrors; the seam header
// (workflow_runtime/catalog_seam.hpp) is the contract surface.

#include <pwb/closure_workflow/catalog_closure_adapter.hpp>

#include <pwb/catalog/checksum.hpp>
#include <pwb/catalog/dedup.hpp>
#include <pwb/catalog/document_index.hpp>
#include <pwb/catalog/queries.hpp>
#include <pwb/catalog/queries_sql.hpp>
#include <pwb/catalog/resolve.hpp>
#include <pwb/catalog/sqlite.hpp>
#include <pwb/catalog/trash.hpp>
#include <pwb/domain/diagnostics.hpp>
#include <pwb/domain/ids.hpp>
#include <pwb/project/paths.hpp>

#include <algorithm>
#include <cctype>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace pwb::closure_workflow {

namespace {

namespace fs = std::filesystem;

using pwb::catalog::CatalogDocument;
using pwb::catalog::DataAsset;
using pwb::catalog::DataRun;
using pwb::catalog::DataVersion;
using pwb::catalog::Database;
using pwb::catalog::DocumentIndex;
using pwb::catalog::RunPort;
using pwb::domain::DataError;
using pwb::domain::DataException;
using pwb::domain::DataStage;
using pwb::domain::ErrorCode;
using pwb::domain::Json;
using pwb::workflow_runtime::AssetRecord;
using pwb::workflow_runtime::RegisteredAssetVersion;
using pwb::workflow_runtime::RunRecord;
using pwb::workflow_runtime::VersionRecord;

// adapter.py:46-48 — the private bridge keys riding inside
// run.parameters. _actor has no Python-side field; it follows the same
// underscore convention so _run_ref-style filtering keeps it out of the
// public parameter surface.
constexpr const char* kDomainTaskKey = "_domain_task_id";
constexpr const char* kSnapshotHashKey = "_input_snapshot_hash";
constexpr const char* kFinishedAtKey = "_finished_at";
constexpr const char* kActorKey = "_actor";

// service_v11.py MAX_RUN_PORTS.
constexpr std::size_t kMaxRunPorts = 256;

std::string lower_ascii(std::string_view text) {
    std::string out(text);
    for (char& c : out) {
        c = static_cast<char>(
            std::tolower(static_cast<unsigned char>(c)));
    }
    return out;
}

std::string strip_ascii(std::string_view text) {
    std::string out(text);
    const auto first = out.find_first_not_of(" \t\n\r");
    const auto last = out.find_last_not_of(" \t\n\r");
    if (first == std::string::npos) return {};
    return out.substr(first, last - first + 1);
}

// service.py update_run_status terminal vocabulary (L2790-2791).
bool is_terminal_status(const std::string& lowered) {
    return lowered == "complete" || lowered == "completed" ||
           lowered == "failed" || lowered == "cancelled" ||
           lowered == "canceled";
}

bool is_complete_alias(const std::string& lowered) {
    return lowered == "complete" || lowered == "completed";
}

[[noreturn]] void fail(const DataError& error) {
    throw DataException(error);
}

void require_ok(const DataError& error) {
    if (!error.ok()) fail(error);
}

// service.py _coerce_stage (str.strip().lower() → DataStage); the seam
// transports stage as a string ("DERIVED", "raw", ...).
DataStage stage_or_throw(const std::string& stage) {
    const std::string lowered = lower_ascii(strip_ascii(stage));
    const auto parsed = pwb::domain::data_stage_from_string(lowered);
    if (!parsed.has_value()) {
        throw std::invalid_argument("unknown data stage: " + stage);
    }
    return *parsed;
}

std::optional<std::string> opt_string(const Json& object, const char* key) {
    if (!object.is_object()) return std::nullopt;
    const auto it = object.find(key);
    if (it == object.end() || !it->is_string()) return std::nullopt;
    return it->get<std::string>();
}

// adapter.py _run_ref: parameters minus the private "_" bridge keys.
Json public_parameters(const Json& parameters) {
    Json out = Json::object();
    if (!parameters.is_object()) return out;
    for (auto it = parameters.begin(); it != parameters.end(); ++it) {
        if (it.key().empty() || it.key().front() != '_') {
            out[it.key()] = it.value();
        }
    }
    return out;
}

// repository.cpp manifest_port key order (the run_metadata port mirror
// keeps the FileCatalogRepository observable shape: raw dict arrays).
Json port_to_json(const RunPort& port) {
    Json out = Json::object();
    out["role"] = port.role;
    out["version_id"] = port.version_id.str();
    out["ordinal"] = port.ordinal;
    out["required"] = port.required;
    out["entity_type"] = port.entity_type;
    out["entity_id"] = port.entity_id;
    out["note"] = port.note;
    return out;
}

Json ports_to_json(const std::vector<RunPort>& ports) {
    Json out = Json::array();
    for (const RunPort& port : ports) out.push_back(port_to_json(port));
    return out;
}

std::string read_file_text(const fs::path& path) {
    std::error_code ec;
    if (!fs::is_regular_file(path, ec)) return {};
    std::ifstream in(path, std::ios::binary);
    if (!in) return {};
    return std::string(std::istreambuf_iterator<char>(in),
                       std::istreambuf_iterator<char>());
}

// ---- record mirrors ------------------------------------------------------

AssetRecord asset_record_of(const DataAsset& asset) {
    AssetRecord out;
    out.id = asset.id.str();
    out.name = asset.name;
    out.type = asset.type;
    // _new_asset parity: format rides asset.metadata["format"].
    if (const auto it = asset.metadata.find("format");
        asset.metadata.is_object() && it != asset.metadata.end() &&
        it->is_string()) {
        out.format = it->get<std::string>();
    }
    if (asset.current_version_id.has_value()) {
        out.current_version_id = asset.current_version_id->str();
    }
    out.metadata = asset.metadata.is_object() ? asset.metadata
                                              : Json::object();
    return out;
}

// _version_ref parity for the seam record: name from the owning asset,
// path resolved through the catalog ladder, payload re-read from the
// managed/external file (the seam's string transport — missing payloads
// read as "").
VersionRecord version_record_of(const DataVersion& version,
                                const DataAsset* asset,
                                const fs::path& project_path) {
    VersionRecord out;
    out.asset_id = version.asset_id.str();
    out.version_id = version.id.str();
    out.name = asset != nullptr ? asset->name : "";
    if (version.run_id.has_value()) {
        out.producing_run_id = version.run_id->str();
    }
    out.checksum = version.sha256.value_or("");
    out.trashed = version.trashed;
    const fs::path resolved =
        pwb::catalog::resolve_payload_path(project_path, version);
    out.path = pwb::project::path_to_u8(resolved);
    out.created_at = version.created_at;
    out.metadata = version.metadata.is_object() ? version.metadata
                                                  : Json::object();
    // RuntimeStore mirror parity: stage + lineage ride metadata so the
    // observable record shape is identical across backends.
    out.metadata["stage"] = std::string(pwb::domain::to_string(version.stage));
    if (!version.parent_version_ids.empty()) {
        Json parents = Json::array();
        for (const auto& parent : version.parent_version_ids) {
            parents.push_back(parent.str());
        }
        out.metadata["parent_version_ids"] = std::move(parents);
    }
    out.payload_json = read_file_text(resolved);
    return out;
}

RunRecord run_record_of(const DataRun& run) {
    RunRecord out;
    out.run_id = run.id.str();
    out.operation = run.operation;
    for (const auto& id : run.input_version_ids) {
        out.input_version_ids.push_back(id.str());
    }
    for (const auto& id : run.output_version_ids) {
        out.output_version_ids.push_back(id.str());
    }
    out.parameters = public_parameters(run.parameters);
    if (!run.generator.empty()) out.generator_version = run.generator;
    out.domain_task_id = opt_string(run.parameters, kDomainTaskKey);
    out.input_snapshot_hash = opt_string(run.parameters, kSnapshotHashKey);
    out.status = run.status;
    if (!run.created_at.empty()) out.started_at = run.created_at;
    out.finished_at = opt_string(run.parameters, kFinishedAtKey);
    out.actor = opt_string(run.parameters, kActorKey);
    out.run_metadata = Json::object();
    if (!run.input_ports.empty()) {
        out.run_metadata["input_ports"] = ports_to_json(run.input_ports);
    }
    if (!run.output_ports.empty()) {
        out.run_metadata["output_ports"] = ports_to_json(run.output_ports);
    }
    return out;
}

// ---- write-path helpers ---------------------------------------------------

// Payload staging lease (service.py _payload_staging_lease, #1222):
// best-effort — acquire failure proceeds with pre-lease semantics.
class StagingLease {
public:
    StagingLease(pwb::catalog::CatalogRepository& repo,
                 std::vector<std::string> targets, const char* kind)
        : repo_(&repo) {
        if (auto id = repo_->acquire_staging_lease(targets, kind)) {
            lease_id_ = *id;
        }
    }
    ~StagingLease() {
        if (!lease_id_.empty()) repo_->release_staging_lease(lease_id_);
    }
    StagingLease(const StagingLease&) = delete;
    StagingLease& operator=(const StagingLease&) = delete;

private:
    pwb::catalog::CatalogRepository* repo_;
    std::string lease_id_;
};

// service.py _staging_target: "<artifacts>/<stage_dir>/<asset_id>" posix.
std::string staging_target(const fs::path& project_path, DataStage stage,
                           const std::string& asset_id) {
    const std::string artifacts_name =
        pwb::project::artifact_dir_for(project_path)
            .filename()
            .generic_string();
    return artifacts_name + "/" + pwb::catalog::stage_dir_name(stage) + "/" +
           asset_id;
}

std::string blob_staging_target(const fs::path& project_path) {
    return pwb::project::artifact_dir_for(project_path)
               .filename()
               .generic_string() +
           "/blobs";
}

// The seam's string transport lands as a real file so place_managed_file
// can hash+place it (Python writes a temp file and registers its path —
// the file location is incidental, the bytes are the identity).
fs::path stage_payload_file(const fs::path& metadata_dir,
                            const std::string& payload_json) {
    const fs::path dir =
        metadata_dir / (".payload-" + pwb::domain::make_id(""));
    std::error_code ec;
    fs::create_directories(dir, ec);
    if (ec) {
        fail(DataError(ErrorCode::IoError,
                       "payload staging dir unwritable: " +
                           dir.generic_string()));
    }
    const fs::path file = dir / "payload.json";
    {
        std::ofstream out(file, std::ios::binary | std::ios::trunc);
        if (!out.good()) {
            fs::remove_all(dir, ec);
            fail(DataError(ErrorCode::IoError,
                           "payload staging file unwritable: " +
                               file.generic_string()));
        }
        out.write(payload_json.data(),
                  static_cast<std::streamsize>(payload_json.size()));
        out.flush();
        if (!out.good()) {
            out.close();
            fs::remove_all(dir, ec);
            fail(DataError(ErrorCode::IoError,
                           "payload staging write failed: " +
                               file.generic_string()));
        }
    }
    return file;
}

void cleanup_staged(const fs::path& staged_file) {
    std::error_code ec;
    fs::remove(staged_file, ec);
    fs::remove(staged_file.parent_path(), ec);  // the .payload- dir (empty)
}

// service.py _rollback payload arm: a placed payload whose metadata commit
// failed is removed (never a CAS blob — those are shared, content
// addressed), then the now-empty version/asset dirs are pruned.
void rollback_placed_payload(const fs::path& project_path,
                             const std::string& rel_path) {
    if (rel_path.empty() ||
        pwb::catalog::is_cas_path(project_path, rel_path)) {
        return;
    }
    std::error_code ec;
    const fs::path payload = pwb::project::project_dir_for(project_path) /
                             pwb::project::path_from_u8(rel_path);
    fs::remove(payload, ec);
    fs::remove(payload.parent_path(), ec);           // version dir
    fs::remove(payload.parent_path().parent_path(), ec);  // asset dir
}

// service.py _build_version (L1670-1727): place_managed_file fills
// path/size/sha256; source_uri is the resolved source path; format comes
// from the asset metadata ("format"); the caller owns the commit +
// rollback.
DataVersion build_managed_version(const fs::path& project_path,
                                  const fs::path& source_file,
                                  const std::string& resolved_source_uri,
                                  const std::string& asset_id,
                                  DataStage stage,
                                  const std::vector<std::string>& parents,
                                  const std::optional<std::string>& run_id,
                                  const Json& metadata,
                                  const std::string& format,
                                  int version_number, bool register_blob,
                                  const std::optional<std::string>& known_sha256) {
    DataVersion version;
    version.id = pwb::domain::VersionId(pwb::domain::make_id("ver_"));
    version.asset_id = pwb::domain::AssetId(asset_id);
    version.version_number = version_number;
    version.stage = stage;
    version.managed = true;
    version.source_uri = resolved_source_uri;
    version.format = format;
    if (run_id.has_value() && !run_id->empty()) {
        version.run_id = pwb::domain::RunId(*run_id);
    }
    version.metadata = metadata.is_object() ? metadata : Json::object();
    version.created_at = pwb::domain::now_iso8601();
    for (const auto& parent : parents) {
        version.parent_version_ids.emplace_back(parent);
    }
    pwb::catalog::PlaceManagedOptions options;
    options.known_sha256 = known_sha256;
    options.register_blob = register_blob;
    auto placed =
        pwb::catalog::place_managed_file(source_file, project_path, stage,
                                         asset_id, version.id.str(), options);
    if (!placed.is_ok()) fail(placed.error());
    version.path = placed.value().rel_path;
    version.size_bytes = placed.value().size_bytes;
    version.sha256 = placed.value().sha256;
    return version;
}

// service.py _new_asset (L2039-2053): type defaults "unknown"; a non-empty
// format rides metadata["format"].
DataAsset new_asset(const std::string& name, const std::string& kind,
                    const std::string& format, const Json& metadata) {
    DataAsset asset;
    asset.id = pwb::domain::AssetId(pwb::domain::make_id("asset_"));
    asset.name = name;
    asset.type = kind.empty() ? "unknown" : kind;
    asset.metadata = metadata.is_object() ? metadata : Json::object();
    if (!format.empty()) asset.metadata["format"] = format;
    asset.created_at = asset.updated_at = pwb::domain::now_iso8601();
    return asset;
}

// service.py _live_asset_by_legacy_id: _asset_by_legacy_id minus trashed.
const DataAsset* live_asset_by_legacy_id(const DocumentIndex& index,
                                         const std::string& legacy_id) {
    const DataAsset* asset = index.asset_by_legacy_id(legacy_id);
    return (asset != nullptr && !asset->trashed) ? asset : nullptr;
}

// st_mtime_ns epoch-ns fingerprint for external_stat (storage.py parity;
// file_clock → system_clock conversion keeps epoch semantics).
std::int64_t mtime_ns_of(const fs::path& path) {
    std::error_code ec;
    const auto stamp = fs::last_write_time(path, ec);
    if (ec) return 0;
    const auto sys = std::chrono::file_clock::to_sys(stamp);
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
               sys.time_since_epoch())
        .count();
}

// adapter.py _bridge_legacy_id (L219-236): record the legacy bridge on an
// idempotent hit when it is missing. The bridge id is set ONCE — an asset
// already carrying a (different) id is left alone and an id already claimed
// by another asset is never re-assigned. Fetches fresh rows so a bridge
// write can never clobber a current pointer another call just moved.
void bridge_legacy_id(pwb::catalog::CatalogRepository& repo,
                      const std::string& version_id,
                      const std::optional<std::string>& legacy_id) {
    if (!legacy_id.has_value() || legacy_id->empty()) return;
    Database& db = repo.writable_database();
    const auto version =
        pwb::catalog::get_version_model(db, version_id);
    if (!version.has_value()) return;
    auto asset =
        pwb::catalog::get_asset_model(db, version->asset_id.str());
    if (!asset.has_value() || asset->legacy_resource_id.has_value()) return;
    // _find_asset_by_legacy_id claim check (exact asset id wins, then the
    // first bridged asset — rowid order is document order).
    for (const auto& row : pwb::catalog::list_asset_identity_rows(
             db, /*include_trashed=*/true)) {
        if (row.id == *legacy_id || row.legacy_resource_id == *legacy_id) {
            return;
        }
    }
    asset->legacy_resource_id = *legacy_id;
    require_ok(repo.upsert_asset(*asset));
}

}  // namespace

// ---------------------------------------------------------------------------

CatalogClosureAdapter::CatalogClosureAdapter(std::filesystem::path project_path,
                                             std::filesystem::path sqlite_path)
    : project_path_(std::move(project_path)),
      repo_(sqlite_path.empty()
                ? pwb::project::catalog_sqlite_for(project_path_)
                : std::move(sqlite_path)) {
    // open_read_write is the validating entry: a missing store is created
    // + schema-seeded; Corrupt/Unreadable → CorruptDatabase error, thrown
    // here — the store is never silently reset.
    auto opened = repo_.open_read_write();
    if (!opened.is_ok()) fail(opened.error());
}

CatalogClosureAdapter::~CatalogClosureAdapter() = default;
CatalogClosureAdapter::CatalogClosureAdapter(CatalogClosureAdapter&&) noexcept =
    default;
CatalogClosureAdapter& CatalogClosureAdapter::operator=(
    CatalogClosureAdapter&&) noexcept = default;

std::optional<CatalogClosureAdapter> CatalogClosureAdapter::try_open(
    const std::filesystem::path& project_path,
    std::filesystem::path sqlite_path, std::string* error_out) {
    try {
        return CatalogClosureAdapter(project_path, std::move(sqlite_path));
    } catch (const std::exception& exc) {
        if (error_out != nullptr) *error_out = exc.what();
        return std::nullopt;
    }
}

// ---- listing / resolution ------------------------------------------------

std::vector<AssetRecord> CatalogClosureAdapter::list_assets() {
    // service.py list_assets default: trashed assets hidden.
    std::vector<AssetRecord> out;
    for (const DataAsset& asset : pwb::catalog::list_asset_models(
             repo_.writable_database(), /*include_trashed=*/false)) {
        out.push_back(asset_record_of(asset));
    }
    return out;
}

std::optional<AssetRecord> CatalogClosureAdapter::resolve_asset(
    const std::string& asset_id) {
    const auto asset = pwb::catalog::get_asset_model(repo_.writable_database(),
                                                     asset_id);
    if (!asset.has_value()) return std::nullopt;
    return asset_record_of(*asset);
}

std::vector<VersionRecord> CatalogClosureAdapter::list_versions(
    const std::string& asset_id) {
    auto versions = pwb::catalog::list_version_models_for_asset(
        repo_.writable_database(), asset_id);
    // service.py list_versions: sorted by version_number (stable: document
    // order is the tiebreak).
    std::stable_sort(versions.begin(), versions.end(),
                     [](const DataVersion& a, const DataVersion& b) {
                         return a.version_number < b.version_number;
                     });
    const auto asset = pwb::catalog::get_asset_model(
        repo_.writable_database(), asset_id);
    const DataAsset* owner = asset.has_value() ? &*asset : nullptr;
    std::vector<VersionRecord> out;
    out.reserve(versions.size());
    for (const DataVersion& version : versions) {
        out.push_back(version_record_of(version, owner, project_path_));
    }
    return out;
}

std::optional<VersionRecord> CatalogClosureAdapter::resolve_version(
    const std::string& version_id) {
    const auto version = pwb::catalog::get_version_model(
        repo_.writable_database(), version_id);
    if (!version.has_value()) return std::nullopt;
    const auto asset = pwb::catalog::get_asset_model(
        repo_.writable_database(), version->asset_id.str());
    return version_record_of(*version,
                             asset.has_value() ? &*asset : nullptr,
                             project_path_);
}

std::vector<RunRecord> CatalogClosureAdapter::list_runs() {
    std::vector<RunRecord> out;
    for (const DataRun& run :
         pwb::catalog::list_run_models(repo_.writable_database())) {
        out.push_back(run_record_of(run));
    }
    return out;
}

std::optional<RunRecord> CatalogClosureAdapter::resolve_run(
    const std::string& run_id) {
    const auto run = pwb::catalog::get_run_model(repo_.writable_database(),
                                                 run_id);
    if (!run.has_value()) return std::nullopt;
    return run_record_of(*run);
}

// ---- mutations -------------------------------------------------------------

std::string CatalogClosureAdapter::register_run(
    const std::string& operation,
    const std::vector<std::string>& input_version_ids,
    const Json& parameters,
    const std::optional<std::string>& generator_version,
    const std::string& status,
    const std::optional<std::string>& domain_task_id,
    const std::optional<std::string>& input_snapshot_hash,
    const std::optional<std::string>& actor) {
    DataRun run;
    run.id = pwb::domain::RunId(pwb::domain::make_id("run_"));
    run.operation = operation;
    for (const auto& id : input_version_ids) {
        run.input_version_ids.emplace_back(id);
    }
    // adapter.py begin_run: the bridge keys ride inside parameters.
    run.parameters = parameters.is_object() ? parameters : Json::object();
    if (domain_task_id.has_value()) {
        run.parameters[kDomainTaskKey] = *domain_task_id;
    }
    if (input_snapshot_hash.has_value()) {
        run.parameters[kSnapshotHashKey] = *input_snapshot_hash;
    }
    if (actor.has_value()) run.parameters[kActorKey] = *actor;
    run.generator = generator_version.value_or("");
    run.status = status;
    run.created_at = pwb::domain::now_iso8601();
    require_ok(repo_.upsert_run(run));
    return run.id.str();
}

RegisteredAssetVersion CatalogClosureAdapter::register_result_asset(
    const std::string& name, const std::string& type,
    const std::string& format, const Json& asset_metadata,
    const std::string& payload_json, const std::string& stage,
    const std::string& run_id, const Json& version_metadata) {
    const DataStage stage_value = stage_or_throw(stage);
    auto document = repo_.open_read_only();
    if (!document.is_ok()) fail(document.error());

    // service.py register_result_asset L1884-1893: the run must exist;
    // lineage parents are the run's inputs filtered to committed versions.
    std::vector<std::string> parents;
    if (!run_id.empty()) {
        const DataRun* run =
            document.value().find_run(pwb::domain::RunId(run_id));
        if (run == nullptr) {
            throw std::invalid_argument("unknown run: " + run_id);
        }
        for (const auto& parent : run->input_version_ids) {
            if (document.value().find_version(parent) != nullptr) {
                parents.push_back(parent.str());
            }
        }
    }

    DataAsset asset = new_asset(name, type, format, asset_metadata);
    const std::string asset_id = asset.id.str();

    const fs::path staged =
        stage_payload_file(repo_.path().parent_path(), payload_json);
    const std::string staged_uri = fs::weakly_canonical(staged).generic_string();
    std::vector<std::string> targets{staging_target(project_path_,
                                                    stage_value, asset_id)};
    StagingLease lease(repo_, targets, "register");
    DataVersion version;
    try {
        version = build_managed_version(
            project_path_, staged, staged_uri, asset_id, stage_value,
            parents,
            run_id.empty() ? std::nullopt
                           : std::optional<std::string>(run_id),
            version_metadata, format, /*version_number=*/1,
            /*register_blob=*/false, std::nullopt);
    } catch (...) {
        cleanup_staged(staged);
        throw;
    }
    cleanup_staged(staged);
    asset.current_version_id = version.id;

    // Atomic commit: asset + version + current pointer (+ run_outputs link
    // when a run produced it) — publish_result_transaction /
    // import_raw_transaction parity (service.py:1909-1929 / 2125-2143).
    const DataError error =
        run_id.empty()
            ? repo_.import_raw_transaction(asset, version)
            : repo_.publish_result_transaction(asset, version,
                                               pwb::domain::RunId(run_id));
    if (!error.ok()) {
        rollback_placed_payload(project_path_, version.path);
        fail(error);
    }
    return {asset_id, version.id.str()};
}

std::string CatalogClosureAdapter::register_version(
    const std::string& asset_id, const std::string& payload_json,
    const std::string& stage,
    const std::vector<std::string>& parent_version_ids,
    const std::string& run_id, const Json& metadata) {
    const DataStage stage_value = stage_or_throw(stage);
    auto document = repo_.open_read_only();
    if (!document.is_ok()) fail(document.error());
    const DataAsset* asset =
        document.value().find_asset(pwb::domain::AssetId(asset_id));
    if (asset == nullptr) {
        throw std::invalid_argument("unknown asset: " + asset_id);
    }
    if (!run_id.empty() &&
        document.value().find_run(pwb::domain::RunId(run_id)) == nullptr) {
        throw std::invalid_argument("unknown run: " + run_id);
    }
    const int version_number =
        document.value().next_version_number(pwb::domain::AssetId(asset_id));
    // _build_version: format comes from the asset's metadata.
    std::string format;
    if (const auto it = asset->metadata.find("format");
        asset->metadata.is_object() && it != asset->metadata.end() &&
        it->is_string()) {
        format = it->get<std::string>();
    }

    const fs::path staged =
        stage_payload_file(repo_.path().parent_path(), payload_json);
    const std::string staged_uri = fs::weakly_canonical(staged).generic_string();
    std::vector<std::string> targets{staging_target(project_path_,
                                                    stage_value, asset_id)};
    StagingLease lease(repo_, targets, "register");
    DataVersion version;
    try {
        version = build_managed_version(
            project_path_, staged, staged_uri, asset_id, stage_value,
            parent_version_ids,
            run_id.empty() ? std::nullopt
                           : std::optional<std::string>(run_id),
            metadata, format, version_number,
            /*register_blob=*/false, std::nullopt);
    } catch (...) {
        cleanup_staged(staged);
        throw;
    }
    cleanup_staged(staged);

    // service.py register_version commit arm: version + derived rows +
    // current pointer + run_outputs link in ONE transaction.
    std::optional<pwb::domain::RunId> run_ref;
    if (!run_id.empty()) run_ref = pwb::domain::RunId(run_id);
    const DataError error = repo_.commit_version_transaction(
        version, pwb::domain::AssetId(asset_id), run_ref);
    if (!error.ok()) {
        rollback_placed_payload(project_path_, version.path);
        fail(error);
    }
    return version.id.str();
}

void CatalogClosureAdapter::update_run_status(const std::string& run_id,
                                              const std::string& status) {
    update_run_status(run_id, status, Json());
}

void CatalogClosureAdapter::update_run_status(
    const std::string& run_id, const std::string& status,
    const Json& extra_parameters) {
    const auto run = pwb::catalog::get_run_model(repo_.writable_database(),
                                                 run_id);
    if (!run.has_value()) {
        throw std::invalid_argument("unknown run: " + run_id);
    }
    // service.py:2787-2796 — a terminal status cannot be overwritten by a
    // different status (complete/completed alias through).
    const std::string current = lower_ascii(run->status);
    const std::string target = lower_ascii(status);
    if (is_terminal_status(current) && current != target &&
        !(is_complete_alias(current) && is_complete_alias(target))) {
        throw std::runtime_error("cannot change terminal run " + run_id +
                                 " from '" + run->status + "' to '" +
                                 status + "'");
    }
    Json extras =
        extra_parameters.is_object() ? extra_parameters : Json::object();
    // Python's complete_run stamps _finished_at via extra_parameters; the
    // seam's bare status call is the C++ equivalent — stamp on terminal
    // transitions unless the caller already supplied one.
    if (is_terminal_status(target) && !extras.contains(kFinishedAtKey)) {
        extras[kFinishedAtKey] = pwb::domain::now_iso8601();
    }
    require_ok(repo_.finish_run_transaction(pwb::domain::RunId(run_id),
                                            status, extras));
}

void CatalogClosureAdapter::attach_run_output(const std::string& run_id,
                                              const std::string& version_id) {
    auto run = pwb::catalog::get_run_model(repo_.writable_database(), run_id);
    if (!run.has_value()) {
        throw std::invalid_argument("unknown run: " + run_id);
    }
    // Python register_* appends when absent (idempotent).
    if (std::find(run->output_version_ids.begin(),
                  run->output_version_ids.end(),
                  pwb::domain::VersionId(version_id)) ==
        run->output_version_ids.end()) {
        run->output_version_ids.emplace_back(version_id);
        require_ok(repo_.upsert_run(*run));
    }
}

void CatalogClosureAdapter::set_run_ports(const std::string& run_id,
                                          const Json& input_ports,
                                          const Json& output_ports) {
    auto run = pwb::catalog::get_run_model(repo_.writable_database(), run_id);
    if (!run.has_value()) {
        throw std::invalid_argument("unknown run: " + run_id);
    }
    // service_v11._apply_run_ports: only the directions actually given are
    // replaced; a null Json leaves that side untouched (seam contract).
    const bool inputs_given = !input_ports.is_null();
    const bool outputs_given = !output_ports.is_null();
    if ((inputs_given && !input_ports.is_array()) ||
        (outputs_given && !output_ports.is_array())) {
        throw std::invalid_argument("run ports must be arrays or null");
    }
    auto coerce = [](const Json& item, const char* direction) -> RunPort {
        if (!item.is_object()) {
            throw std::invalid_argument("Invalid port spec: " + item.dump());
        }
        RunPort port;
        port.direction = direction;
        if (const auto it = item.find("role");
            it != item.end() && it->is_string()) {
            port.role = it->get<std::string>();
        } else {
            port.role = direction;
        }
        const auto vid = item.find("version_id");
        if (vid == item.end() || !vid->is_string() ||
            vid->get<std::string>().empty()) {
            throw std::invalid_argument("port missing version_id");
        }
        port.version_id = pwb::domain::VersionId(vid->get<std::string>());
        if (const auto it = item.find("ordinal");
            it != item.end() && it->is_number_integer()) {
            port.ordinal = static_cast<int>(it->get<std::int64_t>());
        }
        if (const auto it = item.find("required");
            it != item.end() && it->is_boolean()) {
            port.required = it->get<bool>();
        }
        if (const auto it = item.find("entity_type");
            it != item.end() && it->is_string()) {
            port.entity_type = it->get<std::string>();
        }
        if (const auto it = item.find("entity_id");
            it != item.end() && it->is_string()) {
            port.entity_id = it->get<std::string>();
        }
        if (const auto it = item.find("note");
            it != item.end() && it->is_string()) {
            port.note = it->get<std::string>();
        }
        return port;
    };
    std::vector<RunPort> new_inputs;
    std::vector<RunPort> new_outputs;
    if (inputs_given) {
        for (const Json& item : input_ports) {
            new_inputs.push_back(coerce(item, "input"));
        }
    }
    if (outputs_given) {
        for (const Json& item : output_ports) {
            new_outputs.push_back(coerce(item, "output"));
        }
    }
    const std::size_t total =
        (inputs_given ? new_inputs.size() : run->input_ports.size()) +
        (outputs_given ? new_outputs.size() : run->output_ports.size());
    if (total > kMaxRunPorts) {
        throw std::runtime_error("Run " + run_id +
                                 " exceeds the port budget (" +
                                 std::to_string(total) + " > 256)");
    }
    // validate_versions=True for set_run_ports: every port version id must
    // reference a committed version.
    for (const RunPort& port : new_inputs) {
        if (!pwb::catalog::get_version_model(repo_.writable_database(),
                                             port.version_id.str())
                 .has_value()) {
            throw std::runtime_error("Port references unknown version " +
                                     port.version_id.str());
        }
    }
    for (const RunPort& port : new_outputs) {
        if (!pwb::catalog::get_version_model(repo_.writable_database(),
                                             port.version_id.str())
                 .has_value()) {
            throw std::runtime_error("Port references unknown version " +
                                     port.version_id.str());
        }
    }
    // Ports ⊆ flat io lists: extend with any port id the lists lack.
    if (inputs_given) {
        run->input_ports = std::move(new_inputs);
        for (const RunPort& port : run->input_ports) {
            if (std::find(run->input_version_ids.begin(),
                          run->input_version_ids.end(),
                          port.version_id) == run->input_version_ids.end()) {
                run->input_version_ids.push_back(port.version_id);
            }
        }
    }
    if (outputs_given) {
        run->output_ports = std::move(new_outputs);
        for (const RunPort& port : run->output_ports) {
            if (std::find(run->output_version_ids.begin(),
                          run->output_version_ids.end(),
                          port.version_id) == run->output_version_ids.end()) {
                run->output_version_ids.push_back(port.version_id);
            }
        }
    }
    require_ok(repo_.upsert_run(*run));
}

void CatalogClosureAdapter::set_current_version(
    const std::string& asset_id, const std::string& version_id) {
    if (!pwb::catalog::get_asset_model(repo_.writable_database(), asset_id)
             .has_value()) {
        throw std::invalid_argument("unknown asset: " + asset_id);
    }
    require_ok(repo_.set_current_version(pwb::domain::AssetId(asset_id),
                                         pwb::domain::VersionId(version_id),
                                         pwb::domain::now_iso8601()));
}

std::optional<VersionRecord> CatalogClosureAdapter::resolve_legacy_resource(
    const std::string& resource_id) {
    if (resource_id.empty()) return std::nullopt;
    auto document = repo_.open_read_only();
    if (!document.is_ok()) fail(document.error());
    const DocumentIndex index(document.value());
    // adapter.py resolve_legacy_resource: exact-id-then-first-bridge order;
    // trashed / currentless assets resolve to nothing.
    const DataAsset* asset = index.asset_by_legacy_id(resource_id);
    if (asset == nullptr || asset->trashed ||
        !asset->current_version_id.has_value()) {
        return std::nullopt;
    }
    const auto version = pwb::catalog::get_version_model(
        repo_.writable_database(), asset->current_version_id->str());
    if (!version.has_value()) return std::nullopt;
    return version_record_of(*version, asset, project_path_);
}

std::optional<std::string> CatalogClosureAdapter::verify_integrity(
    const std::string& version_id) {
    if (!pwb::catalog::get_version_model(repo_.writable_database(), version_id)
             .has_value()) {
        return std::nullopt;
    }
    auto document = repo_.open_read_only();
    if (!document.is_ok()) fail(document.error());
    // queries.verify_integrity parity — the full resolution ladder (R1-R7)
    // is the same one reads use.
    const auto report = pwb::catalog::verify_integrity(
        document.value(), version_id,
        [this](const DataVersion& version) {
            return pwb::catalog::resolve_payload_path(project_path_, version);
        });
    return report.status_for(version_id);
}

// ---- register_input (adapter.py:239-345 parity) ----------------------------

VersionRecord CatalogClosureAdapter::register_input(
    const std::string& name, const std::string& path,
    const std::optional<std::string>& checksum, const std::string& kind,
    const std::string& format, bool external,
    const std::optional<std::string>& legacy_resource_id) {
    // adapter.py:253-260 — project-relative paths resolve against the
    // PROJECT dir, never the process CWD; the dedup keys ride the resolved
    // posix text.
    fs::path candidate = pwb::project::path_from_u8(path);
    if (!candidate.is_absolute()) {
        candidate = pwb::project::project_dir_for(project_path_) / candidate;
    }
    std::error_code ec;
    fs::path resolved_path = fs::weakly_canonical(candidate, ec);
    if (ec) resolved_path = fs::absolute(candidate).lexically_normal();
    const std::string resolved = resolved_path.generic_string();

    auto document = repo_.open_read_only();
    if (!document.is_ok()) fail(document.error());
    const DocumentIndex index(document.value());

    // Managed imports need a checksum for dedup + integrity; hash the
    // resolved file once when the caller didn't (adapter.py:262-273).
    std::optional<std::string> effective = checksum;
    if (effective.has_value() && effective->empty()) effective.reset();
    if (!external && !effective.has_value() &&
        fs::is_regular_file(resolved_path, ec)) {
        effective = pwb::catalog::sha256_file_or_none(resolved_path);
    }

    // adapter.py:280-284 — a TRASHED bridged asset is treated as unbridged
    // so re-import registers fresh (review finding I2).
    const DataAsset* bridged = nullptr;
    if (legacy_resource_id.has_value() && !legacy_resource_id->empty()) {
        bridged = live_asset_by_legacy_id(index, *legacy_resource_id);
    }

    auto record_for = [&](const DataVersion& version) {
        return version_record_of(
            version, document.value().find_asset(version.asset_id), project_path_);
    };

    if (external) {
        // Idempotence: same external path already linked → the existing
        // unmanaged version (trashed versions are never dedup targets).
        if (const auto found = index.external_for(resolved)) {
            const DataVersion* hit = index.version(*found);
            if (hit != nullptr && !hit->managed && !hit->trashed) {
                bridge_legacy_id(repo_, hit->id.str(), legacy_resource_id);
                return record_for(*hit);
            }
        }
        // Same legacy asset, same external link → its current version
        // (adapter.py:295-298 — reopening must not accumulate duplicates).
        if (bridged != nullptr &&
            bridged->current_version_id.has_value()) {
            const DataVersion* current =
                index.version(bridged->current_version_id->str());
            if (current != nullptr && !current->managed &&
                current->path == resolved) {
                return record_for(*current);
            }
        }
        // service.py link_external (L2145-2206): no copy, no hash — the
        // resolved path is recorded as path AND source_uri, identity facts
        // ride metadata["external_stat"], the asset is flagged
        // metadata["external"]=true, and the legacy bridge lands on the
        // asset only when the id is still unclaimed.
        if (!fs::is_regular_file(resolved_path, ec)) {
            throw std::runtime_error("External file not found: " + resolved);
        }
        DataAsset asset = new_asset(
            name.empty() ? resolved_path.filename().generic_string() : name,
            kind, format, Json::object());
        asset.metadata["external"] = true;
        if (legacy_resource_id.has_value() && !legacy_resource_id->empty() &&
            index.asset_by_legacy_id(*legacy_resource_id) == nullptr) {
            asset.legacy_resource_id = *legacy_resource_id;
        }
        DataVersion version;
        version.id = pwb::domain::VersionId(pwb::domain::make_id("ver_"));
        version.asset_id = asset.id;
        version.version_number = 1;
        version.stage = DataStage::Raw;
        version.managed = false;
        version.path = resolved;
        version.source_uri = resolved;
        version.format = format;
        const auto size = fs::file_size(resolved_path, ec);
        if (!ec) version.size_bytes = static_cast<std::int64_t>(size);
        Json stat = Json::object();
        stat["size"] = ec ? 0 : static_cast<std::int64_t>(size);
        stat["mtime_ns"] = mtime_ns_of(resolved_path);
        version.metadata["external_stat"] = std::move(stat);
        version.created_at = pwb::domain::now_iso8601();
        asset.current_version_id = version.id;
        // Same atomic new-asset+first-version+current shape as import_raw.
        require_ok(repo_.import_raw_transaction(asset, version));
        return version_record_of(version, &asset, project_path_);
    }

    // Managed RAW idempotence: (source_uri, sha256) already imported → the
    // existing immutable version (adapter.py:306-313 + _find_managed_raw
    // predicates).
    if (effective.has_value()) {
        if (const auto found =
                index.managed_raw_for(resolved, *effective)) {
            const DataVersion* hit = index.version(*found);
            if (hit != nullptr && hit->managed &&
                hit->stage == DataStage::Raw && !hit->trashed &&
                hit->source_uri.has_value() &&
                *hit->source_uri == resolved && hit->sha256.has_value() &&
                *hit->sha256 == *effective) {
                bridge_legacy_id(repo_, hit->id.str(), legacy_resource_id);
                return record_for(*hit);
            }
        }
    }
    if (bridged != nullptr && bridged->current_version_id.has_value()) {
        const DataVersion* current =
            index.version(bridged->current_version_id->str());
        if (current != nullptr) {
            if (!effective.has_value()) {
                effective = pwb::catalog::sha256_file_or_none(resolved_path);
            }
            if (effective.has_value() && current->sha256.has_value() &&
                *effective == *current->sha256) {
                bridge_legacy_id(repo_, current->id.str(),
                                 legacy_resource_id);
                return record_for(*current);
            }
            // The SAME asset's source changed: register V2 of this asset
            // (parent lineage), never a phantom asset (adapter.py:326-332).
            const int version_number = document.value().next_version_number(
                pwb::domain::AssetId(bridged->id.str()));
            std::string bridged_format;
            if (const auto it = bridged->metadata.find("format");
                bridged->metadata.is_object() &&
                it != bridged->metadata.end() && it->is_string()) {
                bridged_format = it->get<std::string>();
            }
            DataVersion next;
            {
                std::vector<std::string> targets{staging_target(
                    project_path_, DataStage::Raw, bridged->id.str())};
                StagingLease lease(repo_, targets, "register");
                next = build_managed_version(
                    project_path_, resolved_path, resolved,
                    bridged->id.str(), DataStage::Raw,
                    {current->id.str()}, std::nullopt, Json::object(),
                    bridged_format, version_number,
                    /*register_blob=*/false, std::nullopt);
            }
            const DataError error = repo_.commit_version_transaction(
                next, pwb::domain::AssetId(bridged->id.str()), std::nullopt);
            if (!error.ok()) {
                rollback_placed_payload(project_path_, next.path);
                fail(error);
            }
            bridge_legacy_id(repo_, next.id.str(), legacy_resource_id);
            const auto stored = pwb::catalog::get_version_model(
                repo_.writable_database(), next.id.str());
            const auto owner = pwb::catalog::get_asset_model(
                repo_.writable_database(), bridged->id.str());
            return version_record_of(
                stored.value_or(next),
                owner.has_value() ? &*owner : nullptr, project_path_);
        }
    }

    // service.py import_raw (L2055-2143): new asset + managed RAW version
    // + current pointer in ONE transaction; every managed RAW import
    // registers its payload in the content store (register_blob=true) so
    // later imports of the same content dedup to the shared blob; the
    // caller digest is the dedup fast-path proof candidate
    // (known_sha256 → place_managed_file re-proves before adopting).
    DataAsset asset =
        new_asset(name.empty() ? resolved_path.filename().generic_string()
                               : name,
                  kind, format, Json::object());
    if (legacy_resource_id.has_value() && !legacy_resource_id->empty() &&
        live_asset_by_legacy_id(index, *legacy_resource_id) == nullptr) {
        asset.legacy_resource_id = *legacy_resource_id;
    }
    if (!fs::is_regular_file(resolved_path, ec)) {
        throw std::runtime_error("Source file not found: " + resolved);
    }
    DataVersion version;
    {
        std::vector<std::string> targets{
            staging_target(project_path_, DataStage::Raw, asset.id.str()),
            blob_staging_target(project_path_)};
        StagingLease lease(repo_, targets, "register");
        version = build_managed_version(
            project_path_, resolved_path, resolved, asset.id.str(),
            DataStage::Raw, /*parents=*/{}, std::nullopt, Json::object(),
            format, /*version_number=*/1, /*register_blob=*/true,
            effective);
    }
    asset.current_version_id = version.id;
    const DataError error = repo_.import_raw_transaction(asset, version);
    if (!error.ok()) {
        rollback_placed_payload(project_path_, version.path);
        fail(error);
    }
    return version_record_of(version, &asset, project_path_);
}

}  // namespace pwb::closure_workflow
