// 01-line closure — concrete catalog adapter implementation over the
// CONV-31b deep core. Composition semantics mirror service.py exactly:
//   * import_raw        — service.py 2055 (place → add → one save → rollback)
//   * create_derived    — service.py 2645
//   * materialize       — service.py 2208 (register_version shape)
//   * promote_version   — service.py 3665 (frozen shapes via version_promote)
//   * register_run      — service.py 2734 / update_run_status 2770 (terminal
//                         guard, aliases complete/completed)
//   * trash/restore     — trash_service two-phase with the core save hook
//   * repair_ghost_runs — service.py 3780 (#1219 always-producing set)
//   * rebase            — service.py 4538 (document-first + full save)
// A failed save rolls the composition back in memory AND unlinks the placed
// payload (CAS blobs are shared and never unlinked); nothing is published.
#include <chrono>
#include "closure_catalog_service.hpp"

#include <pwb/catalog/dedup.hpp>
#include <pwb/catalog/lineage_graph.hpp>
#include <pwb/catalog/refs.hpp>
#include <pwb/catalog/resolve.hpp>
#include <pwb/catalog/tags.hpp>
#include <pwb/catalog/trash.hpp>
#include <pwb/project/paths.hpp>

#include <algorithm>
#include <cctype>
#include <sys/stat.h>

namespace pwb::app::closure_catalog {

namespace {

using catalog::DataAsset;
using catalog::DataRun;
using catalog::DataVersion;
using catalog::DirtySet;
using domain::DataError;
using domain::ErrorCode;

fs::path project_dir_of(const fs::path& project_file) {
    return project_file.parent_path();
}

fs::path absolute_payload_(const fs::path& project_file,
                           const std::string& rel) {
    if (rel.empty()) return {};
    fs::path p(rel);
    if (p.is_absolute()) return p;
    return project_dir_of(project_file) / p;
}

DataError raise_(DataError error) {
    throw domain::DataException(std::move(error));
}

catalog::SaveHook core_save_hook_(catalog::CatalogServiceCore& core) {
    return [&core](const DirtySet& dirty) { return core.save(dirty); };
}

// Python Path.resolve() parity — never throws (best-effort absolutization).
std::string resolved_posix_(const fs::path& path) {
    std::error_code ec;
    const fs::path resolved = fs::weakly_canonical(path, ec);
    return (ec ? path : resolved).generic_string();
}

}  // namespace

// ---------------------------------------------------------------------------
// CatalogChangeFeed
// ---------------------------------------------------------------------------

CatalogChangeFeed::Subscription CatalogChangeFeed::subscribe(
    std::function<void(const CatalogChangeEvent&)> listener) {
    std::lock_guard<std::mutex> lock(mutex_);
    const std::uint64_t id = next_id_++;
    listeners_.emplace(id, std::move(listener));
    return Subscription(this, id);
}

std::size_t CatalogChangeFeed::listener_count() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return listeners_.size();
}

void CatalogChangeFeed::publish(const CatalogChangeEvent& event) {
    // Snapshot under the lock; run outside it so a listener may re-enter.
    std::vector<std::function<void(const CatalogChangeEvent&)>> snapshot;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        snapshot.reserve(listeners_.size());
        for (auto& [id, listener] : listeners_) snapshot.push_back(listener);
    }
    for (auto& listener : snapshot) {
        try {
            listener(event);
        } catch (...) {
            // A misbehaving consumer must never break the mutation path.
        }
    }
}

void CatalogChangeFeed::unsubscribe(std::uint64_t id) {
    std::lock_guard<std::mutex> lock(mutex_);
    listeners_.erase(id);
}

CatalogChangeFeed::Subscription::~Subscription() {
    if (feed_ != nullptr) feed_->unsubscribe(id_);
}

CatalogChangeFeed::Subscription::Subscription(Subscription&& other) noexcept
    : feed_(other.feed_), id_(other.id_) {
    other.feed_ = nullptr;
}

CatalogChangeFeed::Subscription&
CatalogChangeFeed::Subscription::operator=(Subscription&& other) noexcept {
    if (this != &other) {
        if (feed_ != nullptr) feed_->unsubscribe(id_);
        feed_ = other.feed_;
        id_ = other.id_;
        other.feed_ = nullptr;
    }
    return *this;
}

void CatalogChangeFeed::Subscription::cancel() {
    if (feed_ != nullptr) {
        feed_->unsubscribe(id_);
        feed_ = nullptr;
    }
}

// ---------------------------------------------------------------------------
// open / close / plumbing
// ---------------------------------------------------------------------------

domain::Result<std::unique_ptr<CatalogClosureAdapter>>
CatalogClosureAdapter::open(const fs::path& project_path,
                            CatalogProjectIdentity identity,
                            catalog::CatalogOpenOptions options) {
    auto opened = catalog::open_catalog(project_path, options);
    if (!opened.is_ok()) return opened.error();
    auto adapter = std::unique_ptr<CatalogClosureAdapter>(
        new CatalogClosureAdapter(std::move(identity)));
    adapter->core_store_.emplace(std::move(opened.value()));
    return adapter;
}

CatalogClosureAdapter::CatalogClosureAdapter(CatalogProjectIdentity identity)
    : identity_(std::move(identity)), review_(this) {}

CatalogClosureAdapter::~CatalogClosureAdapter() {
    try {
        close();
    } catch (...) {
        // Destructors never raise (Python close() swallow parity).
    }
}

catalog::CatalogServiceCore& CatalogClosureAdapter::core_() {
    if (!core_store_.has_value()) {
        raise_(DataError(ErrorCode::InvalidArgument,
                         "数据目录已关闭；请重新打开工程后再执行该操作。"));
    }
    return *core_store_;
}

const catalog::CatalogServiceCore& CatalogClosureAdapter::core_() const {
    if (!core_store_.has_value()) {
        raise_(DataError(ErrorCode::InvalidArgument,
                         "数据目录已关闭；请重新打开工程后再执行该操作。"));
    }
    return *core_store_;
}

void CatalogClosureAdapter::ensure_open_(const std::string& op) const {
    (void)op;
    if (closed_ || !core_store_.has_value()) {
        raise_(DataError(ErrorCode::InvalidArgument,
                         "数据目录已关闭；请重新打开工程后再执行该操作。"));
    }
}

bool CatalogClosureAdapter::is_closed() const {
    std::lock_guard<std::recursive_mutex> lock(mutex_);
    return closed_;
}

int CatalogClosureAdapter::document_revision() const {
    std::lock_guard<std::recursive_mutex> lock(mutex_);
    if (!core_store_.has_value()) return 0;
    return core_store_->document_revision();
}

std::optional<long long> CatalogClosureAdapter::store_revision() const {
    std::lock_guard<std::recursive_mutex> lock(mutex_);
    if (!core_store_.has_value()) return std::nullopt;
    return core_store_->index_revision();
}

std::optional<long long> CatalogClosureAdapter::flushed_revision() const {
    std::lock_guard<std::recursive_mutex> lock(mutex_);
    if (!core_store_.has_value()) return std::nullopt;
    return core_store_->flushed_revision();
}

catalog::DocumentIndex CatalogClosureAdapter::fresh_index_() {
    // value copy of the core's snapshot (callers iterate it while mutating)
    return catalog::DocumentIndex(core_().document());
}

catalog::WorkingCopyContext CatalogClosureAdapter::wc_context_() {
    catalog::WorkingCopyContext context;
    context.project_path = identity_.project_path;
    context.repo = &core_().repository();
    context.document = &core_().document();
    context.pending_commit_assets = &pending_commit_assets_;
    return context;
}

// Events are built inline at each publish site (identity + revision +
// serial stamped from the live core at that moment).

void CatalogClosureAdapter::publish_after_(CatalogChangeEvent event) {
    queued_events_.push_back(std::move(event));
}

void CatalogClosureAdapter::flush_queued_() {
    // Called with mutex_ NOT held (unique_lock released by the caller).
    std::vector<CatalogChangeEvent> events;
    events.swap(queued_events_);
    for (auto& event : events) feed_.publish(event);
}

const CatalogRecoveryReport& CatalogClosureAdapter::last_recovery_report()
    const {
    std::lock_guard<std::recursive_mutex> lock(mutex_);
    return recovery_;
}

std::string CatalogClosureAdapter::conflict_guidance() const {
    // 面向用户的冲突语义（与 PR 文档一致，禁止自动覆盖冲突版本）。
    return "数据目录采用单写者与修订号（revision）保护："
           "当另一实例已提交（manifest/stale-write 冲突）时，本会话的写入会被拒绝，"
           "系统不会自动覆盖他人提交；请重新打开工程后重试。"
           "异常退出后的工作副本会在下次打开工程时自动恢复："
           "已提交的记录被清理，未落盘的改动回到 dirty 状态，载荷缺失的副本被丢弃并报告。";
}

// ---------------------------------------------------------------------------
// CatalogReadService
// ---------------------------------------------------------------------------

const catalog::CatalogDocument& CatalogClosureAdapter::document() const {
    std::lock_guard<std::recursive_mutex> lock(mutex_);
    return core_().document();
}

const catalog::CatalogDocument& CatalogClosureAdapter::document() {
    std::lock_guard<std::recursive_mutex> lock(mutex_);
    return core_().document();
}

const catalog::DataAsset* CatalogClosureAdapter::get_asset(
    const std::string& asset_id) {
    std::lock_guard<std::recursive_mutex> lock(mutex_);
    if (closed_) return nullptr;
    return core_().find_asset(asset_id);
}

std::vector<catalog::DataVersion> CatalogClosureAdapter::list_versions(
    const std::string& asset_id) {
    std::lock_guard<std::recursive_mutex> lock(mutex_);
    ensure_open_("list_versions");
    std::vector<catalog::DataVersion> out;
    const auto* versions = core_().index().versions_of_asset(asset_id);
    if (versions == nullptr) return out;
    out.reserve(versions->size());
    for (const auto* version : *versions) out.push_back(*version);
    return out;
}

std::vector<catalog::DataAsset> CatalogClosureAdapter::list_assets(
    bool include_trashed) {
    std::lock_guard<std::recursive_mutex> lock(mutex_);
    ensure_open_("list_assets");
    std::vector<catalog::DataAsset> out;
    for (const auto& asset : core_().document().assets) {
        if (!include_trashed && asset.trashed) continue;
        out.push_back(asset);
    }
    return out;
}

fs::path CatalogClosureAdapter::resolve_path(
    const catalog::DataVersion& version) {
    std::lock_guard<std::recursive_mutex> lock(mutex_);
    if (closed_) return {};
    return catalog::resolve_payload_path(identity_.project_path, version);
}

std::optional<ui_data_core::CatalogReadService::LineageResult>
CatalogClosureAdapter::get_lineage(const std::string& version_id) {
    std::lock_guard<std::recursive_mutex> lock(mutex_);
    if (closed_) return std::nullopt;
    const catalog::DataVersion* version =
        core_().find_version(version_id);
    if (version == nullptr) return std::nullopt;
    LineageResult result;
    for (const auto& parent_id : version->parent_version_ids) {
        const catalog::DataVersion* parent = core_().find_version(parent_id.str());
        if (parent != nullptr) result.parents.push_back(*parent);
    }
    for (const auto& candidate : core_().document().versions) {
        if (std::find(candidate.parent_version_ids.begin(),
                      candidate.parent_version_ids.end(),
                      version->id) != candidate.parent_version_ids.end()) {
            result.children.push_back(candidate);
        }
    }
    if (version->run_id.has_value()) {
        const catalog::DataRun* run = core_().find_run(version->run_id->str());
        if (run != nullptr) result.run = *run;
    }
    return result;
}

std::unordered_map<std::string, domain::Json>
CatalogClosureAdapter::lineage_summaries() {
    std::lock_guard<std::recursive_mutex> lock(mutex_);
    ensure_open_("lineage_summaries");
    const auto summaries = catalog::compute_lineage_summaries(
        core_().document(), core_().index());
    std::unordered_map<std::string, domain::Json> out;
    out.reserve(summaries.size());
    for (const auto& [version_id, summary] : summaries) {
        domain::Json json = domain::Json::object();
        if (summary.to_raw.has_value()) {
            json["to_raw"] = *summary.to_raw;
        } else {
            json["to_raw"] = nullptr;
        }
        json["broken"] = summary.broken;
        json["has_parents"] = summary.has_parents;
        out.emplace(version_id, std::move(json));
    }
    return out;
}

int CatalogClosureAdapter::mutation_serial() const {
    std::lock_guard<std::recursive_mutex> lock(mutex_);
    if (!core_store_.has_value()) return 0;
    return static_cast<int>(core_store_->mutation_serial());
}

std::vector<std::string> CatalogClosureAdapter::search_assets(
    const catalog::AssetSearchQuery& query) {
    std::lock_guard<std::recursive_mutex> lock(mutex_);
    ensure_open_("search_assets");
    return catalog::search_assets_scan(core_().document(), core_().index(),
                                       query);
}

// ---------------------------------------------------------------------------
// CatalogServiceApi — reads
// ---------------------------------------------------------------------------

catalog::DataVersion CatalogClosureAdapter::get_version(
    const std::string& version_id) {
    std::lock_guard<std::recursive_mutex> lock(mutex_);
    ensure_open_("get_version");
    const catalog::DataVersion* version = core_().find_version(version_id);
    if (version == nullptr) {
        raise_(DataError(ErrorCode::NotFound,
                         "Unknown version: " + version_id));
    }
    return *version;
}

bool CatalogClosureAdapter::asset_exists(const std::string& asset_id) {
    std::lock_guard<std::recursive_mutex> lock(mutex_);
    if (closed_) return false;
    return core_().find_asset(asset_id) != nullptr;
}

std::vector<catalog::DataAsset> CatalogClosureAdapter::get_trashed_assets() {
    std::lock_guard<std::recursive_mutex> lock(mutex_);
    ensure_open_("get_trashed_assets");
    std::vector<catalog::DataAsset> out;
    for (const auto& asset : core_().document().assets) {
        if (asset.trashed) out.push_back(asset);
    }
    return out;
}

// ---------------------------------------------------------------------------
// Rollback (service.py _rollback parity)
// ---------------------------------------------------------------------------

void CatalogClosureAdapter::rollback_(Rollback&& plan) {
    // Runs under the adapter lock (caller holds it); core removals keep the
    // maps coherent (identity pointers, #1044).
    for (catalog::DataAsset* asset : plan.assets) {
        if (asset != nullptr) core_().remove_asset(asset);
    }
    for (catalog::DataVersion* version : plan.versions) {
        if (version != nullptr) core_().remove_version(version);
    }
    for (catalog::DataRun* run : plan.runs) {
        if (run != nullptr) core_().remove_run(run);
    }
    if (plan.restore_current_asset.has_value()) {
        if (catalog::DataAsset* asset =
                core_().find_asset(*plan.restore_current_asset);
            asset != nullptr) {
            if (plan.restore_current_version.has_value()) {
                asset->current_version_id =
                    domain::VersionId(*plan.restore_current_version);
            } else {
                asset->current_version_id = std::nullopt;
            }
        }
    }
    if (plan.restore_run_outputs.has_value()) {
        if (catalog::DataRun* run =
                core_().find_run(plan.restore_run_outputs->first);
            run != nullptr) {
            run->output_version_ids = plan.restore_run_outputs->second;
        }
    }
    if (!plan.payload_rel.has_value() || plan.payload_rel->empty()) return;
    const fs::path payload =
        absolute_payload_(identity_.project_path, *plan.payload_rel);
    if (catalog::is_cas_path(identity_.project_path, *plan.payload_rel)) {
        // Shared, content-addressed, immutable: a failed save must never
        // unlink a blob other versions may reference.
        return;
    }
    if (!plan.restore_payload_to.empty() && fs::exists(payload)) {
        // A consumed working copy goes back where it came from.
        std::error_code ec;
        fs::rename(payload, plan.restore_payload_to, ec);
        return;
    }
    std::error_code ec;
    fs::remove(payload, ec);
    // Prune the now-empty version/asset directories — exactly the two
    // levels Python prunes (payload.parent, payload.parent.parent).
    for (fs::path directory = payload.parent_path();
         directory != project_dir_of(identity_.project_path);
         directory = directory.parent_path()) {
        std::error_code rmdir_ec;
        fs::remove(directory, rmdir_ec);  // fails on non-empty — fine
    }
}

// ---------------------------------------------------------------------------
// Asset lifecycle writes
// ---------------------------------------------------------------------------

catalog::DataAsset CatalogClosureAdapter::trash_asset(
    const std::string& asset_id, const std::string& reason) {
    std::unique_lock<std::recursive_mutex> lock(mutex_);
    ensure_open_("trash_asset");
    catalog::DataAsset* before = core_().find_asset(asset_id);
    if (before == nullptr) {
        raise_(DataError(ErrorCode::NotFound, "Unknown asset: " + asset_id));
    }
    auto index = fresh_index_();
    DataError error = catalog::trash_asset(
        &core_().document(), index, identity_.project_path, asset_id, reason,
        core_save_hook_(core_()));
    if (error.code != ErrorCode::Ok) {
        raise_(std::move(error));
    }
    core_().invalidate_maps();
    catalog::DataAsset out;
    if (const catalog::DataAsset* asset = core_().find_asset(asset_id);
        asset != nullptr) {
        out = *asset;
    }
    CatalogChangeEvent event = [&] {
        CatalogChangeEvent e;
        e.kind = CatalogChangeEvent::Kind::AssetsChanged;
        e.identity = identity_;
        e.store_revision = core_store_->index_revision().value_or(-1);
        e.mutation_serial = core_store_->mutation_serial();
        e.asset_ids.push_back(asset_id);
        e.note = "资产已移入回收站：" + asset_id;
        return e;
    }();
    publish_after_(std::move(event));
    lock.unlock();
    flush_queued_();
    return out;
}

catalog::DataAsset CatalogClosureAdapter::restore_asset(
    const std::string& asset_id) {
    std::unique_lock<std::recursive_mutex> lock(mutex_);
    ensure_open_("restore_asset");
    auto index = fresh_index_();
    DataError error = catalog::restore_asset(
        &core_().document(), index, identity_.project_path, asset_id,
        core_save_hook_(core_()));
    if (error.code != ErrorCode::Ok) {
        raise_(std::move(error));
    }
    core_().invalidate_maps();
    catalog::DataAsset out;
    if (const catalog::DataAsset* asset = core_().find_asset(asset_id);
        asset != nullptr) {
        out = *asset;
    }
    CatalogChangeEvent event;
    event.kind = CatalogChangeEvent::Kind::AssetsChanged;
    event.identity = identity_;
    event.store_revision = core_store_->index_revision().value_or(-1);
    event.mutation_serial = core_store_->mutation_serial();
    event.asset_ids.push_back(asset_id);
    event.note = "资产已从回收站恢复：" + asset_id;
    publish_after_(std::move(event));
    lock.unlock();
    flush_queued_();
    return out;
}

// ---------------------------------------------------------------------------
// Import / derived / materialize / promote
// ---------------------------------------------------------------------------

domain::Result<catalog::DataVersion> CatalogClosureAdapter::import_raw(
    const fs::path& source_path, std::optional<std::string> name,
    std::optional<std::string> type, std::optional<std::string> format,
    domain::Json metadata, std::optional<std::string> legacy_resource_id) {
    std::unique_lock<std::recursive_mutex> lock(mutex_);
    ensure_open_("import_raw");
    std::error_code stat_ec;
    if (!fs::is_regular_file(source_path, stat_ec)) {
        raise_(DataError(ErrorCode::InvalidArgument,
                         "Source file not found: " + source_path.string()));
    }
    catalog::CatalogServiceCore& core = core_();

    DataAsset asset;
    asset.id = domain::AssetId(catalog::new_ref_id("asset"));
    asset.name = name.has_value() ? *name : source_path.filename().string();
    asset.type = type.value_or("unknown");
    asset.metadata = metadata.is_object()
                         ? metadata
                         : domain::Json::object();
    if (format.has_value() && !format->empty()) {
        asset.metadata["format"] = *format;
    }
    asset.created_at = catalog::utc_now_iso();
    asset.updated_at = asset.created_at;

    // Staging lease spans place → commit (the bulk-import funnel guard).
    catalog::StagingLeaseGuard lease(
        core.repository(),
        {catalog::staging_target(identity_.project_path,
                                 domain::DataStage::Raw, asset.id.str()),
         catalog::blob_staging_target(identity_.project_path)});

    DataVersion version;
    version.id = domain::VersionId(catalog::new_ref_id("ver"));
    version.asset_id = asset.id;
    version.version_number = 1;  // first version of a new asset
    version.stage = domain::DataStage::Raw;
    version.managed = true;
    version.source_uri = resolved_posix_(source_path);
    version.format = format.value_or(std::string());
    version.metadata = metadata.is_object() ? metadata : domain::Json::object();
    version.created_at = catalog::utc_now_iso();

    catalog::PlaceManagedOptions place_options;
    place_options.keep_source = true;
    // Every managed RAW import registers its payload in the content store
    // so later imports of the same content dedup to it (service.py 2055).
    place_options.register_blob = true;
    auto placed = catalog::place_managed_file(
        source_path, identity_.project_path, domain::DataStage::Raw,
        asset.id.str(), version.id.str(), place_options);
    if (!placed.is_ok()) {
        raise_(placed.error());
    }
    version.path = placed.value().rel_path;
    version.size_bytes = placed.value().size_bytes;
    version.sha256 = placed.value().sha256;

    // service.py 2113-2119 parity: bind only when no LIVE asset already
    // carries this legacy id — a duplicate bridge would make
    // resolve_legacy_resource unstable. Decided BEFORE add_asset and set on
    // the LOCAL asset: post-add edits through the node pointer would not
    // reach the materialized cache (service_core dual-storage discipline).
    if (legacy_resource_id.has_value()) {
        bool legacy_taken = false;
        for (const auto& existing : core.document().assets) {
            if (!existing.trashed && existing.legacy_resource_id.has_value() &&
                *existing.legacy_resource_id == *legacy_resource_id) {
                legacy_taken = true;
                break;
            }
        }
        if (!legacy_taken) {
            asset.legacy_resource_id = *legacy_resource_id;
        }
    }

    catalog::DataAsset* added = core.add_asset(asset);
    catalog::DataVersion* added_version = core.add_version(version);
    if (added == nullptr || added_version == nullptr) {
        raise_(DataError(ErrorCode::Unknown, "catalog document add failed"));
    }
    added->current_version_id = version.id;

    DirtySet dirty;
    dirty.mark_asset(asset.id.str());
    dirty.mark_version(version.id.str());
    DataError error = core.save(dirty);
    if (error.code != ErrorCode::Ok) {
        Rollback plan;
        plan.assets.push_back(added);
        plan.versions.push_back(added_version);
        plan.payload_rel = version.path;
        rollback_(std::move(plan));
        raise_(std::move(error));
    }

    CatalogChangeEvent event;
    event.kind = CatalogChangeEvent::Kind::VersionsChanged;
    event.identity = identity_;
    event.store_revision = core.index_revision().value_or(-1);
    event.mutation_serial = core.mutation_serial();
    event.asset_ids.push_back(asset.id.str());
    event.version_ids.push_back(version.id.str());
    event.note = "导入完成：" + asset.name;
    publish_after_(std::move(event));
    lock.unlock();
    flush_queued_();
    return version;
}

domain::Result<catalog::DataVersion> CatalogClosureAdapter::link_external(
    const fs::path& path, std::optional<std::string> name,
    std::optional<std::string> type, std::optional<std::string> format,
    domain::Json metadata, std::optional<std::string> legacy_resource_id) {
    std::unique_lock<std::recursive_mutex> lock(mutex_);
    ensure_open_("link_external");
    catalog::CatalogServiceCore& core = core_();
    std::error_code stat_ec;
    if (!fs::is_regular_file(path, stat_ec)) {
        raise_(DataError(ErrorCode::InvalidArgument,
                         "External file not found: " + path.string()));
    }
    // Mutate + save under one discipline (#517): asset + version + current
    // pointer land in the same canonical save, rolled back on failure.
    DataAsset asset;
    asset.id = domain::AssetId(catalog::new_ref_id("asset"));
    asset.name = name.has_value() ? *name : path.filename().string();
    asset.type = type.value_or("unknown");
    asset.metadata = metadata.is_object() ? metadata : domain::Json::object();
    asset.metadata["external"] = true;
    asset.created_at = catalog::utc_now_iso();
    asset.updated_at = asset.created_at;

    const auto stat = fs::last_write_time(path, stat_ec);
    (void)stat;
    DataVersion version;
    version.id = domain::VersionId(catalog::new_ref_id("ver"));
    version.asset_id = asset.id;
    version.version_number = 1;
    version.stage = domain::DataStage::Raw;
    version.managed = false;
    version.path = resolved_posix_(path);
    version.source_uri = version.path;
    version.format = format.value_or(std::string());
    version.created_at = catalog::utc_now_iso();
    // Identity fingerprint for a later fail-closed relink (D9): size +
    // mtime are the recorded facts a relocated file must match when no
    // digest was ever taken. The mtime convention is the deep core's
    // (sources.cpp stat_fingerprint tier; POSIX records the st_mtim
    // nsec component, Windows records full-epoch ns — each platform's
    // recorder and comparator use the same convention).
#if defined(_WIN32)
    {
        std::error_code probe_ec{};
        if (fs::is_regular_file(path, probe_ec) && !probe_ec) {
            const auto size = fs::file_size(path, probe_ec);
            const auto written = fs::last_write_time(path, probe_ec);
            if (!probe_ec) {
                version.size_bytes = static_cast<std::int64_t>(size);
                domain::Json external_stat = domain::Json::object();
                external_stat["size"] = static_cast<std::int64_t>(size);
                external_stat["mtime_ns"] =
                    std::chrono::duration_cast<std::chrono::nanoseconds>(
                        written.time_since_epoch())
                        .count();
                version.metadata["external_stat"] = external_stat;
            }
        }
    }
#else
    struct stat st = {};
    if (::stat(path.string().c_str(), &st) == 0) {
        version.size_bytes = static_cast<std::int64_t>(st.st_size);
        domain::Json external_stat = domain::Json::object();
        external_stat["size"] = static_cast<std::int64_t>(st.st_size);
        external_stat["mtime_ns"] = static_cast<std::int64_t>(st.st_mtim.tv_nsec);
        version.metadata["external_stat"] = external_stat;
    }
#endif
    version.metadata["format"] = version.format;

    // Pre-add legacy decision (see import_raw: node edits after a cache
    // materialize never reach it).
    if (legacy_resource_id.has_value()) {
        bool legacy_taken = false;
        for (const auto& existing : core.document().assets) {
            if (!existing.trashed && existing.legacy_resource_id.has_value() &&
                *existing.legacy_resource_id == *legacy_resource_id) {
                legacy_taken = true;
                break;
            }
        }
        if (!legacy_taken) {
            asset.legacy_resource_id = *legacy_resource_id;
        }
    }

    catalog::DataAsset* added = core.add_asset(asset);
    catalog::DataVersion* added_version = core.add_version(version);
    if (added == nullptr || added_version == nullptr) {
        raise_(DataError(ErrorCode::Unknown, "catalog document add failed"));
    }
    added->current_version_id = version.id;

    DirtySet dirty;
    dirty.mark_asset(asset.id.str());
    dirty.mark_version(version.id.str());
    DataError error = core.save(dirty);
    if (error.code != ErrorCode::Ok) {
        Rollback plan;
        plan.assets.push_back(added);
        plan.versions.push_back(added_version);
        rollback_(std::move(plan));
        raise_(std::move(error));
    }

    CatalogChangeEvent event;
    event.kind = CatalogChangeEvent::Kind::VersionsChanged;
    event.identity = identity_;
    event.store_revision = core.index_revision().value_or(-1);
    event.mutation_serial = core.mutation_serial();
    event.asset_ids.push_back(asset.id.str());
    event.version_ids.push_back(version.id.str());
    event.note = "外部链接已登记：" + asset.name;
    publish_after_(std::move(event));
    lock.unlock();
    flush_queued_();
    return version;
}

catalog::DataVersion CatalogClosureAdapter::create_derived(
    const fs::path& source_path,
    const std::vector<std::string>& parent_version_ids,
    const std::string& name, const std::string& operation,
    const std::string& generator) {
    std::unique_lock<std::recursive_mutex> lock(mutex_);
    ensure_open_("create_derived");
    catalog::CatalogServiceCore& core = core_();

    std::vector<const catalog::DataVersion*> parents;
    for (const auto& parent_id : parent_version_ids) {
        const catalog::DataVersion* parent = core.find_version(parent_id);
        if (parent == nullptr) {
            raise_(DataError(ErrorCode::NotFound,
                             "Unknown version: " + parent_id));
        }
        parents.push_back(parent);
    }
    std::string parent_type;
    if (!parents.empty()) {
        if (const catalog::DataAsset* parent_asset =
                core.find_asset(parents[0]->asset_id.str());
            parent_asset != nullptr) {
            parent_type = parent_asset->type;
        }
    }
    std::error_code stat_ec;
    if (!fs::is_regular_file(source_path, stat_ec)) {
        raise_(DataError(ErrorCode::InvalidArgument,
                         "Source file not found: " + source_path.string()));
    }

    DataAsset asset;
    asset.id = domain::AssetId(catalog::new_ref_id("asset"));
    asset.name = name.empty() ? source_path.stem().string() : name;
    asset.type = parent_type.empty() ? "unknown" : parent_type;
    asset.created_at = catalog::utc_now_iso();
    asset.updated_at = asset.created_at;

    std::optional<DataRun> run;
    if (!operation.empty()) {
        run = DataRun();
        run->id = domain::RunId(catalog::new_ref_id("run"));
        run->operation = operation;
        run->parameters = domain::Json::object();
        run->generator = generator;
        run->status = "completed";
        run->created_at = catalog::utc_now_iso();
        for (const auto* parent : parents) {
            run->input_version_ids.push_back(parent->id);
        }
    }

    catalog::StagingLeaseGuard lease(
        core.repository(),
        {catalog::staging_target(identity_.project_path,
                                 domain::DataStage::Derived, asset.id.str())});

    DataVersion version;
    version.id = domain::VersionId(catalog::new_ref_id("ver"));
    version.asset_id = asset.id;
    version.stage = domain::DataStage::Derived;
    version.managed = true;
    version.source_uri = resolved_posix_(source_path);
    version.created_at = catalog::utc_now_iso();
    for (const auto* parent : parents) {
        version.parent_version_ids.push_back(parent->id);
    }
    if (run.has_value()) version.run_id = run->id;

    // Next version number (max+1 over the asset's versions; new asset → 1).
    int version_number = 1;
    if (const auto* existing = core.index().versions_of_asset(asset.id.str());
        existing != nullptr) {
        for (const auto* candidate : *existing) {
            version_number = std::max(version_number, candidate->version_number + 1);
        }
    }
    version.version_number = version_number;

    auto placed = catalog::place_managed_file(
        source_path, identity_.project_path, domain::DataStage::Derived,
        asset.id.str(), version.id.str(),
        catalog::PlaceManagedOptions{/*keep_source=*/true});
    if (!placed.is_ok()) {
        raise_(placed.error());
    }
    version.path = placed.value().rel_path;
    version.size_bytes = placed.value().size_bytes;
    version.sha256 = placed.value().sha256;

    catalog::DataAsset* added = core.add_asset(asset);
    catalog::DataVersion* added_version = core.add_version(version);
    catalog::DataRun* added_run =
        run.has_value() ? core.add_run(*run) : nullptr;
    if (added == nullptr || added_version == nullptr ||
        (!parent_version_ids.empty() && run.has_value() &&
         added_run == nullptr)) {
        raise_(DataError(ErrorCode::Unknown, "catalog document add failed"));
    }
    added->current_version_id = version.id;
    if (added_run != nullptr) added_run->output_version_ids = {version.id};

    DirtySet dirty;
    dirty.mark_asset(asset.id.str());
    dirty.mark_version(version.id.str());
    if (added_run != nullptr) dirty.mark_run(added_run->id.str());
    DataError error = core.save(dirty);
    if (error.code != ErrorCode::Ok) {
        Rollback plan;
        plan.assets.push_back(added);
        plan.versions.push_back(added_version);
        plan.runs.push_back(added_run);
        plan.payload_rel = version.path;
        rollback_(std::move(plan));
        raise_(std::move(error));
    }

    CatalogChangeEvent event;
    event.kind = CatalogChangeEvent::Kind::VersionsChanged;
    event.identity = identity_;
    event.store_revision = core.index_revision().value_or(-1);
    event.mutation_serial = core.mutation_serial();
    event.asset_ids.push_back(asset.id.str());
    event.version_ids.push_back(version.id.str());
    if (added_run != nullptr) event.run_ids.push_back(added_run->id.str());
    event.note = "派生结果已注册：" + asset.name;
    publish_after_(std::move(event));
    lock.unlock();
    flush_queued_();
    return version;
}

catalog::DataVersion CatalogClosureAdapter::materialize_external(
    const std::string& version_id, const std::optional<std::string>& run_id) {
    std::unique_lock<std::recursive_mutex> lock(mutex_);
    ensure_open_("materialize_external");
    catalog::CatalogServiceCore& core = core_();

    const catalog::DataVersion* linked = core.find_version(version_id);
    if (linked == nullptr) {
        raise_(DataError(ErrorCode::NotFound, "Unknown version: " + version_id));
    }
    if (linked->managed) {
        raise_(DataError(ErrorCode::InvalidArgument,
                         "Version " + version_id + " is already managed"));
    }
    const fs::path source = catalog::resolve_payload_path(
        identity_.project_path, *linked);
    std::error_code stat_ec;
    if (!fs::is_regular_file(source, stat_ec)) {
        raise_(DataError(ErrorCode::InvalidArgument,
                         "External file not available: " + source.string()));
    }
    const std::string asset_id = linked->asset_id.str();

    // register_version composition (RAW snapshot, parent = the external link).
    catalog::DataAsset* asset = core.find_asset(asset_id);
    if (asset == nullptr) {
        raise_(DataError(ErrorCode::NotFound, "Unknown asset: " + asset_id));
    }
    // run_id must exist (register_version get_run parity), and the new
    // version joins its outputs in the SAME save (atomic run-output
    // linkage; restored on rollback).
    catalog::DataRun* linked_run = nullptr;
    std::vector<domain::VersionId> run_outputs_before;
    if (run_id.has_value()) {
        linked_run = core.find_run(*run_id);
        if (linked_run == nullptr) {
            raise_(DataError(ErrorCode::NotFound, "Unknown run: " + *run_id));
        }
        run_outputs_before = linked_run->output_version_ids;
    }

    DataVersion version;
    version.id = domain::VersionId(catalog::new_ref_id("ver"));
    version.asset_id = linked->asset_id;
    version.stage = domain::DataStage::Raw;
    version.managed = true;
    version.source_uri = resolved_posix_(source);
    version.created_at = catalog::utc_now_iso();
    version.parent_version_ids = {linked->id};
    if (run_id.has_value()) version.run_id = domain::RunId(*run_id);

    int version_number = 1;
    if (const auto* existing = core.index().versions_of_asset(asset_id);
        existing != nullptr) {
        for (const auto* candidate : *existing) {
            version_number = std::max(version_number, candidate->version_number + 1);
        }
    }
    version.version_number = version_number;

    catalog::StagingLeaseGuard lease(
        core.repository(),
        {catalog::staging_target(identity_.project_path,
                                 domain::DataStage::Raw, asset_id)});
    auto placed = catalog::place_managed_file(
        source, identity_.project_path, domain::DataStage::Raw, asset_id,
        version.id.str(), catalog::PlaceManagedOptions{/*keep_source=*/true});
    if (!placed.is_ok()) {
        raise_(placed.error());
    }
    version.path = placed.value().rel_path;
    version.size_bytes = placed.value().size_bytes;
    version.sha256 = placed.value().sha256;

    catalog::DataVersion* added = core.add_version(version);
    if (added == nullptr) {
        raise_(DataError(ErrorCode::Unknown, "catalog document add failed"));
    }
    asset->current_version_id = version.id;
    if (linked_run != nullptr) {
        linked_run->output_version_ids.push_back(version.id);
    }

    DirtySet dirty;
    dirty.mark_asset(asset_id);
    dirty.mark_version(version.id.str());
    if (linked_run != nullptr) dirty.mark_run(*run_id);
    DataError error = core.save(dirty);
    if (error.code != ErrorCode::Ok) {
        // NOTE: the asset is pre-existing — it stays (its damage is undone
        // via restore_current), Python register_version rollback parity.
        Rollback plan;
        plan.versions.push_back(added);
        plan.payload_rel = version.path;
        plan.restore_current_asset = asset_id;
        plan.restore_current_version = linked->id.str();
        if (linked_run != nullptr) {
            plan.restore_run_outputs = std::make_pair(*run_id,
                                                      run_outputs_before);
        }
        rollback_(std::move(plan));
        raise_(std::move(error));
    }

    CatalogChangeEvent event;
    event.kind = CatalogChangeEvent::Kind::VersionsChanged;
    event.identity = identity_;
    event.store_revision = core.index_revision().value_or(-1);
    event.mutation_serial = core.mutation_serial();
    event.asset_ids.push_back(asset_id);
    event.version_ids.push_back(version.id.str());
    event.note = "外部链接已物化为受管快照：" + version.id.str();
    publish_after_(std::move(event));
    lock.unlock();
    flush_queued_();
    return version;
}

catalog::DataVersion CatalogClosureAdapter::promote_version(
    const std::string& version_id, domain::DataStage to_stage,
    const std::optional<std::string>& reviewed_by,
    const std::optional<std::string>& note) {
    std::unique_lock<std::recursive_mutex> lock(mutex_);
    ensure_open_("promote_version");
    catalog::CatalogServiceCore& core = core_();

    const catalog::DataVersion* source = core.find_version(version_id);
    if (source == nullptr) {
        raise_(DataError(ErrorCode::NotFound, "Unknown version: " + version_id));
    }
    if (source->trashed) {
        raise_(DataError(ErrorCode::InvalidArgument,
                         "Cannot promote a trashed version: " + version_id));
    }
    const fs::path source_payload =
        catalog::resolve_payload_path(identity_.project_path, *source);
    std::error_code stat_ec;
    if (!fs::is_regular_file(source_payload, stat_ec)) {
        raise_(DataError(ErrorCode::InvalidArgument,
                         "Source payload not available: " +
                             source_payload.string()));
    }
    catalog::DataAsset* asset = core.find_asset(source->asset_id.str());
    if (asset == nullptr) {
        raise_(DataError(ErrorCode::NotFound,
                         "Unknown asset: " + source->asset_id.str()));
    }
    const std::string previous_current =
        asset->current_version_id.has_value()
            ? asset->current_version_id->str()
            : std::string();

    catalog::PromoteOptions options;
    options.to_stage = to_stage;
    options.reviewed_by = reviewed_by;
    options.note = note;
    DataRun run = catalog::make_promote_run(source->id, options);
    run.id = domain::RunId(catalog::new_ref_id("run"));

    catalog::StagingLeaseGuard lease(
        core.repository(),
        {catalog::staging_target(identity_.project_path, to_stage,
                                 asset->id.str())});

    DataVersion version;
    version.id = domain::VersionId(catalog::new_ref_id("ver"));
    version.asset_id = source->asset_id;
    version.stage = to_stage;
    version.managed = true;
    version.source_uri = resolved_posix_(source_payload);
    version.created_at = catalog::utc_now_iso();
    version.parent_version_ids = {source->id};
    version.run_id = run.id;
    version.metadata = catalog::make_promote_version_metadata(source->id, options);
    if (asset->metadata.contains("format") &&
        asset->metadata["format"].is_string()) {
        version.format = asset->metadata["format"].get<std::string>();
    }

    auto placed = catalog::place_managed_file(
        source_payload, identity_.project_path, to_stage, asset->id.str(),
        version.id.str(), catalog::PlaceManagedOptions{/*keep_source=*/true});
    if (!placed.is_ok()) {
        raise_(placed.error());
    }
    version.path = placed.value().rel_path;
    version.size_bytes = placed.value().size_bytes;
    version.sha256 = placed.value().sha256;
    run.output_version_ids = {version.id};

    // Version numbers re-allocated under the lock (#849-1).
    int version_number = 1;
    if (const auto* existing =
            core.index().versions_of_asset(asset->id.str());
        existing != nullptr) {
        for (const auto* candidate : *existing) {
            version_number = std::max(version_number, candidate->version_number + 1);
        }
    }
    version.version_number = version_number;

    catalog::DataVersion* added = core.add_version(version);
    catalog::DataRun* added_run = core.add_run(run);
    if (added == nullptr || added_run == nullptr) {
        raise_(DataError(ErrorCode::Unknown, "catalog document add failed"));
    }
    asset->current_version_id = version.id;

    DirtySet dirty;
    dirty.mark_asset(asset->id.str());
    dirty.mark_version(version.id.str());
    dirty.mark_run(added_run->id.str());
    DataError error = core.save(dirty);
    if (error.code != ErrorCode::Ok) {
        // NOTE: the asset is pre-existing — it stays (its damage is undone
        // via restore_current), Python promote_version rollback parity.
        Rollback plan;
        plan.versions.push_back(added);
        plan.runs.push_back(added_run);
        plan.payload_rel = version.path;
        plan.restore_current_asset = asset->id.str();
        if (!previous_current.empty()) {
            plan.restore_current_version = previous_current;
        }
        rollback_(std::move(plan));
        raise_(std::move(error));
    }

    CatalogChangeEvent event;
    event.kind = CatalogChangeEvent::Kind::VersionsChanged;
    event.identity = identity_;
    event.store_revision = core.index_revision().value_or(-1);
    event.mutation_serial = core.mutation_serial();
    event.asset_ids.push_back(asset->id.str());
    event.version_ids.push_back(version.id.str());
    event.run_ids.push_back(added_run->id.str());
    event.note = "版本已提升：" + version_id + " → " + version.id.str();
    publish_after_(std::move(event));
    lock.unlock();
    flush_queued_();
    return version;
}

// ---------------------------------------------------------------------------
// Working copies
// ---------------------------------------------------------------------------

fs::path CatalogClosureAdapter::create_working_copy(
    const std::string& version_id) {
    std::unique_lock<std::recursive_mutex> lock(mutex_);
    ensure_open_("create_working_copy");
    auto context = wc_context_();
    auto path = catalog::create_working_copy(
        context, domain::VersionId(version_id), /*allow_replace=*/false);
    if (!path.is_ok()) {
        raise_(path.error());
    }
    lock.unlock();
    return path.value();
}

catalog::DataVersion CatalogClosureAdapter::commit_working_copy(
    const fs::path& working_path, const std::string& asset_id,
    const std::optional<std::string>& name, domain::DataStage stage,
    const std::optional<std::string>& run_id) {
    std::unique_lock<std::recursive_mutex> lock(mutex_);
    ensure_open_("commit_working_copy");
    catalog::CommitWorkingCopyRequest request;
    if (!asset_id.empty()) {
        request.asset_id = domain::AssetId(asset_id);
    }
    request.name = name.value_or(std::string());
    request.stage = stage;
    if (run_id.has_value()) {
        request.run_id = domain::RunId(*run_id);
    }
    auto context = wc_context_();
    auto committed =
        catalog::commit_working_copy(context, working_path, request);
    if (!committed.is_ok()) {
        raise_(committed.error());
    }
    catalog::CatalogServiceCore& core = core_();
    core.invalidate_maps();
    CatalogChangeEvent event;
    event.kind = CatalogChangeEvent::Kind::VersionsChanged;
    event.identity = identity_;
    event.store_revision = core.index_revision().value_or(-1);
    event.mutation_serial = core.mutation_serial();
    event.asset_ids.push_back(committed.value().asset_id.str());
    event.version_ids.push_back(committed.value().id.str());
    if (committed.value().run_id.has_value()) {
        event.run_ids.push_back(committed.value().run_id->str());
    }
    event.note = "工作副本已提交：" + committed.value().id.str();
    publish_after_(std::move(event));
    lock.unlock();
    flush_queued_();
    return committed.value();
}

void CatalogClosureAdapter::recover_working_copies() {
    std::unique_lock<std::recursive_mutex> lock(mutex_);
    ensure_open_("recover_working_copies");
    auto context = wc_context_();
    const auto result = catalog::recover_working_copies(context);
    core_().invalidate_maps();
    CatalogRecoveryReport report;
    report.ran = true;
    report.at_iso = catalog::utc_now_iso();
    report.working_copies = result;
    if (result.committing_dropped > 0) {
        report.user_notes.push_back(
            "清理了 " + std::to_string(result.committing_dropped) +
            " 个已提交的工作副本记录。");
    }
    if (result.reverted_to_dirty > 0) {
        report.user_notes.push_back(
            std::to_string(result.reverted_to_dirty) +
            " 个中断的工作副本已恢复为 dirty 状态，可重新提交。");
    }
    if (result.missing_dropped > 0) {
        report.user_notes.push_back(
            std::to_string(result.missing_dropped) +
            " 个工作副本因载荷丢失被丢弃（记录见诊断）。");
    }
    report.user_notes.push_back("保留工作副本 " +
                                std::to_string(result.surviving.size()) + " 个。");
    recovery_ = std::move(report);

    CatalogChangeEvent event;
    event.kind = CatalogChangeEvent::Kind::Recovery;
    event.identity = identity_;
    event.store_revision = core_().index_revision().value_or(-1);
    event.mutation_serial = core_().mutation_serial();
    event.note = "工作副本中断恢复完成。";
    publish_after_(std::move(event));
    lock.unlock();
    flush_queued_();
}

// ---------------------------------------------------------------------------
// Governance metadata / runs / tags / integrity
// ---------------------------------------------------------------------------

void CatalogClosureAdapter::update_asset_metadata(
    const std::string& asset_id, const domain::Json& patch) {
    std::unique_lock<std::recursive_mutex> lock(mutex_);
    ensure_open_("update_asset_metadata");
    auto updated = catalog::update_asset_metadata(
        core_().document(), core_save_hook_(core_()),
        domain::AssetId(asset_id), patch);
    if (!updated.is_ok()) {
        raise_(updated.error());
    }
    CatalogChangeEvent event;
    event.kind = CatalogChangeEvent::Kind::AssetsChanged;
    event.identity = identity_;
    event.store_revision = core_().index_revision().value_or(-1);
    event.mutation_serial = core_().mutation_serial();
    event.asset_ids.push_back(asset_id);
    event.note = "资产元数据已更新：" + asset_id;
    publish_after_(std::move(event));
    lock.unlock();
    flush_queued_();
}

catalog::DataRun CatalogClosureAdapter::register_run(
    const std::string& operation,
    const std::vector<std::string>& input_version_ids,
    const domain::Json& parameters) {
    std::unique_lock<std::recursive_mutex> lock(mutex_);
    ensure_open_("register_run");
    catalog::CatalogServiceCore& core = core_();
    DataRun run;
    run.id = domain::RunId(catalog::new_ref_id("run"));
    run.operation = operation;
    for (const auto& input : input_version_ids) {
        run.input_version_ids.push_back(domain::VersionId(input));
    }
    run.parameters = parameters.is_object() ? parameters : domain::Json::object();
    run.status = "completed";
    run.created_at = catalog::utc_now_iso();

    catalog::DataRun* added = core.add_run(run);
    if (added == nullptr) {
        raise_(DataError(ErrorCode::Unknown, "catalog document add failed"));
    }
    DirtySet dirty;
    dirty.mark_run(run.id.str());
    DataError error = core.save(dirty);
    if (error.code != ErrorCode::Ok) {
        Rollback plan;
        plan.runs.push_back(added);
        rollback_(std::move(plan));
        raise_(std::move(error));
    }
    CatalogChangeEvent event;
    event.kind = CatalogChangeEvent::Kind::RunsChanged;
    event.identity = identity_;
    event.store_revision = core.index_revision().value_or(-1);
    event.mutation_serial = core.mutation_serial();
    event.run_ids.push_back(run.id.str());
    event.note = "运行已登记：" + run.id.str();
    publish_after_(std::move(event));
    lock.unlock();
    flush_queued_();
    return run;
}

void CatalogClosureAdapter::update_run_status(const std::string& run_id,
                                              const std::string& status) {
    std::unique_lock<std::recursive_mutex> lock(mutex_);
    ensure_open_("update_run_status");
    catalog::CatalogServiceCore& core = core_();
    if (core.find_run(run_id) == nullptr) {
        raise_(DataError(ErrorCode::NotFound, "Unknown run: " + run_id));
    }
    // Edit through document() (the cache is the write surface; node-pointer
    // edits would never be persisted), then fold cache→store before saving.
    catalog::DataRun* run = nullptr;
    for (auto& candidate : core.document().runs) {
        if (candidate.id.str() == run_id) {
            run = &candidate;
            break;
        }
    }
    if (run == nullptr) {
        raise_(DataError(ErrorCode::NotFound, "Unknown run: " + run_id));
    }
    // service.py terminal guard: terminal statuses cannot be overwritten by
    // a different status (complete/completed are aliases).
    const std::string current = [&] {
        std::string lowered = run->status;
        std::transform(lowered.begin(), lowered.end(), lowered.begin(),
                       [](unsigned char c) {
                           return static_cast<char>(std::tolower(c));
                       });
        return lowered;
    }();
    const std::string target = [&] {
        std::string lowered = status;
        std::transform(lowered.begin(), lowered.end(), lowered.begin(),
                       [](unsigned char c) {
                           return static_cast<char>(std::tolower(c));
                       });
        return lowered;
    }();
    const bool current_terminal =
        current == "complete" || current == "completed" ||
        current == "failed" || current == "cancelled" ||
        current == "canceled";
    if (current_terminal && current != target &&
        !((current == "complete" || current == "completed") &&
          (target == "complete" || target == "completed"))) {
        raise_(DataError(ErrorCode::InvalidArgument,
                         "cannot change terminal run " + run_id + " from '" +
                             run->status + "' to '" + status + "'"));
    }
    const std::string before = run->status;
    run->status = status;
    core.invalidate_maps();  // fold the cache edit into the node store
    DirtySet dirty;
    dirty.mark_run(run_id);
    DataError error = core.save(dirty);
    if (error.code != ErrorCode::Ok) {
        run->status = before;  // in-memory restore (Python parity)
        core.invalidate_maps();
        raise_(std::move(error));
    }
    CatalogChangeEvent event;
    event.kind = CatalogChangeEvent::Kind::RunsChanged;
    event.identity = identity_;
    event.store_revision = core.index_revision().value_or(-1);
    event.mutation_serial = core.mutation_serial();
    event.run_ids.push_back(run_id);
    event.note = "运行状态已更新：" + run_id + " → " + status;
    publish_after_(std::move(event));
    lock.unlock();
    flush_queued_();
}

void CatalogClosureAdapter::add_tag(
    const std::string& name, const std::optional<std::string>& asset_id,
    const std::optional<std::string>& version_id) {
    std::unique_lock<std::recursive_mutex> lock(mutex_);
    ensure_open_("add_tag");
    catalog::TagStore store(
        &core_().document(), [this]() { return core_().save(); });
    auto result = store.add_tag(name, asset_id, version_id);
    if (!result.is_ok()) {
        raise_(result.error());
    }
    CatalogChangeEvent event;
    event.kind = CatalogChangeEvent::Kind::TagsChanged;
    event.identity = identity_;
    event.store_revision = core_().index_revision().value_or(-1);
    event.mutation_serial = core_().mutation_serial();
    if (asset_id.has_value()) event.asset_ids.push_back(*asset_id);
    if (version_id.has_value()) event.version_ids.push_back(*version_id);
    event.note = "标签已添加：" + name;
    publish_after_(std::move(event));
    lock.unlock();
    flush_queued_();
}

void CatalogClosureAdapter::remove_tag(
    const std::string& name, const std::optional<std::string>& asset_id,
    const std::optional<std::string>& version_id) {
    std::unique_lock<std::recursive_mutex> lock(mutex_);
    ensure_open_("remove_tag");
    catalog::TagStore store(
        &core_().document(), [this]() { return core_().save(); });
    DataError error = store.remove_tag(name, asset_id, version_id);
    if (error.code != ErrorCode::Ok) {
        raise_(std::move(error));
    }
    CatalogChangeEvent event;
    event.kind = CatalogChangeEvent::Kind::TagsChanged;
    event.identity = identity_;
    event.store_revision = core_().index_revision().value_or(-1);
    event.mutation_serial = core_().mutation_serial();
    if (asset_id.has_value()) event.asset_ids.push_back(*asset_id);
    if (version_id.has_value()) event.version_ids.push_back(*version_id);
    event.note = "标签已移除：" + name;
    publish_after_(std::move(event));
    lock.unlock();
    flush_queued_();
}

void CatalogClosureAdapter::bulk_add_tag(
    const std::string& name, const std::vector<std::string>& asset_ids) {
    std::unique_lock<std::recursive_mutex> lock(mutex_);
    ensure_open_("bulk_add_tag");
    catalog::TagStore store(
        &core_().document(), [this]() { return core_().save(); });
    auto result = store.bulk_add_tag(name, asset_ids, {});
    if (!result.is_ok()) {
        raise_(result.error());
    }
    CatalogChangeEvent event;
    event.kind = CatalogChangeEvent::Kind::TagsChanged;
    event.identity = identity_;
    event.store_revision = core_().index_revision().value_or(-1);
    event.mutation_serial = core_().mutation_serial();
    event.asset_ids = asset_ids;
    event.note = "批量添加标签：" + name;
    publish_after_(std::move(event));
    lock.unlock();
    flush_queued_();
}

void CatalogClosureAdapter::bulk_remove_tag(
    const std::string& name, const std::vector<std::string>& asset_ids) {
    std::unique_lock<std::recursive_mutex> lock(mutex_);
    ensure_open_("bulk_remove_tag");
    catalog::TagStore store(
        &core_().document(), [this]() { return core_().save(); });
    DataError error = store.bulk_remove_tag(name, asset_ids, {});
    if (error.code != ErrorCode::Ok) {
        raise_(std::move(error));
    }
    CatalogChangeEvent event;
    event.kind = CatalogChangeEvent::Kind::TagsChanged;
    event.identity = identity_;
    event.store_revision = core_().index_revision().value_or(-1);
    event.mutation_serial = core_().mutation_serial();
    event.asset_ids = asset_ids;
    event.note = "批量移除标签：" + name;
    publish_after_(std::move(event));
    lock.unlock();
    flush_queued_();
}

std::string CatalogClosureAdapter::verify_integrity(
    const std::string& version_id) {
    std::lock_guard<std::recursive_mutex> lock(mutex_);
    ensure_open_("verify_integrity");
    auto report = catalog::verify_integrity(
        core_().document(), version_id,
        [this](const catalog::DataVersion& version) {
            return catalog::resolve_payload_path(identity_.project_path,
                                                 version);
        });
    return report.status_for(version_id);
}

// ---------------------------------------------------------------------------
// Open-time maintenance surface
// ---------------------------------------------------------------------------

void CatalogClosureAdapter::warm_document() {
    // The C++ core opens eager (maps + index built at open; findings F-3
    // records the Python lazy machinery is deliberately not ported). The
    // honest body is the self-healing probe: a miss folds any drift once.
    std::lock_guard<std::recursive_mutex> lock(mutex_);
    if (closed_) return;
    (void)core_().find_asset("");
}

void CatalogClosureAdapter::sweep_temp_on_open() {
    std::lock_guard<std::recursive_mutex> lock(mutex_);
    if (closed_) return;
    // Conservative open-time sweep: temp orphans + empty dirs only; a
    // failure must never block project open (Python swallow parity).
    try {
        catalog::GcContext context;
        context.project_path = identity_.project_path;
        context.document = &core_().document();
        (void)catalog::sweep_gc(context, /*dry_run=*/false,
                                /*explicit_sweep=*/false);
    } catch (...) {
    }
}

void CatalogClosureAdapter::ensure_index_ready() {
    std::lock_guard<std::recursive_mutex> lock(mutex_);
    if (closed_) return;
    (void)core_().index();  // lazily rebuilds when invalidated
}

void CatalogClosureAdapter::repair_ghost_runs() {
    std::unique_lock<std::recursive_mutex> lock(mutex_);
    ensure_open_("repair_ghost_runs");
    catalog::CatalogServiceCore& core = core_();
    // #1219: terminal-completed runs of always-producing operations with
    // zero outputs are honest failures. Existing outputs never touched.
    static const char* kAlwaysProducing[] = {
        "materialize",          "working_copy_commit", "manual_edit",
        "map_product_assembly", "interchange.import"};
    bool repaired = false;
    for (auto& run : core.document().runs) {
        const bool always_producing =
            std::find_if(std::begin(kAlwaysProducing),
                         std::end(kAlwaysProducing),
                         [&](const char* op) { return run.operation == op; }) !=
            std::end(kAlwaysProducing);
        if (!always_producing) continue;
        if (run.status != "completed" && run.status != "complete") continue;
        if (!run.output_version_ids.empty()) continue;
        run.status = "failed";
        domain::Json parameters = run.parameters.is_object()
                                      ? run.parameters
                                      : domain::Json::object();
        parameters["ghost_repair"] =
            "v6 repair: completed run had no outputs";
        run.parameters = parameters;
        repaired = true;
    }
    if (repaired) {
        // Fold the document edits into the node store BEFORE saving (the
        // cache is the write surface; save's map lookups read the store).
        core.invalidate_maps();
        // Python parity: full save; a failed flush leaves memory ahead of
        // disk (the core's documented semantics) and the error propagates.
        DataError error = core.save();
        if (error.code != ErrorCode::Ok) {
            raise_(std::move(error));
        }
    }
}

void CatalogClosureAdapter::migrate_run_ports() {
    std::unique_lock<std::recursive_mutex> lock(mutex_);
    ensure_open_("migrate_run_ports");
    catalog::CatalogServiceCore& core = core_();
    auto outcome = catalog::migrate_run_ports_persist(
        &core.document(), core.index(), core_save_hook_(core));
    if (outcome.error.code != ErrorCode::Ok) {
        raise_(outcome.error);
    }
    if (!outcome.touched_run_ids.empty()) {
        core.invalidate_maps();
    }
}

void CatalogClosureAdapter::migrate_legacy_resources(
    const domain::Json& resources_snapshot) {
    std::unique_lock<std::recursive_mutex> lock(mutex_);
    ensure_open_("migrate_legacy_resources");
    catalog::CatalogServiceCore& core = core_();
    std::vector<catalog::LegacyResourceRow> rows;
    if (resources_snapshot.is_array()) {
        for (const auto& row : resources_snapshot) {
            rows.push_back(catalog::LegacyResourceRow::from_json(row));
        }
    }
    auto report = catalog::migrate_resources(
        rows, identity_.project_path, &core.document());
    if (report.asset_ids.empty()) return;
    // Python parity: the migration mutates the document lists directly, so
    // drop the maintained indexes FIRST, then a full save (not a dirty set).
    core.invalidate_maps();
    DataError error = core.save();
    if (error.code != ErrorCode::Ok) {
        raise_(std::move(error));
    }
}

void CatalogClosureAdapter::rebase_artifact_paths() {
    std::unique_lock<std::recursive_mutex> lock(mutex_);
    ensure_open_("rebase_artifact_paths");
    catalog::CatalogServiceCore& core = core_();
    // service.py 4538: rewrite the document paths, then a FULL save (bulk
    // path-rewrite is a reconcile by design). The store rows follow from
    // the document — repository.rebase_artifact_paths() is the save-as
    // store-side helper used when no session is open, not a second pass.
    const std::string current_artifacts =
        project::artifact_dir_for(identity_.project_path).filename().string();

    auto rewrite = [&](const std::string& raw) -> std::optional<std::string> {
        if (raw.empty()) return std::nullopt;
        const std::string posix = fs::path(raw).generic_string();
        const auto slash = posix.find('/');
        if (slash == std::string::npos) return std::nullopt;
        const std::string head = posix.substr(0, slash);
        const std::string rest = posix.substr(slash + 1);
        if (head.size() > std::string(".artifacts").size() &&
            head.compare(head.size() - std::string(".artifacts").size(),
                          std::string(".artifacts").size(),
                          ".artifacts") == 0 &&
            head != current_artifacts) {
            return current_artifacts + "/" + rest;
        }
        return std::nullopt;
    };

    bool changed = false;
    for (auto& model_version : core.document().model_versions) {
        if (auto rewritten =
                rewrite(model_version.artifact_uri.empty()
                            ? std::string()
                            : model_version.artifact_uri)) {
            model_version.artifact_uri = *rewritten;
            changed = true;
        }
    }
    for (auto& version : core.document().versions) {
        if (!version.managed) continue;
        if (auto rewritten = rewrite(version.path)) {
            version.path = *rewritten;
            changed = true;
        }
        if (version.metadata.contains("trash") &&
            version.metadata["trash"].is_object()) {
            domain::Json& trash = version.metadata["trash"];
            if (trash.contains("original_path") &&
                trash["original_path"].is_string()) {
                if (auto rewritten =
                        rewrite(trash["original_path"].get<std::string>())) {
                    trash["original_path"] = *rewritten;
                    changed = true;
                }
            }
        }
    }
    if (changed) {
        core.invalidate_maps();  // fold the path rewrite into the nodes
        DataError error = core.save();
        if (error.code != ErrorCode::Ok) {
            raise_(std::move(error));
        }
    }
}

void CatalogClosureAdapter::close() {
    std::unique_lock<std::recursive_mutex> lock(mutex_);
    if (closed_ || !core_store_.has_value()) {
        closed_ = true;
        lock.unlock();
        flush_queued_();
        return;
    }
    closed_ = true;
    core_store_->close();     // checkpoint (swallow parity) + repository close
    core_store_.reset();  // resource release
    lock.unlock();
    flush_queued_();
}

// ---------------------------------------------------------------------------
// CatalogPortApi
// ---------------------------------------------------------------------------

std::optional<catalog::DataVersionRef>
CatalogClosureAdapter::resolve_legacy_resource(
    const std::string& legacy_id) {
    std::lock_guard<std::recursive_mutex> lock(mutex_);
    if (closed_) return std::nullopt;
    catalog::CatalogServiceCore& core = core_();
    const catalog::DataAsset* match = nullptr;
    for (const auto& asset : core.document().assets) {
        if (asset.trashed) continue;
        if (asset.legacy_resource_id.has_value() &&
            *asset.legacy_resource_id == legacy_id) {
            match = &asset;
            break;
        }
    }
    if (match == nullptr) return std::nullopt;
    const catalog::DataVersion* version =
        match->current_version_id.has_value()
            ? core.find_version(match->current_version_id->str())
            : nullptr;
    if (version == nullptr) return std::nullopt;

    catalog::DataVersionRef ref;
    ref.asset_id = match->id.str();
    ref.version_id = version->id.str();
    ref.name = match->name;
    ref.stage = version->stage;
    ref.path = version->path;
    ref.checksum = version->sha256;
    ref.external = !version->managed;
    if (version->run_id.has_value()) {
        ref.producing_run_id = version->run_id->str();
    }
    ref.created_at = version->created_at;
    ref.kind = match->type;  // view.py mirrors ref.kind ← asset type seam
    ref.format_field = version->format;
    ref.legacy_resource_id = match->legacy_resource_id;
    ref.trashed = version->trashed;
    ref.version_number = version->version_number;
    return ref;
}

// ---------------------------------------------------------------------------
// ReviewCatalogApi — ui_review::ICatalogApi over the live adapter
// ---------------------------------------------------------------------------

std::optional<catalog::DataVersion> ReviewCatalogApi::get_version(
    const std::string& version_id) {
    auto* adapter = owner_;
    std::lock_guard<std::recursive_mutex> lock(adapter->mutex_);
    if (adapter->closed_ || !adapter->core_store_.has_value()) return std::nullopt;
    const catalog::DataVersion* version =
        adapter->core_store_->find_version(version_id);
    if (version == nullptr) return std::nullopt;
    return *version;
}

std::optional<catalog::DataAsset> ReviewCatalogApi::get_asset(
    const std::string& asset_id) {
    auto* adapter = owner_;
    std::lock_guard<std::recursive_mutex> lock(adapter->mutex_);
    if (adapter->closed_ || !adapter->core_store_.has_value()) return std::nullopt;
    const catalog::DataAsset* asset = adapter->core_store_->find_asset(asset_id);
    if (asset == nullptr) return std::nullopt;
    return *asset;
}

std::optional<ui_review::LineageHop> ReviewCatalogApi::get_lineage(
    const std::string& version_id) {
    auto* adapter = owner_;
    std::lock_guard<std::recursive_mutex> lock(adapter->mutex_);
    if (adapter->closed_ || !adapter->core_store_.has_value()) return std::nullopt;
    catalog::CatalogServiceCore& core = *adapter->core_store_;
    const catalog::DataVersion* version = core.find_version(version_id);
    if (version == nullptr) return std::nullopt;
    ui_review::LineageHop hop;
    hop.version = *version;
    if (version->run_id.has_value()) {
        if (const catalog::DataRun* run = core.find_run(version->run_id->str());
            run != nullptr) {
            hop.run = *run;
        }
    }
    for (const auto& parent_id : version->parent_version_ids) {
        if (const catalog::DataVersion* parent =
                core.find_version(parent_id.str());
            parent != nullptr) {
            hop.parents.push_back(*parent);
        }
    }
    for (const auto& candidate : core.document().versions) {
        if (std::find(candidate.parent_version_ids.begin(),
                      candidate.parent_version_ids.end(),
                      version->id) != candidate.parent_version_ids.end()) {
            hop.children.push_back(candidate);
        }
    }
    return hop;
}

ui_review::ResolvedPath ReviewCatalogApi::resolve_path(
    const catalog::DataVersion& version) {
    auto* adapter = owner_;
    std::lock_guard<std::recursive_mutex> lock(adapter->mutex_);
    ui_review::ResolvedPath resolved;
    if (adapter->closed_ || !adapter->core_store_.has_value()) return resolved;
    const fs::path path = catalog::resolve_payload_path(
        adapter->identity_.project_path, version);
    resolved.path = path.string();
    std::error_code ec;
    resolved.is_file = !path.empty() && fs::is_regular_file(path, ec);
    return resolved;
}

std::vector<catalog::DataVersion> ReviewCatalogApi::list_versions(
    const std::string& asset_id) {
    return owner_->list_versions(asset_id);
}

domain::DataError ReviewCatalogApi::promote_version(
    const std::string& version_id) {
    try {
        owner_->promote_version(version_id, domain::DataStage::Output,
                                std::nullopt, std::nullopt);
        return DataError(ErrorCode::Ok, "");
    } catch (const domain::DataException& exception) {
        return exception.error();
    }
}

domain::DataError ReviewCatalogApi::trash_version(
    const std::string& version_id, const std::string& reason) {
    auto* adapter = owner_;
    std::unique_lock<std::recursive_mutex> lock(adapter->mutex_);
    if (adapter->closed_ || !adapter->core_store_.has_value()) {
        return DataError(ErrorCode::InvalidArgument, "数据目录已关闭。");
    }
    catalog::CatalogServiceCore& core = *adapter->core_store_;
    auto index = catalog::DocumentIndex(core.document());
    DataError error = catalog::trash_version(
        &core.document(), index, adapter->identity_.project_path, version_id,
        reason, core_save_hook_(core));
    if (error.code != ErrorCode::Ok) return error;
    core.invalidate_maps();
    CatalogChangeEvent event;
    event.kind = CatalogChangeEvent::Kind::VersionsChanged;
    event.identity = adapter->identity_;
    event.store_revision = core.index_revision().value_or(-1);
    event.mutation_serial = core.mutation_serial();
    event.version_ids.push_back(version_id);
    event.note = "版本已移入回收站：" + version_id;
    adapter->publish_after_(std::move(event));
    lock.unlock();
    adapter->flush_queued_();
    return DataError(ErrorCode::Ok, "");
}

domain::DataError ReviewCatalogApi::restore_version(
    const std::string& version_id) {
    auto* adapter = owner_;
    std::unique_lock<std::recursive_mutex> lock(adapter->mutex_);
    if (adapter->closed_ || !adapter->core_store_.has_value()) {
        return DataError(ErrorCode::InvalidArgument, "数据目录已关闭。");
    }
    catalog::CatalogServiceCore& core = *adapter->core_store_;
    auto index = catalog::DocumentIndex(core.document());
    DataError error = catalog::restore_version(
        &core.document(), index, adapter->identity_.project_path, version_id,
        core_save_hook_(core));
    if (error.code != ErrorCode::Ok) return error;
    core.invalidate_maps();
    CatalogChangeEvent event;
    event.kind = CatalogChangeEvent::Kind::VersionsChanged;
    event.identity = adapter->identity_;
    event.store_revision = core.index_revision().value_or(-1);
    event.mutation_serial = core.mutation_serial();
    event.version_ids.push_back(version_id);
    event.note = "版本已从回收站恢复：" + version_id;
    adapter->publish_after_(std::move(event));
    lock.unlock();
    adapter->flush_queued_();
    return DataError(ErrorCode::Ok, "");
}

catalog::MissingSourceReport ReviewCatalogApi::find_missing_sources(
    const std::function<bool()>& cancel) {
    auto* adapter = owner_;
    std::lock_guard<std::recursive_mutex> lock(adapter->mutex_);
    if (adapter->closed_ || !adapter->core_store_.has_value()) return {};
    return catalog::find_missing_sources(adapter->core_store_->document(),
                                         adapter->core_store_->index(),
                                         adapter->identity_.project_path,
                                         /*include_managed=*/true, cancel);
}

domain::DataError ReviewCatalogApi::relink_external_source(
    const std::string& version_id, const fs::path& new_path) {
    auto* adapter = owner_;
    std::unique_lock<std::recursive_mutex> lock(adapter->mutex_);
    if (adapter->closed_ || !adapter->core_store_.has_value()) {
        return DataError(ErrorCode::InvalidArgument, "数据目录已关闭。");
    }
    catalog::CatalogServiceCore& core = *adapter->core_store_;
    auto index = catalog::DocumentIndex(core.document());
    return catalog::relink_external_source(
        &core.document(), index, version_id, new_path,
        [&core]() { return core.save(); });
}

catalog::AuditReport ReviewCatalogApi::audit(
    bool deep, const std::function<bool()>& cancel) {
    auto* adapter = owner_;
    std::lock_guard<std::recursive_mutex> lock(adapter->mutex_);
    if (adapter->closed_ || !adapter->core_store_.has_value()) return {};
    catalog::AuditContext context;
    context.document = &adapter->core_store_->document();
    context.index = &adapter->core_store_->index();
    context.project_path = adapter->identity_.project_path;
    context.resolve_path =
        [adapter](const catalog::DataVersion& version) {
            return catalog::resolve_payload_path(
                adapter->identity_.project_path, version);
        };
    return catalog::audit_catalog(context, deep, std::nullopt, cancel);
}

}  // namespace pwb::app::closure_catalog
