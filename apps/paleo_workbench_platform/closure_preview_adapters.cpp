// CLOSURE-PREVIEW (task 04) — pure adapter implementations. See
// closure_preview_adapters.hpp.
#include "closure_preview_adapters.hpp"

#include <pwb/catalog/models.hpp>
#include <pwb/data/facade.hpp>
#include <pwb/domain/json.hpp>
#include <pwb/domain/stage.hpp>

#include <algorithm>
#include <filesystem>
#include <fstream>
#include <map>
#include <set>

namespace pwb::closure_preview {
namespace ingest = ::pwb::ingest::preview;

// --- settings mappers --------------------------------------------------------

ingest::PreviewSettings to_ingest_settings(
    const ui_pages_preview::PreviewSettings& s) {
    ingest::PreviewSettings out;
    out.font_size = s.font_size;
    out.show_metadata = s.show_metadata;
    out.text_limit_kib = s.text_limit_kib;
    out.wrap_text = s.wrap_text;
    out.table_max_rows = s.table_max_rows;
    out.table_max_columns = s.table_max_columns;
    out.auto_fit_columns = s.auto_fit_columns;
    out.smooth_images = s.smooth_images;
    out.geotiff_thumbnail_px = s.geotiff_thumbnail_px;
    out.show_geo_metadata = s.show_geo_metadata;
    out.pdf_fit_mode = s.pdf_fit_mode;
    out.pdf_zoom_percent = s.pdf_zoom_percent;
    out.json_limit_mib = s.json_limit_mib;
    out.json_array_collapse_threshold = s.json_array_collapse_threshold;
    out.json_expand_depth = s.json_expand_depth;
    out.media_autoplay = s.media_autoplay;
    out.media_volume = s.media_volume;
    out.geoviz_max_curves = s.geoviz_max_curves;
    out.geoviz_max_depth_samples = s.geoviz_max_depth_samples;
    out.geoviz_max_slice_axis = s.geoviz_max_slice_axis;
    out.geoviz_max_points = s.geoviz_max_points;
    out.geoviz_surface_grid_size = s.geoviz_surface_grid_size;
    out.density = s.density;
    out.theme_mode = s.theme_mode;
    return out;
}

ui_data_core::PreviewSettings to_core_settings(
    const ui_pages_preview::PreviewSettings& s) {
    ui_data_core::PreviewSettings out;
    out.font_size = s.font_size;
    out.show_metadata = s.show_metadata;
    out.text_limit_kib = s.text_limit_kib;
    out.wrap_text = s.wrap_text;
    out.table_max_rows = s.table_max_rows;
    out.table_max_columns = s.table_max_columns;
    out.auto_fit_columns = s.auto_fit_columns;
    out.smooth_images = s.smooth_images;
    out.geotiff_thumbnail_px = s.geotiff_thumbnail_px;
    out.show_geo_metadata = s.show_geo_metadata;
    out.pdf_fit_mode = s.pdf_fit_mode;
    out.pdf_zoom_percent = s.pdf_zoom_percent;
    out.json_limit_mib = s.json_limit_mib;
    out.json_array_collapse_threshold = s.json_array_collapse_threshold;
    out.json_expand_depth = s.json_expand_depth;
    out.media_autoplay = s.media_autoplay;
    out.media_volume = s.media_volume;
    out.geoviz_max_curves = s.geoviz_max_curves;
    out.geoviz_max_depth_samples = s.geoviz_max_depth_samples;
    out.geoviz_max_slice_axis = s.geoviz_max_slice_axis;
    out.geoviz_max_points = s.geoviz_max_points;
    out.geoviz_surface_grid_size = s.geoviz_surface_grid_size;
    out.density = s.density;
    out.theme_mode = s.theme_mode;
    return out;
}

// --- ingest result mapping ---------------------------------------------------

domain::Json revision_to_json(const ingest::Revision& rev) {
    if (!rev.present) return domain::Json(nullptr);
    if (!rev.text_parts.empty()) {
        domain::Json arr = domain::Json::array();
        for (const auto& part : rev.text_parts) {
            arr.push_back(domain::Json(part));
        }
        return arr;
    }
    return domain::Json::array(
        {domain::Json(rev.has_stat ? rev.stat_size : 0),
         domain::Json(rev.has_stat ? rev.stat_mtime_ns : 0)});
}

ui_pages_data::qt::PreviewResultView view_from_ingest(
    const ingest::PreviewResult& r, const ingest::ResourceRef& ref) {
    ui_pages_data::qt::PreviewResultView view;
    view.mode = r.mode;
    view.title = r.title.empty() ? ref.name : r.title;
    view.message = r.message;
    view.warning = r.warning;
    view.type_label = r.type_label;
    view.format = r.format;
    view.status = r.status;
    view.path = r.path.empty() ? ref.path : r.path;
    view.text = r.text;
    view.table_headers = r.table_headers;
    view.table_rows = r.table_rows;
    view.rich_html = r.rich_html;
    view.media_path = r.media_path;
    view.visualization_available = r.visualization_available;
    view.retryable = r.retryable;
    return view;
}

ui_data_core::PreviewResult core_from_ingest(const ingest::PreviewResult& r) {
    ui_data_core::PreviewResult out;
    out.mode = r.mode;
    out.title = r.title;
    out.path = r.path;
    out.revision = revision_to_json(r.revision);
    out.format = r.format;
    out.status = r.status;
    out.type_label = r.type_label;
    out.message = r.message;
    out.warning = r.warning;
    out.text = r.text;
    out.table_headers = r.table_headers;
    out.table_rows = r.table_rows;
    out.summary_rows = r.summary_rows;
    out.sheets = r.sheets;
    out.truncated = r.truncated;
    out.image_bytes = r.image_bytes;
    out.rich_html = r.rich_html;
    out.json_truncated = r.json_truncated;
    out.media_path = r.media_path;
    out.estimated_bytes = r.estimated_bytes;
    out.visualization_available = r.visualization_available;
    out.cacheable = r.cacheable;
    out.retryable = r.retryable;
    out.data_headers = r.data_headers;
    out.data_rows = r.data_rows;
    return out;
}

// --- registry input mapping --------------------------------------------------

std::string lower_ext_of(const std::string& path) {
    auto pos = path.find_last_of('.');
    if (pos == std::string::npos) return {};
    std::string ext = path.substr(pos + 1);
    for (char& c : ext) {
        if (c >= 'A' && c <= 'Z') c = static_cast<char>(c + 32);
    }
    return ext;
}

ingest::ResourceRef ref_from_view(const ui_pages_data::AssetView& v) {
    ingest::ResourceRef ref;
    ref.id = v.id;
    ref.name = v.name;
    ref.path = v.path;
    ref.type = v.type;
    ref.format = v.format.empty() ? lower_ext_of(v.path) : v.format;
    ref.status = v.status.empty() ? "indexed" : v.status;
    ref.checksum = v.checksum;
    return ref;
}

ingest::ResourceRef ref_from_asset(const ui_data_core::AssetObjectData& asset) {
    struct Visitor {
        ingest::ResourceRef operator()(
            const ui_data_core::ResourceItem& r) const {
            ingest::ResourceRef ref;
            ref.id = r.id;
            ref.name = r.name;
            ref.path = r.path;
            ref.type = r.type;
            ref.format = !r.format.empty() ? r.format : lower_ext_of(r.path);
            ref.status = r.status.empty() ? "indexed" : r.status;
            ref.checksum = r.checksum.value_or("");
            return ref;
        }
        ingest::ResourceRef operator()(
            const ui_data_core::SqlCatalogAssetRef& s) const {
            ingest::ResourceRef ref;
            ref.id = s.id;
            ref.name = s.name;
            ref.path = s.path;
            ref.type = s.type;
            ref.format = !s.format.empty() ? s.format : lower_ext_of(s.path);
            ref.status = "indexed";
            ref.checksum = s.sha256;
            return ref;
        }
        ingest::ResourceRef operator()(
            const ui_data_core::ExportArtifact& a) const {
            ingest::ResourceRef ref;
            ref.id = a.id;
            ref.name = a.output_path;
            ref.path = a.output_path;
            ref.type = "artifact";
            ref.format =
                !a.format.empty() ? a.format : lower_ext_of(a.output_path);
            ref.status = "generated";
            return ref;
        }
        ingest::ResourceRef operator()(
            const ui_data_core::GenericAsset& g) const {
            ingest::ResourceRef ref;
            const auto get = [&g](const char* key) -> std::string {
                const auto it = g.attrs.find(key);
                if (it == g.attrs.end() || !it->is_string()) return {};
                return it->get<std::string>();
            };
            ref.id = get("id");
            ref.name = get("name");
            ref.path = get("path");
            ref.type = get("type");
            ref.format = get("format");
            if (ref.format.empty()) ref.format = lower_ext_of(ref.path);
            ref.status = "indexed";
            return ref;
        }
        ingest::ResourceRef operator()(
            const std::shared_ptr<ui_data_core::AssetView>& v) const {
            if (v == nullptr) return ingest::ResourceRef{};
            ingest::ResourceRef ref;
            ref.id = v->id;
            ref.name = v->name;
            ref.path = v->path;
            ref.type = v->type;
            ref.format =
                !v->format.empty() ? v->format : lower_ext_of(v->path);
            ref.status =
                v->status.empty() ? "indexed" : v->status;
            ref.checksum = v->checksum.value_or("");
            return ref;
        }
        ingest::ResourceRef operator()(
            const std::shared_ptr<const catalog::DataAsset>& a) const {
            // Catalog rows carry no payload path here — the registry
            // surfaces the honest 文件不存在 message for them.
            ingest::ResourceRef ref;
            if (a != nullptr) {
                ref.id = a->id.str();
                ref.name = a->name;
                ref.type = a->type;
            }
            return ref;
        }
    };
    return std::visit(Visitor{}, asset);
}

// --- json payload ------------------------------------------------------------

std::shared_ptr<const void> load_json_payload(const std::string& path,
                                              int limit_mib, bool& truncated,
                                              bool& ok) {
    truncated = false;
    ok = false;
    std::error_code ec;
    if (path.empty() || !std::filesystem::exists(path, ec)) return nullptr;
    const auto size = std::filesystem::file_size(path, ec);
    if (ec) return nullptr;
    const long long limit =
        static_cast<long long>(limit_mib <= 0 ? 5 : limit_mib) * 1024 * 1024;
    truncated = static_cast<long long>(size) > limit;
    std::ifstream in(path, std::ios::binary);
    if (!in) return nullptr;
    // Bounded read: at most `limit` bytes hit memory (never a whole-file
    // slurp of a 10 GiB payload on the worker thread).
    std::string bytes;
    const std::size_t want = static_cast<std::size_t>(
        std::min<long long>(size, limit));
    bytes.resize(want);
    in.read(bytes.data(), static_cast<std::streamsize>(want));
    bytes.resize(static_cast<std::size_t>(in.gcount()));
    auto parsed = domain::Json::parse(bytes, nullptr);
    if (parsed == nullptr) return nullptr;
    ok = true;
    return std::make_shared<domain::Json>(std::move(parsed));
}

// --- catalog asset source ----------------------------------------------------

namespace {

// 稿式「关联对象」列的解析：工程 JSON 的 entity_asset_links
// (asset_id → entity_id) + 实体名表（wells/seismic_surveys/
// geological_entities 的 id → name）。读不到 → 空表，列显 "—"。
// 治理闭环扩展：携带首个/主链接的 role（表格「角色」过滤维度）。
struct EntityLinkTables {
    std::map<std::string, std::string> entity_names;   // entity_id → name
    std::map<std::string, std::string> asset_entities; // asset_id → entity_id
    std::map<std::string, std::string> asset_roles;    // asset_id → link role
    std::set<std::string> asset_primary;               // 主链接的 asset_id
};

EntityLinkTables entity_link_tables(
    const std::filesystem::path& project_file) {
    EntityLinkTables tables;
    domain::Json root = domain::Json::object();
    {
        std::ifstream in(project_file);
        if (in) {
            try {
                in >> root;
            } catch (const std::exception&) {
                return tables;
            }
        }
    }
    const auto name_table = [&tables, &root](const char* key) {
        const auto it = root.find(key);
        if (it == root.end() || !it->is_array()) return;
        for (const auto& node : *it) {
            const auto id_it = node.find("id");
            const auto name_it = node.find("name");
            if (id_it != node.end() && id_it->is_string() &&
                name_it != node.end() && name_it->is_string()) {
                tables.entity_names[id_it->get<std::string>()] =
                    name_it->get<std::string>();
            }
        }
    };
    name_table("wells");
    name_table("seismic_surveys");
    name_table("geological_entities");

    const auto links_it = root.find("entity_asset_links");
    if (links_it != root.end() && links_it->is_array()) {
        for (const auto& node : *links_it) {
            const auto asset_it = node.find("asset_id");
            const auto entity_it = node.find("entity_id");
            if (asset_it != node.end() && asset_it->is_string() &&
                entity_it != node.end() && entity_it->is_string()) {
                const std::string asset_id = asset_it->get<std::string>();
                const auto role_it = node.find("role");
                const std::string role =
                    role_it != node.end() && role_it->is_string()
                        ? role_it->get<std::string>()
                        : "other";
                const auto primary_it = node.find("is_primary");
                const bool primary = primary_it != node.end() &&
                                     primary_it->is_boolean() &&
                                     primary_it->get<bool>();
                // 「关联对象/角色」两列必须来自同一条链接（primary 优先，
                // 否则首条占位）——多实体多角色时列间不自相矛盾。
                if (primary || tables.asset_primary.count(asset_id) == 0) {
                    tables.asset_entities[asset_id] =
                        entity_it->get<std::string>();
                    tables.asset_roles[asset_id] = role;
                }
                if (primary) tables.asset_primary.insert(asset_id);
            }
        }
    }
    return tables;
}

std::string metadata_horizon(const domain::Json& metadata) {
    // 资产/版本 metadata 的层位登记键（无标准键——读常见名，
    // 全缺省 → 空）。
    for (const char* key : {"horizon", "horizon_id", "target_horizon"}) {
        const auto it = metadata.find(key);
        if (it != metadata.end() && it->is_string()) {
            return it->get<std::string>();
        }
    }
    return {};
}

}  // namespace

std::vector<ui_pages_data::AssetRow> asset_rows_from_snapshot(
    const pwb::data::ProjectSnapshotV1& snapshot) {
    std::map<std::string, const catalog::DataVersion*> current;
    for (const auto& version : snapshot.catalog_versions) {
        if (version.trashed) continue;
        current[version.id.str()] = &version;  // keyed by VERSION id
    }
    // 治理闭环：asset 级标签（tag_id → display；asset_id → tag 显示名）。
    std::map<std::string, std::string> tag_names;
    for (const auto& tag : snapshot.catalog_tags) {
        tag_names[tag.id] = tag.display_name.has_value() &&
                                    !tag.display_name->empty()
                                ? *tag.display_name
                                : tag.name;
    }
    std::map<std::string, std::vector<std::string>> asset_tag_names;
    for (const auto& [asset_id, tag_id] : snapshot.catalog_asset_tags) {
        const auto it = tag_names.find(tag_id);
        if (it != tag_names.end()) {
            asset_tag_names[asset_id].push_back(it->second);
        }
    }
    const std::filesystem::path project_dir =
        snapshot.project_file.parent_path();
    const EntityLinkTables links =
        entity_link_tables(snapshot.project_file);

    std::vector<ui_pages_data::AssetRow> rows;
    rows.reserve(snapshot.catalog_assets.size());
    for (const auto& asset : snapshot.catalog_assets) {
        if (asset.trashed) continue;
        ui_pages_data::AssetRow row;
        row.kind = ui_pages_data::AssetKind::Resource;
        row.view.id = asset.id.str();
        row.view.name = asset.name;
        row.view.type = asset.type;
        row.view.status = "indexed";
        row.view.managed = true;
        row.view.is_trashed = false;
        // 稿式「关联对象」列：entity_asset_links → 实体名；治理闭环
        // 补「角色」列（主链接 role，无链接留空 → 过滤维度诚实空值）。
        if (const auto link = links.asset_entities.find(row.view.id);
            link != links.asset_entities.end()) {
            const auto name = links.entity_names.find(link->second);
            row.view.linked_label =
                name != links.entity_names.end() ? name->second
                                                 : link->second;
        }
        if (const auto role = links.asset_roles.find(row.view.id);
            role != links.asset_roles.end()) {
            row.view.role = role->second;
        }
        if (const auto tags = asset_tag_names.find(row.view.id);
            tags != asset_tag_names.end()) {
            row.view.tags = tags->second;
        }
        row.view.horizon_label = metadata_horizon(asset.metadata);
        row.view.description = asset.description;
        if (asset.current_version_id.has_value()) {
            const auto it = current.find(asset.current_version_id->str());
            if (it != current.end() && it->second != nullptr) {
                const catalog::DataVersion& version = *it->second;
                row.view.format = version.format;
                // stage::kRaw vocabulary is the BARE value ("raw") — the
                // context-menu stage gates compare it verbatim.
                row.view.stage =
                    std::string(pwb::domain::to_string(version.stage));
                row.view.version_label =
                    "v" + std::to_string(version.version_number);
                row.view.modified_label = version.created_at;
                if (row.view.horizon_label.empty()) {
                    row.view.horizon_label =
                        metadata_horizon(version.metadata);
                }
                if (!version.path.empty()) {
                    std::error_code ec;
                    const std::filesystem::path p(version.path);
                    row.view.path =
                        p.is_absolute()
                            ? version.path
                            : (project_dir / p).lexically_normal().string();
                    row.view.size_label =
                        version.size_bytes.has_value()
                            ? std::to_string(*version.size_bytes)
                            : std::string();
                    row.view.checksum = version.sha256.value_or("");
                }
            }
        }
        rows.push_back(std::move(row));
    }
    return rows;
}

// --- the data page's base preview builder ------------------------------------

ui_pages_data::qt::PreviewResultView build_registry_view(
    const ui_pages_data::AssetRow& row,
    const ui_pages_preview::PreviewSettings& settings) {
    const ingest::ResourceRef ref = ref_from_view(row.view);
    const ingest::PreviewResult result =
        ingest::build_preview(ref, to_ingest_settings(settings));
    ui_pages_data::qt::PreviewResultView view =
        view_from_ingest(result, ref);
    if (result.mode == "json_tree" && result.json_ok) {
        bool truncated = false;
        bool ok = false;
        auto payload = load_json_payload(view.path, settings.json_limit_mib,
                                         truncated, ok);
        if (ok && payload != nullptr) {
            view.payload = payload.get();
            view.payload_owner = payload;
        } else {
            // Race (file moved / payload unparseable on re-read) — an
            // honest message instead of a dead tree.
            view.mode = "message";
            view.message = "JSON 载荷读取失败";
        }
    }
    return view;
}

// --- the VisualizationPage provider ------------------------------------------

ui_data_core::PreviewProvider registry_preview_provider() {
    ui_data_core::PreviewProvider::BuildFn builder =
        [](const ui_data_core::AssetObjectData& asset,
           const ui_data_core::PreviewSettings& settings)
        -> ui_data_core::PreviewResult {
        const ingest::ResourceRef ref = ref_from_asset(asset);
        if (ref.path.empty()) {
            // A bare catalog::DataAsset row carries no payload path — the
            // registry's 文件不存在 would be a FALSE statement; say what
            // is actually true.
            ui_data_core::PreviewResult bare;
            bare.mode = ui_data_core::preview_mode::kMessage;
            bare.title = ref.name;
            bare.message = "该目录行没有可解析的文件路径，无法预览";
            return bare;
        }
        ingest::PreviewSettings ingest_settings;
        ingest_settings.font_size = settings.font_size;
        ingest_settings.show_metadata = settings.show_metadata;
        ingest_settings.text_limit_kib = settings.text_limit_kib;
        ingest_settings.wrap_text = settings.wrap_text;
        ingest_settings.table_max_rows = settings.table_max_rows;
        ingest_settings.table_max_columns = settings.table_max_columns;
        ingest_settings.auto_fit_columns = settings.auto_fit_columns;
        ingest_settings.smooth_images = settings.smooth_images;
        ingest_settings.geotiff_thumbnail_px = settings.geotiff_thumbnail_px;
        ingest_settings.show_geo_metadata = settings.show_geo_metadata;
        ingest_settings.pdf_fit_mode = settings.pdf_fit_mode;
        ingest_settings.pdf_zoom_percent = settings.pdf_zoom_percent;
        ingest_settings.json_limit_mib = settings.json_limit_mib;
        ingest_settings.json_array_collapse_threshold =
            settings.json_array_collapse_threshold;
        ingest_settings.json_expand_depth = settings.json_expand_depth;
        ingest_settings.media_autoplay = settings.media_autoplay;
        ingest_settings.media_volume = settings.media_volume;
        ingest_settings.geoviz_max_curves = settings.geoviz_max_curves;
        ingest_settings.geoviz_max_depth_samples =
            settings.geoviz_max_depth_samples;
        ingest_settings.geoviz_max_slice_axis = settings.geoviz_max_slice_axis;
        ingest_settings.geoviz_max_points = settings.geoviz_max_points;
        ingest_settings.geoviz_surface_grid_size =
            settings.geoviz_surface_grid_size;
        ingest_settings.density = settings.density;
        ingest_settings.theme_mode = settings.theme_mode;
        try {
            const ingest::PreviewResult result =
                ingest::build_preview(ref, ingest_settings);
            return core_from_ingest(result);
        } catch (const std::exception& e) {
            ui_data_core::PreviewResult failure;
            failure.mode = ui_data_core::preview_mode::kMessage;
            failure.message = e.what();
            failure.retryable = true;
            return failure;
        }
    };
    return ui_data_core::PreviewProvider(std::move(builder));
}

}  // namespace pwb::closure_preview
