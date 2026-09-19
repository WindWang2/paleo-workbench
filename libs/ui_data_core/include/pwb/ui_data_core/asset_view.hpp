// data_view_models.py port — presentation DTOs (AssetView / VersionView /
// TagView / LineageView), the integrity vocabulary, the resource/artifact/
// SQL-row adapters, the filesystem probe cache, and the stage/type label
// tables. Qt-free; uses domain::Json for free-form payloads.
#pragma once

#include "pwb/catalog/models.hpp"
#include "pwb/domain/json.hpp"
#include "pwb/domain/stage.hpp"
#include "pwb/ui_data_core/tokens.hpp"

#include <cstdint>
#include <filesystem>
#include <memory>
#include <optional>
#include <set>
#include <string>
#include <string_view>
#include <variant>
#include <vector>

namespace pwb::ui_data_core {

using domain::DataStage;

// paleo_workbench.tokens.format_size: None → "—", <1KiB → "N B",
// KiB/MiB with one decimal only when non-integral.
std::string format_size(const std::optional<long long>& size_bytes);

// ---------------------------------------------------------------------------
// Stage presentation (STAGE_LABELS / STAGE_ICONS / STAGE_COLORS)
// ---------------------------------------------------------------------------

std::string stage_label(DataStage stage);          // 原始输入/派生数据/中间结果/输出成果
std::string stage_icon(DataStage stage);           // ▣ ◈ ◇ ★ (state_language maturity glyphs)
std::string stage_color(DataStage stage);          // PRIMARY/SUCCESS/ACCENT/TEAL

// ---------------------------------------------------------------------------
// IntegrityState — str Enum parity (value, label, icon_symbol, color_token)
// ---------------------------------------------------------------------------

enum class IntegrityState {
    Verified,
    Modified,
    Missing,
    Unmanaged,
    Unknown,
};

std::string_view integrity_state_value(IntegrityState state);  // "VERIFIED" etc.
std::string integrity_state_label(IntegrityState state);       // 已校验/已修改/缺失/外部链接/未校验
std::string integrity_state_icon(IntegrityState state);        // ✅ ⚠️ ❌ § ❓
std::string integrity_state_color(IntegrityState state);       // token hex
std::optional<IntegrityState> integrity_state_from_value(std::string_view value);

// ---------------------------------------------------------------------------
// Project-side records (project/models.py pydantic surface)
// ---------------------------------------------------------------------------

struct ResourceItem {
    std::string id;
    std::string name;
    std::string path;
    std::string type;
    std::string format;
    std::optional<std::string> crs;
    std::string status = "indexed";
    std::vector<std::string> tags;
    std::string source = "local";
    domain::Json parsed_summary = domain::Json::object();
    std::optional<std::string> checksum;
    bool external = false;
    std::optional<std::string> artifact_role;
};

struct ExportArtifact {
    std::string id;
    std::string linked_id;
    std::string format;
    std::string output_path;
    domain::Json options = domain::Json::object();
    std::vector<std::string> included_map_elements;
    std::string generated_at;
    std::vector<std::string> source_task_ids;
    std::optional<std::string> catalog_version_id;
};

// ---------------------------------------------------------------------------
// View DTOs
// ---------------------------------------------------------------------------

struct VersionView {
    std::string version_id;
    bool is_current = true;
    DataStage stage = DataStage::Raw;
    std::string created_at = "—";
    std::optional<std::string> checksum;
    IntegrityState checksum_state = IntegrityState::Unknown;
    std::optional<std::string> parent_version_id;
    bool managed = true;
    std::string source_note;
    std::vector<std::string> tags;

    std::string checksum_display() const;  // — / first8...last4 / verbatim
};

struct TagView {
    std::string name;
    int count = 0;
    std::string category = "custom";
};

struct LineageView {
    std::vector<std::string> parent_ids;
    std::vector<std::string> parent_names;
    std::optional<std::string> run_id;
    std::optional<std::string> workflow_step;
    std::vector<std::string> child_ids;
    std::vector<std::string> child_names;

    bool has_lineage() const {
        return !parent_ids.empty() || !child_ids.empty() || run_id.has_value();
    }
};

// A paged-SQL row's lightweight raw-asset ref (paged_asset_model.py
// SqlCatalogAssetRef): identity + lifecycle facts the action paths read.
struct SqlCatalogAssetRef {
    std::string id;
    std::string name;
    std::string type = "unknown";
    std::string path;
    domain::Json metadata = domain::Json::object();
    bool trashed = false;
    std::string current_version_id;
    std::string format;
    DataStage stage = DataStage::Raw;
    bool managed = true;
    std::optional<long long> size_bytes;
    std::string sha256;
    std::string created_at;

    explicit SqlCatalogAssetRef(const domain::Json& row);
};

// Duck-typed "generic asset" (asset_view_from_object fallback branch): an
// attribute bag whose keys mirror the getattr() reads of the Python path.
struct GenericAsset {
    domain::Json attrs = domain::Json::object();
};

struct AssetView;

// The raw model object a view was built from (Python ``view.raw_asset``).
// ``shared_ptr<const catalog::DataAsset>`` carries catalog-only rows
// (asset_view_from_catalog_overview: ``raw_asset = asset``).
using AssetObjectData =
    std::variant<ResourceItem, ExportArtifact, SqlCatalogAssetRef, GenericAsset,
                 std::shared_ptr<AssetView>,
                 std::shared_ptr<const catalog::DataAsset>>;

// Identity handle: the same underlying object arriving twice compares equal
// by pointer — the ``_match_positions_by_identity`` reuse key (#1063).
using AssetHandle = std::shared_ptr<AssetObjectData>;

struct AssetView {
    std::string id;
    std::string name;
    std::string type;
    std::string type_label;
    std::string format;
    DataStage stage = DataStage::Raw;
    std::string current_version;
    std::vector<VersionView> versions;
    std::vector<std::string> tags;
    bool managed = true;
    IntegrityState integrity_state = IntegrityState::Unknown;
    std::optional<std::string> checksum;
    std::string path;
    std::optional<long long> size_bytes;
    std::string size_formatted;
    std::string created_at;
    std::string modified_at;
    std::string source;
    LineageView lineage;
    std::optional<std::string> crs;
    std::string status = "indexed";
    domain::Json parsed_summary = domain::Json::object();
    AssetHandle raw_asset;
    std::set<std::string> normalized_tags;
    bool trashed = false;
    std::optional<std::string> trashed_at;
    // Insertion-ordered governance pairs (GOVERNANCE_KEYS order).
    std::vector<std::pair<std::string, std::string>> governance;
    std::string lineage_status;
    domain::Json catalog_metadata = domain::Json::object();

    void finalize_normalized_tags();   // __post_init__ normalization
    bool is_raw() const { return stage == DataStage::Raw; }
    bool is_derived() const { return stage == DataStage::Derived; }
    bool is_output() const { return stage == DataStage::Output; }
    bool is_trashed() const { return trashed; }
    std::string trashed_label() const { return "✕ 已移至回收站"; }
    std::string stage_label_text() const { return stage_label(stage); }
    std::string integrity_label() const { return integrity_state_label(integrity_state); }
    std::string checksum_display() const;
    bool is_missing() const {
        return integrity_state == IntegrityState::Missing || status == "missing";
    }
    // governance.get(key, "")
    std::string governance_get(std::string_view key) const;
    void governance_set(std::string_view key, const std::string& value);
};

// ---------------------------------------------------------------------------
// RESOURCE_TYPE_DISPLAY_LABELS
// ---------------------------------------------------------------------------

const std::unordered_map<std::string, std::string>& resource_type_display_labels();
std::string resource_type_display_label(std::string_view type,
                                        std::string_view fallback = "");

// ---------------------------------------------------------------------------
// FsProbeCache — one stat per distinct path, missing-dir pruning (#917)
// ---------------------------------------------------------------------------

struct StatNode {
    long long size = 0;
    long long mtime_ns = 0;
    double mtime = 0.0;
    unsigned int mode = 0;    // st_mode
    bool is_regular = false;
    bool is_directory = false;
};

class FsProbeCache {
public:
    virtual ~FsProbeCache() = default;
    // os.stat(path) or None, cached per refresh.
    virtual const StatNode* probe(const std::filesystem::path& path);
    bool dir_exists(const std::filesystem::path& directory);

protected:
    // Stat seam for tests (fixture-driven probes) and future backends.
    virtual std::optional<StatNode> stat_node(const std::filesystem::path& path) const;

private:
    std::unordered_map<std::string, std::optional<StatNode>> nodes_;
    std::unordered_map<std::string, bool> dirs_;
};

// ``Path.exists()`` treating unprobeable paths as absent (#882).
bool path_exists_safe(const std::filesystem::path& path);
bool path_is_dir_safe(const std::filesystem::path& path);

// datetime.fromtimestamp(st_mtime).strftime("%Y-%m-%d %H:%M") — LOCAL time.
std::string format_mtime_minutes(double mtime_seconds);

// ---------------------------------------------------------------------------
// Adapters (asset_view_from_resource / _from_artifact / _from_object)
// ---------------------------------------------------------------------------

DataStage infer_stage(const std::optional<std::string>& role,
                      const std::string& rtype);

AssetView asset_view_from_resource(const ResourceItem& resource,
                                   const std::filesystem::path* project_root = nullptr,
                                   FsProbeCache* fs_probe = nullptr);

AssetView asset_view_from_artifact(const ExportArtifact& artifact,
                                   const std::filesystem::path* project_root = nullptr,
                                   FsProbeCache* fs_probe = nullptr);

// Generic-asset branch of asset_view_from_object.
AssetView asset_view_from_generic(const GenericAsset& asset,
                                  const AssetHandle& raw_handle);

// asset_view_from_object dispatch. ``handle`` MUST own the same object the
// caller's asset list holds so identity matching sees stable pointers.
AssetView asset_view_from_object(const AssetHandle& handle,
                                 const std::filesystem::path* project_root = nullptr,
                                 FsProbeCache* fs_probe = nullptr);

AssetHandle make_asset_handle(ResourceItem resource);
AssetHandle make_asset_handle(ExportArtifact artifact);
AssetHandle make_asset_handle(SqlCatalogAssetRef ref);
AssetHandle make_asset_handle(GenericAsset asset);
AssetHandle make_asset_handle(std::shared_ptr<AssetView> view);
// Non-owning handle over a catalog DataAsset (raw_asset for catalog-only rows).
AssetHandle make_asset_handle(const catalog::DataAsset* asset);
// Python ``raw_asset is other_raw`` identity: pointer identity of the wrapped
// object for pointer-carrying variants, else the handle object itself.
const void* asset_handle_identity(const AssetHandle& handle);

// asset_view_from_sql_row (paged_asset_model.py): paged row dict → view.
AssetView asset_view_from_sql_row(const domain::Json& row,
                                  const std::filesystem::path* project_root = nullptr);

// json.loads(row["metadata"]) → object | {}
domain::Json load_row_metadata(const domain::Json& raw);

// ---------------------------------------------------------------------------
// Catalog enrichment (data_view_models.py catalog seam)
// ---------------------------------------------------------------------------

// Read-side seam for the Python ``service`` object (DataCatalogService).
// The application binds a concrete adapter over the real service; tests
// inject fixtures. Methods that "raise" in Python return nullopt/empty here.
class CatalogReadService {
public:
    virtual ~CatalogReadService() = default;
    virtual const catalog::CatalogDocument& document() const = 0;
    virtual const catalog::DataAsset* get_asset(const std::string& asset_id) = 0;
    virtual std::vector<catalog::DataVersion> list_versions(
        const std::string& asset_id) = 0;
    virtual std::vector<catalog::DataAsset> list_assets(bool include_trashed) = 0;
    // Absolute payload path for a version; throws/empty → treated as absent.
    virtual std::filesystem::path resolve_path(
        const catalog::DataVersion& version) = 0;

    struct LineageResult {
        std::vector<catalog::DataVersion> parents;
        std::vector<catalog::DataVersion> children;
        std::optional<catalog::DataRun> run;
    };
    // lineage dict or nullopt on failure.
    virtual std::optional<LineageResult> get_lineage(
        const std::string& version_id) = 0;
    // version_id → summary dict (broken/to_raw/has_parents keys).
    virtual std::unordered_map<std::string, domain::Json> lineage_summaries() = 0;
    virtual int mutation_serial() const { return 0; }
};

// _integrity_from_version: catalog-recorded posture, never a re-hash.
IntegrityState integrity_from_version(CatalogReadService& service,
                                      const catalog::DataVersion& version,
                                      FsProbeCache* fs_probe = nullptr);

struct CatalogRowOverview {
    std::string asset_id;
    std::optional<std::string> legacy_resource_id;
    DataStage stage = DataStage::Raw;
    int version_count = 0;
    std::optional<int> current_version_number;
    std::optional<std::string> current_version_id;
    std::vector<std::string> tags;
    std::vector<std::pair<std::string, std::string>> governance;
    IntegrityState integrity_state = IntegrityState::Unknown;
    std::string lineage_status;
    std::optional<std::string> checksum;
    std::string path;
    std::string resolved_path;
    std::optional<long long> size_bytes;
    std::string created_at;
    bool managed = true;
    bool trashed = false;
    const catalog::DataAsset* asset = nullptr;  // non-owning doc pointer
};

// _lineage_status_text(summary, stage)
std::string lineage_status_text(const domain::Json* summary, DataStage stage);

// catalog_row_overview(service): one locked pass. The Python (document,
// revision) result cache is the adapter's concern; this is the pure
// computation it wraps.
std::unordered_map<std::string, CatalogRowOverview> compute_catalog_row_overview(
    CatalogReadService& service);

// apply_catalog_overview(view, overview) — in place.
void apply_catalog_overview(AssetView& view, const CatalogRowOverview& overview);

// make_catalog_enricher → a reusable resolver/enricher closure.
class CatalogEnricher {
public:
    explicit CatalogEnricher(
        std::unordered_map<std::string, CatalogRowOverview> overviews);

    // resolve(view) → overview pointer or nullptr (the three bridge shapes).
    const CatalogRowOverview* resolve(const AssetView& view) const;
    // enrich(view) → view with overlay applied (returns input on failure).
    AssetView enrich(AssetView view) const;

    const std::unordered_map<std::string, CatalogRowOverview>& overview_map()
        const {
        return overviews_;
    }
    const std::unordered_map<std::string, std::string>& version_to_asset()
        const {
        return version_to_asset_;
    }

private:
    std::unordered_map<std::string, CatalogRowOverview> overviews_;
    std::unordered_map<std::string, std::string> version_to_asset_;
    std::unordered_map<std::string, std::string> legacy_to_asset_;
};

// asset_view_from_catalog_overview: catalog-only row view.
AssetView asset_view_from_catalog_overview(
    const CatalogRowOverview& overview,
    const std::filesystem::path* project_root = nullptr);

// enrich_view_from_catalog: authoritative per-asset enrichment in place.
// Any catalog failure leaves the legacy view untouched.
void enrich_view_from_catalog(AssetView& view, CatalogReadService& service,
                              const std::string& asset_id);

}  // namespace pwb::ui_data_core
