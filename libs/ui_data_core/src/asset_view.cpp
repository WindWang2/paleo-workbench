// data_view_models.py adapters — see asset_view.hpp for the contract.

#include <chrono>
#include "pwb/ui_data_core/asset_view.hpp"

#include <pwb/domain/text.hpp>
#include "pwb/catalog/entity_view.hpp"  // normalize_tag_name
#include "pwb/ui_data_core/governance.hpp"
#include "pwb/ui_data_core/json_util.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdio>
#include <ctime>
#include <stdexcept>
#if !defined(_WIN32)
#include <sys/stat.h>
#else
#include <sys/stat.h>
#include <sys/types.h>
#endif

namespace pwb::ui_data_core {

// ---------------------------------------------------------------------------
// format_size — paleo_workbench.tokens.format_size
// ---------------------------------------------------------------------------

std::string format_size(const std::optional<long long>& size_bytes) {
    if (!size_bytes.has_value()) {
        return "—";
    }
    const long long n = *size_bytes;
    char buf[64];
    if (n >= 1024 * 1024) {
        const double val = static_cast<double>(n) / (1024.0 * 1024.0);
        if (std::fmod(val, 1.0) != 0.0) {
            std::snprintf(buf, sizeof(buf), "%.1f M", val);
        } else {
            std::snprintf(buf, sizeof(buf), "%lld M", static_cast<long long>(val));
        }
        return buf;
    }
    if (n >= 1024) {
        const double val = static_cast<double>(n) / 1024.0;
        if (std::fmod(val, 1.0) != 0.0) {
            std::snprintf(buf, sizeof(buf), "%.1f K", val);
        } else {
            std::snprintf(buf, sizeof(buf), "%lld K", static_cast<long long>(val));
        }
        return buf;
    }
    std::snprintf(buf, sizeof(buf), "%lld B", n);
    return buf;
}

// ---------------------------------------------------------------------------
// Stage presentation
// ---------------------------------------------------------------------------

std::string stage_label(DataStage stage) {
    switch (stage) {
        case DataStage::Raw: return "原始输入";
        case DataStage::Derived: return "派生数据";
        case DataStage::Intermediate: return "中间结果";
        case DataStage::Output: return "输出成果";
    }
    return std::string(domain::to_string(stage));
}

std::string stage_icon(DataStage stage) {
    switch (stage) {
        case DataStage::Raw: return "▣";
        case DataStage::Derived: return "◈";
        case DataStage::Intermediate: return "◇";
        case DataStage::Output: return "★";
    }
    return "▤";
}

std::string stage_color(DataStage stage) {
    switch (stage) {
        case DataStage::Raw: return std::string(tokens::kPrimary);
        case DataStage::Derived: return std::string(tokens::kSuccess);
        case DataStage::Intermediate: return std::string(tokens::kAccent);
        case DataStage::Output: return std::string(tokens::kTeal);
    }
    return std::string(tokens::kTextSecondary);
}

// ---------------------------------------------------------------------------
// IntegrityState
// ---------------------------------------------------------------------------

std::string_view integrity_state_value(IntegrityState state) {
    switch (state) {
        case IntegrityState::Verified: return "VERIFIED";
        case IntegrityState::Modified: return "MODIFIED";
        case IntegrityState::Missing: return "MISSING";
        case IntegrityState::Unmanaged: return "UNMANAGED";
        case IntegrityState::Unknown: return "UNKNOWN";
    }
    return "UNKNOWN";
}

std::string integrity_state_label(IntegrityState state) {
    switch (state) {
        case IntegrityState::Verified: return "已校验";
        case IntegrityState::Modified: return "已修改";
        case IntegrityState::Missing: return "缺失";
        case IntegrityState::Unmanaged: return "外部链接";
        case IntegrityState::Unknown: return "未校验";
    }
    return std::string(integrity_state_value(state));
}

std::string integrity_state_icon(IntegrityState state) {
    switch (state) {
        case IntegrityState::Verified: return "✅";
        case IntegrityState::Modified: return "⚠️";
        case IntegrityState::Missing: return "❌";
        case IntegrityState::Unmanaged: return "§";
        case IntegrityState::Unknown: return "❓";
    }
    return "❓";
}

std::string integrity_state_color(IntegrityState state) {
    switch (state) {
        case IntegrityState::Verified: return std::string(tokens::kSuccess);
        case IntegrityState::Modified: return std::string(tokens::kWarning);
        case IntegrityState::Missing: return std::string(tokens::kErrorRed);
        case IntegrityState::Unmanaged: return std::string(tokens::kTextSecondary);
        case IntegrityState::Unknown: return std::string(tokens::kTextSecondary);
    }
    return std::string(tokens::kTextSecondary);
}

std::optional<IntegrityState> integrity_state_from_value(std::string_view value) {
    if (value == "VERIFIED") return IntegrityState::Verified;
    if (value == "MODIFIED") return IntegrityState::Modified;
    if (value == "MISSING") return IntegrityState::Missing;
    if (value == "UNMANAGED") return IntegrityState::Unmanaged;
    if (value == "UNKNOWN") return IntegrityState::Unknown;
    return std::nullopt;
}

// ---------------------------------------------------------------------------
// DTO helpers
// ---------------------------------------------------------------------------

namespace {

std::string checksum_display_of(const std::optional<std::string>& checksum) {
    if (!checksum.has_value() || checksum->empty()) {
        return "—";
    }
    if (checksum->size() > 12) {
        return checksum->substr(0, 8) + "..." + checksum->substr(checksum->size() - 4);
    }
    return *checksum;
}

}  // namespace

std::string VersionView::checksum_display() const {
    return checksum_display_of(checksum);
}

std::string AssetView::checksum_display() const {
    return checksum_display_of(checksum);
}

std::string AssetView::governance_get(std::string_view key) const {
    for (const auto& [k, v] : governance) {
        if (k == key) {
            return v;
        }
    }
    return "";
}

void AssetView::governance_set(std::string_view key, const std::string& value) {
    for (auto& [k, v] : governance) {
        if (k == key) {
            v = value;
            return;
        }
    }
    governance.emplace_back(std::string(key), value);
}

void AssetView::finalize_normalized_tags() {
    if (normalized_tags.empty() && !tags.empty()) {
        for (const auto& tag : tags) {
            // {normalize(t) for t in tags if t and str(t).strip()} — a
            // whitespace-only tag is truthy but strips to empty → skipped.
            const auto first = tag.find_first_not_of(" \t\n\r\f\v");
            if (first == std::string::npos) {
                continue;
            }
            normalized_tags.insert(catalog::normalize_tag_name(tag));
        }
    }
}

// ---------------------------------------------------------------------------
// SqlCatalogAssetRef + _load_metadata
// ---------------------------------------------------------------------------

domain::Json load_row_metadata(const domain::Json& raw) {
    if (raw.is_null() || (raw.is_string() && raw.get<std::string>().empty())) {
        return domain::Json::object();
    }
    if (raw.is_object()) {
        return raw;
    }
    if (raw.is_string()) {
        try {
            const domain::Json parsed = domain::Json::parse(raw.get<std::string>());
            return parsed.is_object() ? parsed : domain::Json::object();
        } catch (...) {
            return domain::Json::object();
        }
    }
    return domain::Json::object();
}

namespace {

// str(row.get(key) or fallback): any falsy value (null/missing/""/0/false/
// empty container) → fallback; truthy non-strings → str(value).
std::string row_str_or(const domain::Json& row, std::string_view key,
                       std::string_view fallback) {
    if (!row.is_object()) {
        return std::string(fallback);
    }
    const auto it = row.find(std::string(key));
    if (it == row.end() || !json_truthy(*it)) {
        return std::string(fallback);
    }
    return json_str(*it);
}

}  // namespace

SqlCatalogAssetRef::SqlCatalogAssetRef(const domain::Json& row) {
    id = row_str_or(row, "id", "");
    name = row_str_or(row, "name", "");
    type = row_str_or(row, "type", "unknown");
    path = row_str_or(row, "current_path", "");
    metadata = load_row_metadata(row.is_object() && row.contains("metadata")
                                     ? row.at("metadata")
                                     : domain::Json());
    trashed = json_get_bool(row, "trashed");
    current_version_id = row_str_or(row, "current_version_id", "");
    format = row_str_or(row, "current_format", "");
    // NOTE: the ref path does NOT lowercase before parsing (the view builder
    // does) — uppercase stage strings fall through to Raw here.
    const std::string stage_raw = row_str_or(row, "current_stage", "raw");
    stage = domain::data_stage_from_string(stage_raw).value_or(DataStage::Raw);
    // bool(row.get("current_managed", 1)): absent → True, present → bool(v).
    managed = row.is_object() && row.contains("current_managed")
                  ? json_truthy(row.at("current_managed"))
                  : true;
    size_bytes = json_get_opt_int(row, "current_size_bytes");
    sha256 = row_str_or(row, "current_sha256", "");
    created_at = row_str_or(row, "current_created_at", "");
}

// ---------------------------------------------------------------------------
// RESOURCE_TYPE_DISPLAY_LABELS
// ---------------------------------------------------------------------------

const std::unordered_map<std::string, std::string>& resource_type_display_labels() {
    static const std::unordered_map<std::string, std::string> map = {
        {"well_log", "测井"},
        {"seismic", "地震"},
        {"horizon", "层位"},
        {"well_stratification", "井分层"},
        {"time_depth", "时深"},
        {"tabular", "表格"},
        {"spreadsheet", "表格"},
        {"document", "文档"},
        {"image_reference", "影像"},
        {"reference_map", "参考图"},
        {"well_reference", "测井参考"},
        {"fault", "断层"},
        {"raster", "栅格"},
        {"vector", "矢量"},
        {"geojson", "GeoJSON矢量"},
        {"factor_map", "因子图"},
        {"factor_map_grid", "因子图"},
        {"prediction", "预测"},
        {"prediction_result", "预测"},
        {"paleomap", "古地图"},
        {"interpretation", "解释"},
        {"horizon_interpretation", "解释"},
        {"correlation", "地层对比"},
        {"stratigraphic_correlation", "地层对比"},
        {"fault_interpretation", "断层解释"},
        {"qc", "质检"},
        {"qc_report", "质检"},
        {"export", "成果"},
        {"modeling", "三维建模"},
        {"unknown", "其他"},
    };
    return map;
}

std::string resource_type_display_label(std::string_view type,
                                        std::string_view fallback) {
    const auto& map = resource_type_display_labels();
    const auto it = map.find(std::string(type));
    if (it != map.end()) {
        return it->second;
    }
    return fallback.empty() ? std::string(type) : std::string(fallback);
}

// ---------------------------------------------------------------------------
// FsProbeCache
// ---------------------------------------------------------------------------

std::optional<StatNode> FsProbeCache::stat_node(
    const std::filesystem::path& path) const {
    // PWB-V14-DATA-LINEAGE: MSVC has no wchar-capable ::stat; _wstat64
    // carries the same fields (st_mtime is second-granular there, matching
    // the #ifdef st_mtime fallback below).
#if defined(_WIN32)
    struct _stat64 st {};
    if (_wstat64(path.c_str(), &st) != 0) {
        return std::nullopt;
    }
#else
    struct stat st {};
    if (::stat(path.c_str(), &st) != 0) {
        return std::nullopt;
    }
#endif
    StatNode node;
    node.size = static_cast<long long>(st.st_size);
    node.mtime = static_cast<double>(st.st_mtime);
#ifdef st_mtime  // glibc: st_mtime is a macro for st_mtim.tv_sec
    node.mtime_ns = static_cast<long long>(st.st_mtim.tv_sec) * 1000000000LL +
                    static_cast<long long>(st.st_mtim.tv_nsec);
#else
    node.mtime_ns = static_cast<long long>(st.st_mtime) * 1000000000LL;
#endif
    node.mode = static_cast<unsigned int>(st.st_mode);
#if defined(_WIN32)
    node.is_regular = (st.st_mode & _S_IFMT) == _S_IFREG;
    node.is_directory = (st.st_mode & _S_IFMT) == _S_IFDIR;
#else
    node.is_regular = S_ISREG(st.st_mode);
    node.is_directory = S_ISDIR(st.st_mode);
#endif
    return node;
}

const StatNode* FsProbeCache::probe(const std::filesystem::path& path) {
    const std::string key = path.generic_string();
    if (const auto it = nodes_.find(key); it != nodes_.end()) {
        return it->second.has_value() ? &*it->second : nullptr;
    }
    std::optional<StatNode> result;
    if (dir_exists(path.parent_path())) {
        result = stat_node(path);
    }
    auto [it, _] = nodes_.emplace(key, std::move(result));
    return it->second.has_value() ? &*it->second : nullptr;
}

bool FsProbeCache::dir_exists(const std::filesystem::path& directory) {
    const std::string key = directory.generic_string();
    if (const auto it = dirs_.find(key); it != dirs_.end()) {
        return it->second;
    }
    bool exists = false;
    if (directory == directory.parent_path()) {
        exists = true;
    } else if (!dir_exists(directory.parent_path())) {
        exists = false;
    } else {
        const StatNode* node = probe(directory);
        exists = node != nullptr && node->is_directory;
    }
    dirs_[key] = exists;
    return exists;
}

bool path_exists_safe(const std::filesystem::path& path) {
    std::error_code ec;
    const bool exists = std::filesystem::exists(path, ec);
    return !ec && exists;
}

bool path_is_dir_safe(const std::filesystem::path& path) {
    std::error_code ec;
    const bool is_dir = std::filesystem::is_directory(path, ec);
    return !ec && is_dir;
}

std::string format_mtime_minutes(double mtime_seconds) {
    const std::time_t t = static_cast<std::time_t>(mtime_seconds);
    std::tm tm_value {};
#if defined(_WIN32)
    if (localtime_s(&tm_value, &t) != 0) {
        return "—";
    }
#else
    if (::localtime_r(&t, &tm_value) == nullptr) {
        return "—";
    }
#endif
    char buf[32];
    if (std::strftime(buf, sizeof(buf), "%Y-%m-%d %H:%M", &tm_value) == 0) {
        return "—";
    }
    return buf;
}

// ---------------------------------------------------------------------------
// _infer_stage
// ---------------------------------------------------------------------------

DataStage infer_stage(const std::optional<std::string>& role,
                    const std::string& rtype) {
    if (role.has_value()) {
        if (*role == "input") return DataStage::Raw;
        if (*role == "derived") return DataStage::Derived;
        if (*role == "intermediate") return DataStage::Intermediate;
        if (*role == "export" || *role == "output") return DataStage::Output;
    }
    // Default fallbacks based on type — every documented rtype lands on RAW.
    return DataStage::Raw;
}

// ---------------------------------------------------------------------------
// asset_view_from_resource
// ---------------------------------------------------------------------------

namespace {

std::optional<long long> summary_size_bytes(const domain::Json& summary) {
    return json_get_opt_int(summary, "size_bytes");
}

}  // namespace

AssetView asset_view_from_resource(const ResourceItem& resource,
                                   const std::filesystem::path* project_root,
                                   FsProbeCache* fs_probe) {
    const DataStage stage = infer_stage(resource.artifact_role, resource.type);

    std::filesystem::path path_obj(resource.path);
    if (path_obj.is_relative() && project_root != nullptr) {
        path_obj = *project_root / path_obj;
    }

    const StatNode* stat_node = nullptr;
    StatNode transient {};
    bool file_exists = false;
    if (fs_probe != nullptr) {
        const StatNode* node = fs_probe->probe(path_obj);
        if (node != nullptr) {
            file_exists = true;
            if (node->is_regular) {
                stat_node = node;
            }
        }
    } else {
        file_exists = path_exists_safe(path_obj);
        std::error_code ec;
        if (file_exists && std::filesystem::is_regular_file(path_obj, ec) && !ec) {
            // PWB-V14-DATA-LINEAGE: _wstat64 on Windows (no wchar
            // ::stat overload; st_mtime is second-granular there).
#if defined(_WIN32)
            struct _stat64 st {};
            if (_wstat64(path_obj.c_str(), &st) == 0) {
                transient.size = static_cast<long long>(st.st_size);
                transient.mtime = static_cast<double>(st.st_mtime);
                transient.mtime_ns =
                    static_cast<long long>(st.st_mtime) * 1000000000LL;
                transient.mode = st.st_mode;
                transient.is_regular = true;
                stat_node = &transient;
            }
#else
            struct stat st {};
            if (::stat(path_obj.c_str(), &st) == 0) {
                transient.size = static_cast<long long>(st.st_size);
                transient.mtime = static_cast<double>(st.st_mtime);
                transient.mtime_ns =
                    static_cast<long long>(st.st_mtim.tv_sec) * 1000000000LL +
                    static_cast<long long>(st.st_mtim.tv_nsec);
                transient.mode = st.st_mode;
                transient.is_regular = true;
                stat_node = &transient;
            }
#endif
        }
    }

    IntegrityState integrity;
    if (!file_exists || resource.status == "missing") {
        integrity = IntegrityState::Missing;
    } else if (resource.external) {
        integrity = IntegrityState::Unmanaged;
    } else if (resource.checksum.has_value() && !resource.checksum->empty()) {
        integrity = IntegrityState::Verified;
    } else {
        integrity = IntegrityState::Unknown;
    }

    std::optional<long long> size_bytes = summary_size_bytes(resource.parsed_summary);
    if (!size_bytes.has_value() && stat_node != nullptr) {
        size_bytes = stat_node->size;
    }

    std::string modified_at = "—";
    if (stat_node != nullptr) {
        modified_at = format_mtime_minutes(stat_node->mtime);
    }

    VersionView default_version;
    default_version.version_id = "v1";
    default_version.is_current = true;
    default_version.stage = stage;
    default_version.created_at = modified_at;
    default_version.checksum = resource.checksum;
    default_version.checksum_state = integrity;
    default_version.managed = !resource.external;
    default_version.source_note = "Legacy / v1-compatible";

    AssetView view;
    view.id = resource.id;
    view.name = resource.name;
    view.type = resource.type;
    view.type_label = resource_type_display_label(resource.type);
    view.format = resource.format;
    view.stage = stage;
    view.current_version = "v1";
    view.versions = {default_version};
    view.tags = resource.tags;
    view.managed = !resource.external;
    view.integrity_state = integrity;
    view.checksum = resource.checksum;
    view.path = resource.path;
    view.size_bytes = size_bytes;
    view.size_formatted = format_size(size_bytes);
    view.created_at = modified_at;
    view.modified_at = modified_at;
    view.source = resource.source;
    view.crs = resource.crs;
    view.status = resource.status;
    view.parsed_summary =
        resource.parsed_summary.is_object() ? resource.parsed_summary
                                            : domain::Json::object();
    view.trashed = json_get_bool(view.parsed_summary, "catalog_trashed");
    view.trashed_at = json_get_opt_string(view.parsed_summary, "catalog_trashed_at");
    view.finalize_normalized_tags();
    return view;
}

// ---------------------------------------------------------------------------
// asset_view_from_artifact
// ---------------------------------------------------------------------------

AssetView asset_view_from_artifact(const ExportArtifact& artifact,
                                   const std::filesystem::path* project_root,
                                   FsProbeCache* fs_probe) {
    std::filesystem::path out_path(artifact.output_path);
    // Path(output_path).name or output_path — falsy name falls back.
    const std::string base = python_path_name(artifact.output_path);
    const std::string name = base.empty() ? artifact.output_path : base;
    std::filesystem::path path_obj = out_path;
    if (path_obj.is_relative() && project_root != nullptr) {
        path_obj = *project_root / path_obj;
    }

    const StatNode* stat_node = nullptr;
    StatNode transient_artifact {};
    bool file_exists = false;
    if (fs_probe != nullptr) {
        const StatNode* node = fs_probe->probe(path_obj);
        file_exists = node != nullptr;
        if (node != nullptr && node->is_regular) {
            stat_node = node;
        }
    } else {
        file_exists = path_exists_safe(path_obj);
        std::error_code ec;
        if (file_exists && std::filesystem::is_regular_file(path_obj, ec) && !ec) {
#if defined(_WIN32)
            struct _stat64 st {};
            if (_wstat64(path_obj.c_str(), &st) == 0) {
#else
            struct stat st {};
            if (::stat(path_obj.c_str(), &st) == 0) {
#endif
                transient_artifact.size = static_cast<long long>(st.st_size);
                transient_artifact.mtime = static_cast<double>(st.st_mtime);
                transient_artifact.is_regular = true;
                stat_node = &transient_artifact;
            }
        }
    }
    // No recorded checksum → mere existence is never "verified" (#850-4).
    const IntegrityState integrity =
        file_exists ? IntegrityState::Unknown : IntegrityState::Missing;

    const std::optional<long long> size_bytes =
        stat_node != nullptr ? std::optional<long long>(stat_node->size)
                             : std::nullopt;

    VersionView default_version;
    default_version.version_id = "v1";
    default_version.is_current = true;
    default_version.stage = DataStage::Output;
    default_version.created_at =
        artifact.generated_at.empty() ? "—" : artifact.generated_at;
    default_version.checksum_state = integrity;
    default_version.managed = true;
    default_version.source_note = "Exported Artifact";

    LineageView lineage;
    if (!artifact.linked_id.empty()) {
        lineage.parent_ids = {artifact.linked_id};
    }
    if (!artifact.source_task_ids.empty()) {
        lineage.run_id = artifact.source_task_ids.front();
    }

    AssetView view;
    view.id = artifact.id;
    view.name = name;
    view.type = "export";
    view.type_label = "成果";
    view.format = artifact.format;
    view.stage = DataStage::Output;
    view.current_version = "v1";
    view.versions = {default_version};
    view.tags = {"成果"};
    view.managed = true;
    view.integrity_state = integrity;
    view.path = artifact.output_path;
    view.size_bytes = size_bytes;
    view.size_formatted = format_size(size_bytes);
    view.created_at = artifact.generated_at.empty() ? "—" : artifact.generated_at;
    view.modified_at = artifact.generated_at.empty() ? "—" : artifact.generated_at;
    view.source = "export";
    view.lineage = lineage;
    view.status = "generated";
    view.parsed_summary = domain::Json::object();
    view.parsed_summary["included_map_elements"] = artifact.included_map_elements;
    view.finalize_normalized_tags();
    return view;
}

// ---------------------------------------------------------------------------
// asset_view_from_object (+ generic fallback)
// ---------------------------------------------------------------------------

AssetView asset_view_from_generic(const GenericAsset& asset,
                                  const AssetHandle& raw_handle) {
    const domain::Json& attrs = asset.attrs;
    // getattr(asset, key, fallback): the fallback fires only when the key is
    // ABSENT — a present-but-null attribute is returned verbatim (falsy, so
    // "" is the downstream-equivalent string here; str(None) would be "None").
    auto attr_or = [&](std::string_view key, std::string_view fallback) {
        if (attrs.is_object() && attrs.contains(std::string(key))) {
            const auto& v = attrs.at(std::string(key));
            return v.is_null() ? std::string() : json_str(v);
        }
        return std::string(fallback);
    };
    std::string id;
    if (attrs.is_object() && attrs.contains("id")) {
        const auto& v = attrs.at("id");
        id = v.is_null() ? std::string() : json_str(v);
    } else {
        // Python uses f"asset_{id(asset)}" — an unportable object identity;
        // the stable C++ equivalent is the shared handle address.
        char buf[64];
        std::snprintf(buf, sizeof(buf), "asset_%zx",
                      reinterpret_cast<std::uintptr_t>(raw_handle.get()));
        id = buf;
    }
    std::string name;
    if (attrs.is_object() && attrs.contains("name")) {
        const auto& v = attrs.at("name");
        name = v.is_null() ? std::string() : json_str(v);
    } else {
        name = attrs.dump();  // str(asset) fallback for the attr bag
    }
    DataStage stage = DataStage::Raw;
    if (attrs.is_object() && attrs.contains("stage") && attrs["stage"].is_string()) {
        stage = domain::data_stage_from_string(attrs["stage"].get<std::string>())
                    .value_or(DataStage::Raw);
    }

    VersionView default_version;
    default_version.version_id = "v1";
    default_version.is_current = true;
    default_version.stage = stage;

    std::vector<std::string> tags;
    if (attrs.is_object() && attrs.contains("tags") && attrs["tags"].is_array()) {
        for (const auto& tag : attrs["tags"]) {
            tags.push_back(json_str(tag));
        }
    }
    const std::string current_version = attr_or("current_version", "v1");
    IntegrityState integrity = IntegrityState::Unknown;
    if (attrs.is_object() && attrs.contains("integrity_state") &&
        attrs["integrity_state"].is_string()) {
        integrity =
            integrity_state_from_value(attrs["integrity_state"].get<std::string>())
                .value_or(IntegrityState::Unknown);
    }

    const auto size_bytes = json_get_opt_int(attrs, "size_bytes");

    AssetView view;
    view.id = id;
    view.name = name;
    view.type = attr_or("type", "unknown");
    view.type_label = attr_or("type_label", "未知");
    view.format = attr_or("format", "unknown");
    view.stage = stage;
    view.current_version = current_version;
    view.versions = {default_version};
    view.tags = std::move(tags);
    view.managed = json_get_bool(attrs, "managed", true);
    view.integrity_state = integrity;
    if (auto checksum = json_get_opt_string(attrs, "checksum"); checksum.has_value()) {
        view.checksum = *checksum;
    }
    // str(getattr(asset, "path", "")) — str() of the raw value, so a
    // present-null lands as "None" exactly like Python.
    view.path = attrs.is_object() && attrs.contains("path")
                    ? json_str(attrs.at("path"))
                    : "";
    view.size_bytes = size_bytes;
    view.size_formatted = format_size(size_bytes);
    view.created_at = "—";
    view.modified_at = "—";
    view.source = "local";
    view.raw_asset = raw_handle;
    view.finalize_normalized_tags();
    return view;
}

AssetView asset_view_from_object(const AssetHandle& handle,
                                 const std::filesystem::path* project_root,
                                 FsProbeCache* fs_probe) {
    if (handle == nullptr) {
        // A null AssetHandle is a wiring bug, not a payload variant —
        // degrade instead of dereferencing (#1383 guard extended to the
        // handle itself; Python's isinstance chain simply falls through).
        return AssetView{};
    }
    const AssetObjectData& data = *handle;
    if (const auto* view = std::get_if<std::shared_ptr<AssetView>>(&data)) {
        // #1383: make_asset_handle never validates non-null — a null
        // shared_ptr must degrade, not dereference (snapshot_asset parity).
        if (*view == nullptr) {
            return AssetView{};
        }
        return **view;
    }
    if (const auto* resource = std::get_if<ResourceItem>(&data)) {
        AssetView view = asset_view_from_resource(*resource, project_root, fs_probe);
        view.raw_asset = handle;
        return view;
    }
    if (const auto* artifact = std::get_if<ExportArtifact>(&data)) {
        AssetView view = asset_view_from_artifact(*artifact, project_root, fs_probe);
        view.raw_asset = handle;
        return view;
    }
    if (const auto* ref = std::get_if<SqlCatalogAssetRef>(&data)) {
        // Duck-typing fallback: the ref's attrs are what getattr() sees.
        GenericAsset generic;
        generic.attrs = {
            {"id", ref->id},
            {"name", ref->name},
            {"type", ref->type},
            {"format", ref->format},
            {"stage", std::string(domain::to_string(ref->stage))},
            {"managed", ref->managed},
            {"path", ref->path},
            {"size_bytes", ref->size_bytes.has_value() ? domain::Json(*ref->size_bytes)
                                                     : domain::Json(nullptr)},
            {"trashed", ref->trashed},
        };
        AssetView view = asset_view_from_generic(generic, handle);
        return view;
    }
    // #1383: the catalog-row alternative previously fell through to
    // std::get<GenericAsset> and threw std::bad_variant_access. Python's
    // duck-typing fallback reads getattr(asset, ...) — a DataAsset carries
    // id/name/type; absent attributes take the defaults.
    if (const auto* cat =
            std::get_if<std::shared_ptr<const catalog::DataAsset>>(&data)) {
        if (*cat == nullptr) {
            return AssetView{};
        }
        GenericAsset generic;
        generic.attrs = {
            {"id", (*cat)->id.str()},
            {"name", (*cat)->name},
            {"type", (*cat)->type},
        };
        return asset_view_from_generic(generic, handle);
    }
    const auto* generic = std::get_if<GenericAsset>(&data);
    if (generic == nullptr) {
        // Unreachable with the closed variant; degrade instead of throwing.
        return AssetView{};
    }
    return asset_view_from_generic(*generic, handle);
}

AssetHandle make_asset_handle(ResourceItem resource) {
    return std::make_shared<AssetObjectData>(std::move(resource));
}
AssetHandle make_asset_handle(ExportArtifact artifact) {
    return std::make_shared<AssetObjectData>(std::move(artifact));
}
AssetHandle make_asset_handle(SqlCatalogAssetRef ref) {
    return std::make_shared<AssetObjectData>(std::move(ref));
}
AssetHandle make_asset_handle(GenericAsset asset) {
    return std::make_shared<AssetObjectData>(std::move(asset));
}
AssetHandle make_asset_handle(std::shared_ptr<AssetView> view) {
    return std::make_shared<AssetObjectData>(std::move(view));
}
AssetHandle make_asset_handle(const catalog::DataAsset* asset) {
    // Non-owning alias shared_ptr — identity matches the underlying object.
    std::shared_ptr<const catalog::DataAsset> alias(asset, [](const catalog::DataAsset*) {});
    return std::make_shared<AssetObjectData>(std::move(alias));
}
AssetHandle make_asset_handle(std::shared_ptr<const catalog::DataAsset> asset) {
    // Owning form (#1382): keeps the catalog row alive with the handle.
    return std::make_shared<AssetObjectData>(std::move(asset));
}

const void* asset_handle_identity(const AssetHandle& handle) {
    if (!handle) {
        return nullptr;
    }
    if (const auto* inner =
            std::get_if<std::shared_ptr<const catalog::DataAsset>>(&*handle)) {
        return inner->get();
    }
    if (const auto* inner = std::get_if<std::shared_ptr<AssetView>>(&*handle)) {
        return inner->get();
    }
    // By-value payloads: identity is the handle object itself — constructing
    // separate handles to "equal" values is a different Python object.
    return handle.get();
}

// ---------------------------------------------------------------------------
// asset_view_from_sql_row
// ---------------------------------------------------------------------------

namespace {

std::optional<long long> int_like(const domain::Json& value) {
    if (value.is_boolean()) {
        return value.get<bool>() ? 1LL : 0LL;
    }
    if (value.is_number_integer() || value.is_number_unsigned()) {
        return value.get<long long>();
    }
    if (value.is_number_float()) {
        return static_cast<long long>(value.get<double>());
    }
    if (value.is_string()) {
        try {
            return std::stoll(value.get<std::string>());
        } catch (...) {
            return std::nullopt;
        }
    }
    return std::nullopt;
}

std::string lower_ascii(std::string value) {
    return domain::lower_ascii(value);  // shared impl (#1392)
}

}  // namespace

AssetView asset_view_from_sql_row(const domain::Json& row,
                                  const std::filesystem::path* /*project_root*/) {
    // str(row.get("current_stage") or "raw").lower() — falsy → "raw".
    const std::string stage_raw =
        lower_ascii(row_str_or(row, "current_stage", "raw"));
    const DataStage stage =
        domain::data_stage_from_string(stage_raw).value_or(DataStage::Raw);
    auto ref_handle = make_asset_handle(SqlCatalogAssetRef(row));

    std::string current_version = "—";
    const domain::Json version_raw =
        row.is_object() && row.contains("current_version_number")
            ? row.at("current_version_number")
            : domain::Json();
    if (json_truthy(version_raw)) {
        // Python f"v{int(version_number)}" — truthy raw value, int() result.
        current_version = "v" + std::to_string(int_like(version_raw).value_or(0));
    }

    // int(size_bytes) when not None — int() accepts ints/floats/numeric
    // strings; a non-numeric string raises in Python (page fails there, we
    // degrade to None here — documented divergence).
    const domain::Json size_raw =
        row.is_object() && row.contains("current_size_bytes")
            ? row.at("current_size_bytes")
            : domain::Json();
    const std::optional<long long> size_bytes =
        size_raw.is_null() ? std::nullopt : int_like(size_raw);

    // if checksum → truthiness of the RAW value (0/"" are falsy → UNKNOWN).
    const domain::Json checksum_raw =
        row.is_object() && row.contains("current_sha256")
            ? row.at("current_sha256")
            : domain::Json();
    const std::optional<std::string> checksum =
        json_truthy(checksum_raw) ? std::optional<std::string>(json_str(checksum_raw))
                                  : std::nullopt;
    const IntegrityState integrity =
        checksum.has_value() ? IntegrityState::Verified : IntegrityState::Unknown;

    // {key: str(value) for key, value in ref.metadata.items() if key in
    // ("review_status", "owner", "source_system") and value} — iteration
    // order is the metadata dict's, not the key tuple's.
    static const char* kGovKeys[] = {"review_status", "owner", "source_system"};
    std::vector<std::pair<std::string, std::string>> governance;
    const auto& ref = std::get<SqlCatalogAssetRef>(*ref_handle);
    if (ref.metadata.is_object()) {
        for (const auto& [key, value] : ref.metadata.items()) {
            const bool wanted =
                std::find(std::begin(kGovKeys), std::end(kGovKeys), key) !=
                std::end(kGovKeys);
            if (wanted && json_truthy(value)) {
                governance.emplace_back(key, json_str(value));
            }
        }
    }

    AssetView view;
    view.id = ref.id;
    view.name = ref.name;
    view.type = ref.type;
    view.type_label = ref.type;   // raw type, not the display label
    view.format = row_str_or(row, "current_format", "");
    view.stage = stage;
    view.current_version = current_version;
    view.tags = {};
    view.managed = row.is_object() && row.contains("current_managed")
                       ? json_truthy(row.at("current_managed"))
                       : true;
    view.integrity_state = integrity;
    view.checksum = checksum;
    view.path = row_str_or(row, "current_path", "");
    view.size_bytes = size_bytes;
    view.size_formatted = format_size(size_bytes);
    view.created_at = row_str_or(row, "current_created_at", "");
    view.modified_at = row_str_or(row, "updated_at", "");
    view.source = "catalog";
    view.raw_asset = ref_handle;
    view.trashed = ref.trashed;
    view.governance = std::move(governance);
    view.finalize_normalized_tags();
    return view;
}

// ---------------------------------------------------------------------------
// Catalog enrichment
// ---------------------------------------------------------------------------

IntegrityState integrity_from_version(CatalogReadService& service,
                                      const catalog::DataVersion& version,
                                      FsProbeCache* fs_probe) {
    try {
        if (version.trashed) {
            return IntegrityState::Unknown;
        }
        if (!version.managed) {
            return IntegrityState::Unmanaged;
        }
        const std::filesystem::path payload = service.resolve_path(version);
        bool present = false;
        if (fs_probe != nullptr) {
            const StatNode* node = fs_probe->probe(payload);
            present = node != nullptr && node->is_regular;
        } else {
            std::error_code ec;
            present = std::filesystem::is_regular_file(payload, ec) && !ec;
        }
        if (!present) {
            return IntegrityState::Missing;
        }
        if (version.sha256.has_value() && !version.sha256->empty()) {
            return IntegrityState::Verified;
        }
        return IntegrityState::Unknown;
    } catch (...) {
        return IntegrityState::Unknown;
    }
}

std::string lineage_status_text(const domain::Json* summary, DataStage stage) {
    // Python `not summary` → falsy (None / {} / [] / "").
    if (summary == nullptr || !json_truthy(*summary)) {
        return "";
    }
    if (!summary->is_object()) {
        // Python `summary.get` on a non-mapping raises AttributeError, which
        // propagates to the caller's `except → {}` — mirror with a throw.
        throw std::invalid_argument("lineage_status_text: summary must be a mapping");
    }
    // f"...".strip() — Python strips BOTH ends (an empty to_raw renders a
    // leading space that strip removes).
    auto strip = [](std::string s) {
        const auto b = s.find_first_not_of(" \t\n\r\v\f");
        if (b == std::string::npos) {
            return std::string();
        }
        const auto e = s.find_last_not_of(" \t\n\r\v\f");
        return s.substr(b, e - b + 1);
    };
    const std::string broken =
        json_get_bool(*summary, "broken") ? " ⚠断链" : "";
    // `stage == RAW or summary.get("to_raw") == 0` — Python == covers
    // numeric zero of any numeric type plus False.
    if (stage == DataStage::Raw) {
        return strip("源头" + broken);
    }
    const auto it = summary->find("to_raw");
    if (it != summary->end() && !it->is_null()) {
        const bool numeric_zero =
            (it->is_number() && it->get<double>() == 0.0) ||
            (it->is_boolean() && !it->get<bool>());
        if (numeric_zero) {
            return strip("源头" + broken);
        }
        // `to_raw is not None` → f"{to_raw} 级至源头" — str() of the raw
        // value (ints, floats, strings, True all render).
        return strip(json_str(*it) + " 级至源头" + broken);
    }
    if (summary->contains("has_parents") &&
        json_truthy(summary->at("has_parents"))) {
        return strip("未接源头" + broken);
    }
    return strip("无血缘记录" + broken);
}

std::unordered_map<std::string, CatalogRowOverview> compute_catalog_row_overview(
    CatalogReadService& service) {
    std::unordered_map<std::string, CatalogRowOverview> overviews;
    const catalog::CatalogDocument& document = service.document();
    try {
        const auto assets = service.list_assets(/*include_trashed=*/true);
        const auto summaries = service.lineage_summaries();
        std::unordered_map<std::string, const catalog::Tag*> tag_by_id;
        for (const auto& tag : document.tags) {
            tag_by_id[tag.id] = &tag;
        }
        std::unordered_map<std::string, std::vector<std::string>> asset_tag_names;
        for (const auto& [asset_id, tag_id] : document.asset_tags) {
            const auto it = tag_by_id.find(tag_id);
            if (it != tag_by_id.end()) {
                asset_tag_names[asset_id].push_back(
                    it->second->display_name.has_value() &&
                            !it->second->display_name->empty()
                        ? *it->second->display_name
                        : it->second->name);
            }
        }

        FsProbeCache fs_probe;
        std::unordered_map<std::string, std::vector<const catalog::DataVersion*>>
            versions_by_asset;
        for (const auto& version : document.versions) {
            versions_by_asset[version.asset_id.str()].push_back(&version);
        }

        for (const auto& asset : assets) {
            const auto vit = versions_by_asset.find(asset.id.str());
            const std::vector<const catalog::DataVersion*> empty_versions;
            const auto& versions =
                vit != versions_by_asset.end() ? vit->second : empty_versions;
            const catalog::DataVersion* current = nullptr;
            if (asset.current_version_id.has_value()) {
                for (const auto* v : versions) {
                    if (v->id == *asset.current_version_id) {
                        current = v;
                        break;
                    }
                }
            }
            if (current == nullptr && !versions.empty()) {
                current = versions.back();
            }

            CatalogRowOverview overview;
            overview.asset_id = asset.id.str();
            overview.legacy_resource_id = asset.legacy_resource_id;
            overview.stage = current != nullptr ? current->stage : DataStage::Raw;
            overview.version_count = static_cast<int>(versions.size());
            if (current != nullptr) {
                overview.current_version_number = current->version_number;
                overview.current_version_id = current->id.str();
            }
            overview.governance = governance_values(asset.metadata);
            if (current != nullptr) {
                const auto sit = summaries.find(current->id.str());
                overview.lineage_status = lineage_status_text(
                    sit != summaries.end() ? &sit->second : nullptr,
                    current->stage);
            }
            overview.checksum =
                current != nullptr ? current->sha256 : std::nullopt;
            overview.path = current != nullptr ? current->path : "";
            if (current != nullptr) {
                // str(service.resolve_path(current)) — a failure here aborts
                // the WHOLE pass (outer except → {}), matching Python.
                overview.resolved_path =
                    service.resolve_path(*current).generic_string();
            }
            overview.size_bytes =
                current != nullptr ? current->size_bytes : std::nullopt;
            overview.created_at = current != nullptr ? current->created_at : "";
            overview.managed = current != nullptr ? current->managed : true;
            overview.trashed = asset.trashed;
            // #1382: `assets` is the by-value list_assets copy and dies at
            // return — take shared ownership of a copy instead of &asset.
            overview.asset =
                std::make_shared<const catalog::DataAsset>(asset);
            if (current != nullptr) {
                overview.integrity_state =
                    integrity_from_version(service, *current, &fs_probe);
            }
            const auto tit = asset_tag_names.find(asset.id.str());
            if (tit != asset_tag_names.end()) {
                overview.tags = tit->second;
            }
            overviews[asset.id.str()] = std::move(overview);
        }
    } catch (...) {
        return {};
    }
    return overviews;
}

void apply_catalog_overview(AssetView& view, const CatalogRowOverview& overview) {
    view.stage = overview.stage;
    if (overview.current_version_number.has_value()) {
        view.current_version =
            "v" + std::to_string(*overview.current_version_number);
        if (overview.version_count > 1) {
            view.current_version =
                "v" + std::to_string(*overview.current_version_number) + " (" +
                std::to_string(overview.version_count) + ")";
        }
    }
    view.integrity_state = overview.integrity_state;
    view.lineage_status = overview.lineage_status;
    view.governance = overview.governance;
    try {
        view.catalog_metadata = overview.asset != nullptr &&
                                        overview.asset->metadata.is_object()
                                    ? overview.asset->metadata
                                    : domain::Json::object();
    } catch (...) {
        view.catalog_metadata = domain::Json::object();
    }
    view.trashed = overview.trashed;
    view.managed = overview.managed;
    if (!overview.tags.empty()) {
        view.tags = overview.tags;
        view.normalized_tags.clear();
        for (const auto& tag : overview.tags) {
            // {normalize(t) for t in tags if t and str(t).strip()}
            if (tag.find_first_not_of(" \t\n\r\f\v") != std::string::npos) {
                view.normalized_tags.insert(catalog::normalize_tag_name(tag));
            }
        }
    }
    if (overview.checksum.has_value() && !overview.checksum->empty()) {
        view.checksum = overview.checksum;
    }
}

CatalogEnricher::CatalogEnricher(
    std::unordered_map<std::string, CatalogRowOverview> overviews)
    : overviews_(std::move(overviews)) {
    for (const auto& [asset_id, overview] : overviews_) {
        if (overview.current_version_id.has_value()) {
            version_to_asset_[*overview.current_version_id] = asset_id;
        }
        if (overview.legacy_resource_id.has_value() &&
            !overview.legacy_resource_id->empty()) {
            legacy_to_asset_.try_emplace(*overview.legacy_resource_id, asset_id);
        }
    }
}

const CatalogRowOverview* CatalogEnricher::resolve(const AssetView& view) const {
    if (!view.raw_asset) {
        return nullptr;
    }
    const AssetObjectData& raw = *view.raw_asset;
    // getattr(raw, "id", None): typed carriers always have the attribute
    // (possibly ""); the attr bag may not.
    std::string raw_id;
    bool has_id = true;
    bool is_artifact = false;
    std::string catalog_version_id;
    if (const auto* res = std::get_if<ResourceItem>(&raw)) {
        raw_id = res->id;
    } else if (const auto* art = std::get_if<ExportArtifact>(&raw)) {
        raw_id = art->id;
        is_artifact = true;
        if (art->catalog_version_id.has_value()) {
            catalog_version_id = *art->catalog_version_id;
        }
    } else if (const auto* ref = std::get_if<SqlCatalogAssetRef>(&raw)) {
        raw_id = ref->id;
    } else if (const auto* gen = std::get_if<GenericAsset>(&raw)) {
        const auto& attrs = gen->attrs;
        if (attrs.is_object() && attrs.contains("id") &&
            !attrs.at("id").is_null()) {
            raw_id = json_str(attrs.at("id"));
        } else {
            has_id = false;  // getattr → None → `is not None` fails
        }
    } else if (const auto* nested =
                   std::get_if<std::shared_ptr<AssetView>>(&raw)) {
        if (*nested) {
            raw_id = (*nested)->id;
        } else {
            has_id = false;
        }
    } else if (const auto* cat =
                   std::get_if<std::shared_ptr<const catalog::DataAsset>>(
                       &raw)) {
        if (*cat) {
            raw_id = (*cat)->id.str();
        } else {
            has_id = false;
        }
    }
    // `raw_id is not None and raw_id in overviews` — "" is still checked.
    if (has_id) {
        if (const auto it = overviews_.find(raw_id); it != overviews_.end()) {
            return &it->second;
        }
        if (const auto it = legacy_to_asset_.find(raw_id);
            it != legacy_to_asset_.end()) {
            const auto oit = overviews_.find(it->second);
            if (oit != overviews_.end()) {
                return &oit->second;
            }
        }
    }
    if (is_artifact && !catalog_version_id.empty()) {
        if (const auto it = version_to_asset_.find(catalog_version_id);
            it != version_to_asset_.end()) {
            const auto oit = overviews_.find(it->second);
            if (oit != overviews_.end()) {
                return &oit->second;
            }
        }
    }
    return nullptr;
}

AssetView CatalogEnricher::enrich(AssetView view) const {
    try {
        const CatalogRowOverview* overview = resolve(view);
        if (overview != nullptr) {
            apply_catalog_overview(view, *overview);
        }
    } catch (...) {
    }
    return view;
}

AssetView asset_view_from_catalog_overview(
    const CatalogRowOverview& overview,
    const std::filesystem::path* project_root) {
    const catalog::DataAsset* asset = overview.asset.get();
    // getattr(asset, "name", overview.asset_id) — the fallback fires only
    // when the attribute is absent (asset==nullptr), not when "".
    const std::string name =
        asset != nullptr ? asset->name : overview.asset_id;
    // str((metadata or {}).get("format", "") or "") — falsy → "".
    std::string fmt;
    if (asset != nullptr && asset->metadata.is_object() &&
        asset->metadata.contains("format") &&
        json_truthy(asset->metadata.at("format"))) {
        fmt = json_str(asset->metadata.at("format"));
    }
    std::string path = overview.path;
    if (!overview.resolved_path.empty()) {
        path = overview.resolved_path;
    } else if (project_root != nullptr && !path.empty() &&
               !std::filesystem::path(path).is_absolute()) {
        path = (*project_root / path).generic_string();
    }
    const std::string modified =
        !overview.created_at.empty() ? overview.created_at : "—";
    const DataStage stage = overview.stage;
    const std::string version_label =
        overview.current_version_number.has_value() &&
                *overview.current_version_number != 0
            ? "v" + std::to_string(*overview.current_version_number)
            : "—";

    VersionView default_version;
    default_version.version_id =
        overview.current_version_id.has_value() ? *overview.current_version_id
                                                : "—";
    default_version.is_current = true;
    default_version.stage = stage;
    default_version.created_at =
        !overview.created_at.empty() ? overview.created_at : "—";
    default_version.checksum = overview.checksum;
    default_version.checksum_state = overview.integrity_state;
    default_version.managed = overview.managed;
    default_version.source_note = "catalog";

    AssetView view;
    view.id = overview.asset_id;
    view.name = name;
    view.type = asset != nullptr ? asset->type : "unknown";
    // RESOURCE_TYPE_DISPLAY_LABELS.get(getattr(asset,"type","unknown"),
    //   getattr(asset,"type","未知")) — fallback is the asset's raw type, or
    //   "未知" when the asset itself is absent (empty string stays empty).
    const std::string label_fallback =
        asset != nullptr ? asset->type : std::string("未知");
    view.type_label =
        resource_type_display_label(view.type, label_fallback);
    view.format = fmt;
    view.stage = stage;
    view.current_version = version_label;
    view.versions = {default_version};
    view.tags = overview.tags;
    view.managed = overview.managed;
    view.integrity_state = overview.integrity_state;
    view.checksum = overview.checksum;
    view.path = path;
    view.size_bytes = overview.size_bytes;
    view.size_formatted = format_size(overview.size_bytes);
    view.created_at = !overview.created_at.empty() ? overview.created_at : "—";
    view.modified_at = modified;
    // (metadata or {}).get("source", "catalog") — a PRESENT key wins
    // verbatim ("" → "", no "catalog" fallback); absent → "catalog". A
    // present-null lands as falsy "" (Python None → falsy downstream).
    if (asset != nullptr && asset->metadata.is_object() &&
        asset->metadata.contains("source")) {
        const auto& v = asset->metadata.at("source");
        view.source = v.is_null() ? std::string() : json_str(v);
    } else {
        view.source = "catalog";
    }
    view.lineage = LineageView();
    view.governance = overview.governance;
    view.lineage_status = overview.lineage_status;
    view.catalog_metadata =
        asset != nullptr && asset->metadata.is_object() ? asset->metadata
                                                        : domain::Json::object();
    view.status = "catalog";
    view.trashed = overview.trashed;
    // raw_asset = asset — the catalog DataAsset, sharing the overview's
    // ownership so the handle keeps the row alive (#1382).
    if (overview.asset != nullptr) {
        view.raw_asset = make_asset_handle(overview.asset);
    }
    view.finalize_normalized_tags();
    return view;
}

namespace {

// _catalog_tag_maps (#1173): (tag_by_id, version_tag_map) cached per catalog
// state — keyed on document identity + catalog_revision + mutation_serial.
struct CatalogTagMaps {
    std::unordered_map<std::string, const catalog::Tag*> tag_by_id;
    std::unordered_map<std::string, std::vector<std::string>> version_tag_map;
};
struct CatalogTagMapsCacheEntry {
    const catalog::CatalogDocument* document = nullptr;
    int revision = -1;
    int serial = -1;
    CatalogTagMaps maps;
};
CatalogTagMapsCacheEntry g_tag_maps_cache;

const CatalogTagMaps& catalog_tag_maps(CatalogReadService& service) {
    const catalog::CatalogDocument& document = service.document();
    const int revision = document.catalog_revision;
    const int serial = service.mutation_serial();
    if (g_tag_maps_cache.document == &document &&
        g_tag_maps_cache.revision == revision &&
        g_tag_maps_cache.serial == serial) {
        return g_tag_maps_cache.maps;
    }
    CatalogTagMaps maps;
    for (const auto& tag : document.tags) {
        maps.tag_by_id[tag.id] = &tag;
    }
    try {
        for (const auto& [version_id, tag_id] : document.version_tags) {
            const auto it = maps.tag_by_id.find(tag_id);
            if (it != maps.tag_by_id.end()) {
                maps.version_tag_map[version_id].push_back(
                    it->second->display_name.has_value() &&
                            !it->second->display_name->empty()
                        ? *it->second->display_name
                        : it->second->name);
            }
        }
    } catch (...) {
        maps.version_tag_map.clear();
    }
    g_tag_maps_cache.document = &document;
    g_tag_maps_cache.revision = revision;
    g_tag_maps_cache.serial = serial;
    g_tag_maps_cache.maps = std::move(maps);
    return g_tag_maps_cache.maps;
}

}  // namespace

void enrich_view_from_catalog(AssetView& view, CatalogReadService& service,
                              const std::string& asset_id) {
    const catalog::DataAsset* asset = nullptr;
    try {
        asset = service.get_asset(asset_id);
    } catch (...) {
        return;
    }
    if (asset == nullptr) {
        return;
    }

    // --- tombstone state ---
    view.trashed = asset->trashed;
    view.trashed_at = asset->trashed_at;

    // --- governance / catalog metadata ---
    try {
        view.governance = governance_values(asset->metadata);
        view.catalog_metadata = asset->metadata.is_object()
                                    ? asset->metadata
                                    : domain::Json::object();
    } catch (...) {
    }

    // --- versions ---
    std::vector<catalog::DataVersion> versions;
    try {
        versions = service.list_versions(asset_id);
    } catch (...) {
        versions.clear();
    }
    // Version-level tags come from the revision-keyed module cache (#1173).
    const CatalogTagMaps& tag_maps = catalog_tag_maps(service);
    const auto& tag_by_id = tag_maps.tag_by_id;
    const auto& version_tag_map = tag_maps.version_tag_map;

    const catalog::DataVersion* current_version = nullptr;
    if (!versions.empty()) {
        view.versions.clear();
        for (const auto& v : versions) {
            VersionView vv;
            vv.version_id = v.id.str();
            vv.is_current = asset->current_version_id.has_value() &&
                            v.id == *asset->current_version_id;
            vv.stage = v.stage;
            vv.created_at = v.created_at.empty() ? "—" : v.created_at;
            vv.checksum = v.sha256;
            if (!v.parent_version_ids.empty()) {
                vv.parent_version_id = v.parent_version_ids.front().str();
            }
            vv.managed = v.managed;
            vv.source_note = "catalog v" + std::to_string(v.version_number);
            const auto tit = version_tag_map.find(v.id.str());
            if (tit != version_tag_map.end()) {
                vv.tags = tit->second;
            }
            view.versions.push_back(std::move(vv));
        }
        if (asset->current_version_id.has_value() &&
            !asset->current_version_id->str().empty()) {
            view.current_version = asset->current_version_id->str();
        }
        for (const auto& v : versions) {
            if (asset->current_version_id.has_value() &&
                v.id == *asset->current_version_id) {
                current_version = &v;
                break;
            }
        }
        if (current_version != nullptr) {
            view.stage = current_version->stage;
            if (current_version->sha256.has_value() &&
                !current_version->sha256->empty()) {
                view.checksum = current_version->sha256;
            }
        }
    }

    // --- integrity (catalog-recorded posture) ---
    if (current_version != nullptr) {
        FsProbeCache fs_probe;
        view.integrity_state =
            integrity_from_version(service, *current_version, &fs_probe);
    }

    // --- tags ---
    std::vector<std::string> catalog_tags;
    try {
        for (const auto& [aid, tag_id] : service.document().asset_tags) {
            if (aid != asset_id) {
                continue;
            }
            const auto it = tag_by_id.find(tag_id);
            if (it != tag_by_id.end()) {
                catalog_tags.push_back(
                    it->second->display_name.has_value() &&
                            !it->second->display_name->empty()
                        ? *it->second->display_name
                        : it->second->name);
            }
        }
    } catch (...) {
        catalog_tags.clear();
    }
    if (!catalog_tags.empty()) {
        view.tags = catalog_tags;
        view.normalized_tags.clear();
        for (const auto& tag : catalog_tags) {
            // {normalize(t) for t in tags if t and str(t).strip()}
            if (tag.find_first_not_of(" \t\n\r\f\v") != std::string::npos) {
                view.normalized_tags.insert(catalog::normalize_tag_name(tag));
            }
        }
    }

    // --- lineage ---
    if (asset->current_version_id.has_value()) {
        std::optional<CatalogReadService::LineageResult> lineage;
        try {
            lineage = service.get_lineage(asset->current_version_id->str());
        } catch (...) {
            lineage = std::nullopt;
        }
        if (lineage.has_value()) {
            auto version_name = [&](const catalog::DataVersion& v) {
                try {
                    if (const catalog::DataAsset* a =
                            service.get_asset(v.asset_id.str());
                        a != nullptr) {
                        return a->name;
                    }
                } catch (...) {
                }
                return v.id.str();
            };
            LineageView lv;
            for (const auto& v : lineage->parents) {
                lv.parent_ids.push_back(v.id.str());
                lv.parent_names.push_back(version_name(v));
            }
            if (lineage->run.has_value()) {
                lv.run_id = lineage->run->id.str();
                lv.workflow_step = lineage->run->operation;
            }
            for (const auto& v : lineage->children) {
                lv.child_ids.push_back(v.id.str());
                lv.child_names.push_back(version_name(v));
            }
            view.lineage = std::move(lv);
        }
    }
}

}  // namespace pwb::ui_data_core
