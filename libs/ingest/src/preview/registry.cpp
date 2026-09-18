#include "pwb/ingest/preview/registry.hpp"

#include <filesystem>
#include <fstream>
#include <iterator>

#include "pwb/ingest/preview/document_parsers.hpp"
#include "pwb/ingest/preview/office.hpp"
#include "pwb/ingest/preview/spreadsheetml.hpp"
#include "pwb/ingest/preview/text_parsers.hpp"
#include "pwb/ingest/preview/office.hpp"
#include "pwb/ingest/preview/well_log_xml_preview.hpp"
#include "pwb/ingest/project_path.hpp"
#include "pwb/ingest/py_compat.hpp"

namespace pwb::ingest::preview {

namespace {

std::string basename_of(const std::string& path) {
    auto pos = path.find_last_of('/');
    return pos == std::string::npos ? path : path.substr(pos + 1);
}

// safe_stat-shaped revision (parse_error/text/dat/table/office routes).
Revision stat_revision(const AssetFile& file) {
    Revision rev;
    rev.present = true;
    rev.has_stat = file.exists;
    rev.stat_size = static_cast<long long>(file.size);
    return rev;
}

PreviewResult message_result(const ResourceRef& res, std::string message,
                             std::string status = "",
                             std::string type_label_override = "") {
    PreviewResult r;
    r.mode = "message";
    r.title = res.name;
    r.path = res.path;
    r.revision = res.revision;
    r.format = res.format;
    r.status = status.empty() ? res.status : status;
    r.type_label = type_label_override.empty() ? res.type : type_label_override;
    r.message = message;
    r.warning = message;
    return r;
}

}  // namespace

AssetFile read_asset(const std::string& path) {
    AssetFile file;
    std::error_code ec;
    auto st = safe_file_stat(path);
    if (!st) return file;
    file.exists = true;
    file.size = st->size;
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        file.exists = false;
        return file;
    }
    file.bytes.assign(std::istreambuf_iterator<char>(in),
                      std::istreambuf_iterator<char>());
    return file;
}

Revision resource_revision_token(const ResourceRef& asset, bool file_stat_ok,
                                 long long stat_size, long long stat_mtime_ns) {
    (void)stat_mtime_ns;  // never frozen (D13)
    Revision rev;
    rev.present = true;
    rev.text_parts = {"resource", asset.id, asset.path, asset.type,
                      asset.format, asset.status, asset.checksum};
    if (file_stat_ok) {
        rev.has_stat = true;
        rev.stat_size = stat_size;
    }
    return rev;
}

PreviewResult artifact_preview(const std::string& output_path,
                               const std::string& format,
                               const std::string& linked_id) {
    PreviewResult r;
    r.mode = "message";
    r.title = basename_of(output_path);
    if (r.title.empty()) r.title = output_path;
    r.path = output_path;
    auto st = safe_file_stat(output_path);
    if (st) {
        r.revision.present = true;
        r.revision.has_stat = true;
        r.revision.stat_size = st->size;
        r.revision.stat_mtime_ns = st->mtime_ns;
    }
    r.format = format;
    r.status = "generated";
    r.type_label = "成果";
    r.message = "成果文件 · 关联对象 " + linked_id;
    return r;
}

PreviewResult build_preview(const ResourceRef& asset_in,
                            const PreviewSettings& settings,
                            const std::optional<std::string>& project_root,
                            const std::vector<std::pair<std::string, std::string>>&
                                sibling_dir_entries) {
    ResourceRef asset = asset_in;
    const AssetFile file = [&] {
        // resolve project-relative paths first (traversal-rejecting)
        if (project_root && !asset.path.empty()) {
            std::error_code ec;
            if (!std::filesystem::path(asset.path).is_absolute()) {
                std::string resolved = resolve_asset_path(asset.path, *project_root);
                if (resolved != asset.path) asset.path = resolved;
            }
        }
        return read_asset(asset.path);
    }();
    if (!asset.revision.present) {
        asset.revision = resource_revision_token(
            asset, file.exists, static_cast<long long>(file.size), 0);
    }
    std::string fmt;
    for (char c : asset.format) fmt.push_back(c >= 'A' && c <= 'Z'
                                                 ? static_cast<char>(c + 32)
                                                 : c);
    const std::string& title = asset.name;

    if (!file.exists) {
        PreviewResult missing_r = message_result(asset,
                              "\xE6\x96\x87\xE4\xBB\xB6\xE4\xB8\x8D\xE5\xAD\x98\xE5\x9C\xA8",  // 文件不存在
                              "missing");
        missing_r.warning = "";
        return missing_r;
    }
    // NOTE: the Python registry consults its (empty in production) registered
    // parser table first; the hardcoded chain below is the effective behavior.
    auto bounded_text = [&]() -> std::pair<std::string, bool> {
        size_t limit = static_cast<size_t>(settings.text_limit_kib) * 1024;
        return {file.bytes.substr(0, limit), file.bytes.size() > limit};
    };

    if (in_pdf_formats(fmt)) {
        PreviewResult r;
        r.mode = "pdf";
        r.title = title;
        r.path = asset.path;
        r.revision = asset.revision;
        r.format = asset.format;
        r.status = asset.status;
        r.type_label = asset.type;
        return r;
    }
    if (fmt == "pptx") {
        PreviewResult r = pptx_preview(asset, file.bytes);
        r.revision = stat_revision(file);
        return r;
    }
    if (fmt == "dfb") {
        PreviewResult r = dfb_preview(asset, file.bytes, sibling_dir_entries);
        r.revision = stat_revision(file);
        return r;
    }
    if (fmt == "zip") {
        PreviewResult r = zip_preview(asset, file.bytes, kMaxArchiveNames);
        r.revision = stat_revision(file);
        return r;
    }
    if (fmt == "wlp") {
        PreviewResult wlp_r = wlp_preview(asset);
        wlp_r.revision = stat_revision(file);
        return wlp_r;
    }
    if (in_geotiff_formats(fmt)) {
        // rasterio unavailable (D4/D8): image fallback with the dependency
        // warning, reading the raw bytes.
        PreviewResult r;
        r.mode = "image";
        r.title = title;
        r.path = asset.path;
        r.revision = asset.revision;
        r.format = asset.format;
        r.status = asset.status;
        r.type_label = asset.type;
        r.image_bytes = file.bytes;
        r.warning =
            "\xE5\x9C\xB0\xE7\x90\x86\xE5\x85\x83\xE6\x95\xB0\xE6\x8D\xAE\xE8\xAF\xBB"
            "\xE5\x8F\x96\xE5\xA4\xB1\xE8\xB4\xA5\xEF\xBC\x8C\xE4\xBB\x85\xE6\x98\xBE"
            "\xE7\xA4\xBA\xE5\x9B\xBE\xE5\x83\x8F";  // 地理元数据读取失败，仅显示图像
        return r;
    }
    if (in_image_formats(fmt) || asset.type == "image_reference" ||
        asset.type == "reference_map") {
        PreviewResult r;
        r.mode = "image";
        r.title = title;
        r.path = asset.path;
        r.revision = asset.revision;
        r.format = asset.format;
        r.status = asset.status;
        r.type_label = asset.type;
        return r;
    }
    if (in_table_formats(fmt)) {
        PreviewResult r =
            table_preview(asset, file.bytes, fmt == "tsv" ? '\t' : ',', settings);
        r.revision = stat_revision(file);
        return r;
    }
    if (in_excel_formats(fmt)) {
        // pandas unavailable (D8)
        std::string msg = "Excel \xE9\xA2\x84\xE8\xA7\x88\xE5\xA4\xB1\xE8\xB4\xA5: "
                          "ModuleNotFoundError";  // Excel 预览失败:
        PreviewResult r = message_result(asset, msg, asset.status);
        r.revision = stat_revision(file);
        return r;
    }
    if (in_las_formats(fmt)) {
        std::string msg = "LAS \xE9\xA2\x84\xE8\xA7\x88\xE5\xA4\xB1\xE8\xB4\xA5: "
                          "ModuleNotFoundError";  // LAS 预览失败:
        PreviewResult las_r = message_result(asset, msg, asset.status);
        las_r.revision = stat_revision(file);
        return las_r;
    }
    if (asset.type == "well_log") {
        if (fmt == "xml") {
            auto xml_log = xml_well_log_preview(asset, file.bytes, settings);
            if (xml_log) {
                xml_log->revision = stat_revision(file);
                return *xml_log;
            }
        }
        std::string msg = "LAS \xE9\xA2\x84\xE8\xA7\x88\xE5\xA4\xB1\xE8\xB4\xA5: "
                          "ModuleNotFoundError";  // las fallback (geoviz absent)
        PreviewResult las_r = message_result(asset, msg, asset.status);
        las_r.revision = stat_revision(file);
        return las_r;
    }
    if (in_segy_formats(fmt) || asset.type == "seismic") {
        // segyio unavailable: the dependency-missing message (D8)
        PreviewResult segy_r = message_result(
            asset,
            "SEG-Y \xE9\xA2\x84\xE8\xA7\x88\xE4\xBE\x9D\xE8\xB5\x96"
            "\xE4\xB8\x8D\xE5\x8F\xAF\xE7\x94\xA8");  // SEG-Y 预览依赖不可用
        segy_r.revision = stat_revision(file);
        return segy_r;
    }
    if (in_html_formats(fmt)) {
        auto [chunk, truncated] = bounded_text();
        PreviewResult r;
        r.mode = "rich_text";
        r.title = title;
        r.path = asset.path;
        r.revision = asset.revision;
        r.format = asset.format;
        r.status = asset.status;
        r.type_label = asset.type;
        // plain decode("utf-8", errors=replace): a BOM would stay in the html
        r.rich_html = decode_utf8(chunk, false).value_or("");
        r.warning = truncated ? "\xE4\xBB\x85\xE6\x98\xBE\xE7\xA4\xBA\xE5\x89\x8D " +
                                    std::to_string(settings.text_limit_kib) + " KiB"
                              : "";
        r.truncated = truncated;
        return r;
    }
    if (in_markdown_formats(fmt)) {
        PreviewResult r = markdown_rich_preview(asset, file.bytes, settings);
        r.revision = stat_revision(file);
        return r;
    }
    if (in_json_formats(fmt)) {
        return json_preview(asset, file.bytes, settings);
    }
    if (in_audio_formats(fmt) || in_video_formats(fmt)) {
        PreviewResult r;
        r.mode = "media";
        r.title = title;
        r.path = asset.path;
        r.revision = asset.revision;
        r.format = asset.format;
        r.status = asset.status;
        r.type_label = asset.type;
        r.media_path = asset.path;
        return r;
    }
    if (fmt == "docx") {
        PreviewResult docx_r = message_result(
            asset,
            "docx \xE9\xA2\x84\xE8\xA7\x88\xE4\xBE\x9D\xE8\xB5\x96\xE7\xBC\xBA\xE5\xA4\xB1"
            "\xEF\xBC\x8C\xE8\xAF\xB7\xE5\xAE\x89\xE8\xA3\x85 python-docx");  // docx 预览依赖缺失，请安装 python-docx
        docx_r.warning = "";
        return docx_r;
    }
    if (fmt == "doc") {
        PreviewResult doc_r = message_result(
            asset,
            "\xE6\x97\xA7\xE7\x89\x88\xE4\xBA\x8C\xE8\xBF\x9B\xE5\x88\xB6 .doc "
            "\xE4\xB8\x8D\xE5\x8F\x97\xE6\x94\xAF\xE6\x8C\x81\xEF\xBC\x8C\xE8\xAF\xB7"
            "\xE5\x8F\xA6\xE5\xAD\x98\xE4\xB8\xBA .docx \xE5\x90\x8E\xE5\x86\x8D\xE9\xA2\x84"
            "\xE8\xA7\x88");  // 旧版二进制 .doc 不受支持，请另存为 .docx 后再预览
        doc_r.warning = "";
        return doc_r;
    }
    if (fmt == "xml") {
        auto xml_log = xml_well_log_preview(asset, file.bytes, settings);
        if (xml_log) {
            xml_log->revision = stat_revision(file);
            return *xml_log;
        }
        auto spreadsheet = spreadsheetml_preview(
            asset, file.bytes,
            static_cast<long long>(settings.text_limit_kib) * 1024,
            settings.table_max_rows, settings.table_max_columns);
        if (spreadsheet) {
            spreadsheet->revision = stat_revision(file);
            return *spreadsheet;
        }
    }
    if (fmt == "dat") {
        PreviewResult r = dat_preview(asset, file.bytes, settings);
        r.revision = stat_revision(file);
        return r;
    }
    if (in_text_formats(fmt)) {
        PreviewResult r = text_preview(asset, file.bytes, settings);
        r.revision = stat_revision(file);
        return r;
    }
    PreviewResult r = message_result(
        asset,
        "\xE6\xAD\xA4\xE6\xA0\xBC\xE5\xBC\x8F\xE6\x9A\x82\xE4\xB8\x8D\xE6\x94\xAF\xE6\x8C\x81"
        "\xE5\x86\x85\xE7\xBD\xAE\xE9\x98\x85\xE8\xAF\xBB\xEF\xBC\x8C\xE5\x8F\xAF\xE4\xBD\xBF"
        "\xE7\x94\xA8\xE6\x89\x93\xE5\xBC\x80\xE7\x9B\xAE\xE5\xBD\x95\xE5\xAE\x9A\xE4\xBD\x8D"
        "\xE6\x96\x87\xE4\xBB\xB6");  // 此格式暂不支持内置阅读，可使用打开目录定位文件
    r.warning = "";  // Python's terminal fallback sets message only
    return r;
}

}  // namespace pwb::ingest::preview
