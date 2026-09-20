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
    std::string bytes;
    bytes.reserve(static_cast<std::size_t>(std::min<long long>(size, limit)));
    bytes.assign(std::istreambuf_iterator<char>(in),
                 std::istreambuf_iterator<char>());
    if (truncated) bytes.resize(static_cast<std::size_t>(limit));
    auto parsed = domain::Json::parse(bytes, nullptr);
    if (parsed == nullptr) return nullptr;
    ok = true;
    return std::make_shared<domain::Json>(std::move(parsed));
}

// --- catalog asset source ----------------------------------------------------

std::vector<ui_pages_data::AssetRow> asset_rows_from_snapshot(
    const pwb::data::ProjectSnapshotV1& snapshot) {
    std::map<std::string, const catalog::DataVersion*> current;
    for (const auto& version : snapshot.catalog_versions) {
        if (version.trashed) continue;
        current[version.id.str()] = &version;  // keyed by VERSION id
    }
    const std::filesystem::path project_dir =
        snapshot.project_file.parent_path();

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
        if (asset.current_version_id.has_value()) {
            const auto it = current.find(asset.current_version_id->str());
            if (it != current.end() && it->second != nullptr) {
                const catalog::DataVersion& version = *it->second;
                row.view.format = version.format;
                row.view.stage = "stage::" +
                                 std::string(pwb::domain::to_string(
                                     version.stage));
                row.view.version_label =
                    "v" + std::to_string(version.version_number);
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
