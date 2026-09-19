#pragma once

// 01-line closure — the CONCRETE catalog service adapter (the composition
// layer ui_controllers/catalog_api.hpp reserves for "the catalog-service
// slice"): one real object over the CONV-31b deep core (CatalogServiceCore
// + CatalogRepository + working_copy/trash/tags/sources/gc/v11 modules).
//
// It implements, over one live core:
//   * ui_controllers::CatalogServiceApi — the DataCatalogService surface the
//     root controllers consume (raising methods throw domain::DataException);
//   * ui_controllers::CatalogPortApi   — the legacy-bridge port;
//   * ui_data_core::CatalogReadService — inherited through CatalogServiceApi,
//     the read side the 04 data page enrichers run on unmodified;
//   * ui_review::ICatalogApi           — via the nested ReviewCatalogApi
//     (no-throw channel: optional/DataError; separate class because
//     get_version has intentionally different contracts on the two seams).
//
// Line-01 additions (owned semantics):
//   * CatalogProjectIdentity — every event/report carries path + project id
//     + name, so 02/03/04/09 consumers never lose the project identity;
//   * CatalogChangeFeed      — real asset add/remove/change subscription
//     (post-commit events only; a failed transaction publishes nothing);
//   * CatalogRecoveryReport  — the user-facing interrupt-recovery result
//     (working-copy states after recover_working_copies()).
//
// Failure semantics (统一失败回滚): every composition follows the Python
// service.py discipline — build payload outside the lock, mutate the
// document, one canonical save; on save failure the just-added entities are
// removed (core map-cohering removes), the current-version pointer is
// restored, and the placed payload is unlinked UNLESS it is a shared CAS
// blob (is_cas_path guard). Revision conflicts (#411/#1220 CAS) surface as
// ConflictBaseVersion / stale_write — NEVER auto-overwritten; the caller
// reopens the project.
//
// Threading: single-writer like Python's RLock — one adapter-level
// recursive_mutex spans each composition sequence (lock order: adapter →
// core/repository, never the reverse; repository.hpp contract). Listeners
// run AFTER the adapter lock is released.

#include <filesystem>
#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <set>
#include <string>
#include <unordered_map>
#include <vector>

#include <pwb/catalog/apply_changes.hpp>
#include <pwb/catalog/asset_metadata.hpp>
#include <pwb/catalog/audit.hpp>
#include <pwb/catalog/document_index.hpp>
#include <pwb/catalog/gc.hpp>
#include <pwb/catalog/legacy_migration.hpp>
#include <pwb/catalog/models.hpp>
#include <pwb/catalog/queries.hpp>
#include <pwb/catalog/repository.hpp>
#include <pwb/catalog/service_core.hpp>
#include <pwb/catalog/sources.hpp>
#include <pwb/catalog/trash_service.hpp>
#include <pwb/catalog/v11_bundle.hpp>
#include <pwb/catalog/version_promote.hpp>
#include <pwb/catalog/working_copy.hpp>
#include <pwb/domain/errors.hpp>
#include <pwb/domain/json.hpp>
#include <pwb/ui_controllers/catalog_api.hpp>
#include <pwb/ui_review/catalog_api.hpp>

namespace pwb::app::closure_catalog {

namespace fs = std::filesystem;

// 工程身份（用户可见语义：保留原工程身份 — open 到 close 不变，重开由宿主重新注入）。
struct CatalogProjectIdentity {
    fs::path project_path;      // the .paleo.json project FILE
    std::string project_id;     // ProjectDocument meta id（宿主注入；空 = 未提供）
    std::string project_name;   // 展示名（空 = 未提供）
};

struct CatalogChangeEvent {
    enum class Kind {
        AssetsChanged,   // 增删改资产（含回收站迁移）
        VersionsChanged, // 新版本/提升/物化/工作副本提交
        RunsChanged,
        TagsChanged,
        Recovery,        // 打开期中断恢复结果
    };
    Kind kind = Kind::AssetsChanged;
    CatalogProjectIdentity identity;
    long long store_revision = -1;      // -1 = unknown (never published as 0 lie)
    std::uint64_t mutation_serial = 0;
    std::vector<std::string> asset_ids;
    std::vector<std::string> version_ids;
    std::vector<std::string> run_ids;
    std::string note;  // 用户可读（中文）
};

// Post-commit change subscription. A failed transaction publishes nothing;
// listeners run on the publishing thread AFTER the adapter lock is released
// (a listener may call back into the adapter reads).
class CatalogChangeFeed {
public:
    class Subscription {
    public:
        Subscription() = default;
        Subscription(CatalogChangeFeed* feed, std::uint64_t id)
            : feed_(feed), id_(id) {}
        ~Subscription();
        Subscription(Subscription&& other) noexcept;
        Subscription& operator=(Subscription&& other) noexcept;
        Subscription(const Subscription&) = delete;
        Subscription& operator=(const Subscription&) = delete;

        bool active() const noexcept { return feed_ != nullptr; }
        void cancel();  // idempotent

    private:
        CatalogChangeFeed* feed_ = nullptr;
        std::uint64_t id_ = 0;
    };

    Subscription subscribe(
        std::function<void(const CatalogChangeEvent&)> listener);
    std::size_t listener_count() const;
    void publish(const CatalogChangeEvent& event);  // swallow listener throws

private:
    friend class Subscription;
    void unsubscribe(std::uint64_t id);

    mutable std::mutex mutex_;
    std::uint64_t next_id_ = 1;
    std::map<std::uint64_t, std::function<void(const CatalogChangeEvent&)>>
        listeners_;
};

// 用户可见的中断恢复报告（open 后宿主驱动一次 recover_working_copies()）。
struct CatalogRecoveryReport {
    bool ran = false;
    std::string at_iso;
    catalog::WorkingCopyRecovery working_copies;
    // 用户可读摘要（中文，逐条对应一个被恢复/丢弃/保留的工作副本）。
    std::vector<std::string> user_notes;
};

class CatalogClosureAdapter;

// ui_review::ICatalogApi binding over the live adapter (09 审核消费).
class ReviewCatalogApi final : public ui_review::ICatalogApi {
public:
    explicit ReviewCatalogApi(CatalogClosureAdapter* owner) : owner_(owner) {}

    std::optional<catalog::DataVersion> get_version(
        const std::string& version_id) override;
    std::optional<catalog::DataAsset> get_asset(
        const std::string& asset_id) override;
    std::optional<ui_review::LineageHop> get_lineage(
        const std::string& version_id) override;
    ui_review::ResolvedPath resolve_path(
        const catalog::DataVersion& version) override;
    std::vector<catalog::DataVersion> list_versions(
        const std::string& asset_id) override;

    domain::DataError promote_version(const std::string& version_id) override;
    domain::DataError trash_version(const std::string& version_id,
                                    const std::string& reason) override;
    domain::DataError restore_version(const std::string& version_id) override;

    catalog::MissingSourceReport find_missing_sources(
        const std::function<bool()>& cancel) override;
    domain::DataError relink_external_source(
        const std::string& version_id,
        const fs::path& new_path) override;

    catalog::AuditReport audit(bool deep,
                               const std::function<bool()>& cancel) override;

private:
    CatalogClosureAdapter* owner_;  // non-owning; adapter outlives the view
};

// The concrete adapter. Open via open(); close() is idempotent.
class CatalogClosureAdapter final
    : public ui_controllers::CatalogServiceApi,
      public ui_controllers::CatalogPortApi {
public:
    // open_catalog() health matrix over the project file (corrupt → isolate
    // + manifest rebuild; unreadable → honest IoError refusal).
    static domain::Result<std::unique_ptr<CatalogClosureAdapter>> open(
        const fs::path& project_path, CatalogProjectIdentity identity,
        catalog::CatalogOpenOptions options = {});

    ~CatalogClosureAdapter() override;  // close() + swallow
    CatalogClosureAdapter(const CatalogClosureAdapter&) = delete;
    CatalogClosureAdapter& operator=(const CatalogClosureAdapter&) = delete;

    // ---- identity / state ------------------------------------------------
    const CatalogProjectIdentity& identity() const { return identity_; }
    bool is_closed() const;
    int document_revision() const;
    std::optional<long long> store_revision() const;
    std::optional<long long> flushed_revision() const;

    // ---- line-01 extensions ------------------------------------------------
    // 资产查询/筛选（queries.search_assets_scan parity — document-order ids）。
    std::vector<std::string> search_assets(
        const catalog::AssetSearchQuery& query);
    // RAW 导入注册（service.import_raw composition — the bulk-import funnel).
    domain::Result<catalog::DataVersion> import_raw(
        const fs::path& source_path, std::optional<std::string> name,
        std::optional<std::string> type, std::optional<std::string> format,
        domain::Json metadata,
        std::optional<std::string> legacy_resource_id = std::nullopt);
    // 外部链接注册（service.link_external composition — unmanaged RAW link,
    // no copy/no hash; materialize_external() later promotes it).
    domain::Result<catalog::DataVersion> link_external(
        const fs::path& path, std::optional<std::string> name,
        std::optional<std::string> type, std::optional<std::string> format,
        domain::Json metadata,
        std::optional<std::string> legacy_resource_id = std::nullopt);
    CatalogChangeFeed& change_feed() { return feed_; }
    const CatalogRecoveryReport& last_recovery_report() const;
    ReviewCatalogApi& review_api() { return review_; }
    // 面向用户的冲突/恢复语义说明（reuse the recovery notes channel):
    std::string conflict_guidance() const;

    // ---- CatalogReadService (via CatalogServiceApi) ------------------------
    const catalog::CatalogDocument& document() const override;
    const catalog::DataAsset* get_asset(
        const std::string& asset_id) override;
    std::vector<catalog::DataVersion> list_versions(
        const std::string& asset_id) override;
    std::vector<catalog::DataAsset> list_assets(
        bool include_trashed) override;
    fs::path resolve_path(const catalog::DataVersion& version) override;
    std::optional<LineageResult> get_lineage(
        const std::string& version_id) override;
    std::unordered_map<std::string, domain::Json> lineage_summaries() override;
    int mutation_serial() const override;

    // ---- CatalogServiceApi (raising channel) --------------------------------
    const fs::path& project_path() const override { return identity_.project_path; }
    catalog::DataVersion get_version(const std::string& version_id) override;
    bool asset_exists(const std::string& asset_id) override;
    std::vector<catalog::DataAsset> get_trashed_assets() override;

    catalog::DataAsset trash_asset(const std::string& asset_id,
                                   const std::string& reason) override;
    catalog::DataAsset restore_asset(const std::string& asset_id) override;
    catalog::DataVersion create_derived(
        const fs::path& source_path,
        const std::vector<std::string>& parent_version_ids,
        const std::string& name, const std::string& operation,
        const std::string& generator) override;
    catalog::DataVersion materialize_external(
        const std::string& version_id,
        const std::optional<std::string>& run_id) override;
    fs::path create_working_copy(const std::string& version_id) override;
    catalog::DataVersion commit_working_copy(
        const fs::path& working_path, const std::string& asset_id,
        const std::optional<std::string>& name, domain::DataStage stage,
        const std::optional<std::string>& run_id) override;
    catalog::DataVersion promote_version(
        const std::string& version_id, domain::DataStage to_stage,
        const std::optional<std::string>& reviewed_by,
        const std::optional<std::string>& note) override;
    void update_asset_metadata(const std::string& asset_id,
                               const domain::Json& patch) override;

    catalog::DataRun register_run(
        const std::string& operation,
        const std::vector<std::string>& input_version_ids,
        const domain::Json& parameters) override;
    void update_run_status(const std::string& run_id,
                           const std::string& status) override;

    void add_tag(const std::string& name,
                 const std::optional<std::string>& asset_id,
                 const std::optional<std::string>& version_id) override;
    void remove_tag(const std::string& name,
                    const std::optional<std::string>& asset_id,
                    const std::optional<std::string>& version_id) override;
    void bulk_add_tag(const std::string& name,
                      const std::vector<std::string>& asset_ids) override;
    void bulk_remove_tag(const std::string& name,
                         const std::vector<std::string>& asset_ids) override;

    std::string verify_integrity(const std::string& version_id) override;

    void warm_document() override;
    void recover_working_copies() override;
    void migrate_legacy_resources(const domain::Json& resources_snapshot) override;
    void sweep_temp_on_open() override;
    void ensure_index_ready() override;
    void repair_ghost_runs() override;
    void migrate_run_ports() override;
    void rebase_artifact_paths() override;
    void close() override;

    // ---- CatalogPortApi ------------------------------------------------------
    const catalog::CatalogDocument& document() override;
    std::optional<catalog::DataVersionRef> resolve_legacy_resource(
        const std::string& legacy_id) override;

private:
    // The review view is the same object's no-throw face; it shares the
    // adapter's single-writer lock and event queue.
    friend class ReviewCatalogApi;

    CatalogClosureAdapter(CatalogProjectIdentity identity);
    void ensure_open_(const std::string& op) const;  // throws when closed
    catalog::CatalogServiceCore& core_();
    const catalog::CatalogServiceCore& core_() const;
    catalog::DocumentIndex fresh_index_();  // snapshot over the live document
    // One composition's rollback (service.py _rollback parity).
    struct Rollback {
        // EXISTING assets must never be listed here (remove_asset would
        // detach them with all their versions) — only entities this call
        // itself added. Existing-asset damage is undone via the
        // restore_current pointers below (Python _rollback parity).
        std::vector<catalog::DataAsset*> assets;
        std::vector<catalog::DataVersion*> versions;
        std::vector<catalog::DataRun*> runs;
        std::optional<std::string> payload_rel;             // placed payload
        std::optional<std::string> restore_current_asset;   // asset id
        std::optional<std::string> restore_current_version; // prev pointer
        fs::path restore_payload_to;  // non-empty = moved WC restore
        // run whose output_version_ids gained a version (register_version
        // run linkage); restored to the pre-call list on failure.
        std::optional<std::pair<std::string, std::vector<domain::VersionId>>>
            restore_run_outputs;
    };
    void rollback_(Rollback&& plan);

    // Event helpers (events flushed after the adapter lock is released).
    void publish_after_(CatalogChangeEvent event);  // queues
    void flush_queued_();                           // must run unlocked

    catalog::WorkingCopyContext wc_context_();

    CatalogProjectIdentity identity_;
    std::optional<catalog::CatalogServiceCore> core_store_;  // nullopt after close
    std::set<std::string> pending_commit_assets_;      // #1218 purge guard set
    CatalogRecoveryReport recovery_;
    ReviewCatalogApi review_;
    CatalogChangeFeed feed_;

    mutable std::recursive_mutex mutex_;  // adapter → core, never reverse
    std::vector<CatalogChangeEvent> queued_events_;
    bool closed_ = false;
};

}  // namespace pwb::app::closure_catalog
