#include "pwb/ingest/classifier.hpp"

#include <pwb/domain/text.hpp>

#include <set>

#include "pwb/ingest/py_compat.hpp"
#include "pwb/ingest/well_xml.hpp"
#include "pwb/ingest/xml_scanner.hpp"

namespace pwb::ingest {

namespace {

std::string lower_ascii(std::string s) {
    return domain::lower_ascii(s);  // shared impl (#1392)
}

bool in(std::initializer_list<std::string_view> set, const std::string& value) {
    for (auto s : set) {
        if (s == value) return true;
    }
    return false;
}

bool contains_any(const std::string& text,
                  std::initializer_list<std::string_view> needles) {
    for (auto n : needles) {
        if (text.find(n) != std::string::npos) return true;
    }
    return false;
}

bool path_has_exact_part(std::string_view path, std::string_view needle);

bool path_has_exact_part(std::string_view path, std::string_view needle) {
    size_t start = 0;
    while (start <= path.size()) {
        size_t end = path.find('/', start);
        if (end == std::string_view::npos) end = path.size();
        std::string part = lower_ascii(std::string(path.substr(start, end - start)));
        if (part == needle) return true;
        if (end == path.size()) break;
        start = end + 1;
    }
    return false;
}

bool any_part_contains(std::string_view path,
                       std::initializer_list<std::string_view> needles) {
    // pathlib.parts over '/' segments (Python also splits on '\\' only on
    // Windows; this port targets the POSIX layout).
    size_t start = 0;
    while (start <= path.size()) {
        size_t end = path.find('/', start);
        if (end == std::string_view::npos) end = path.size();
        std::string part = lower_ascii(std::string(path.substr(start, end - start)));
        if (contains_any(part, needles)) return true;
        if (end == path.size()) break;
        start = end + 1;
    }
    return false;
}

}  // namespace

Classification classify_path(std::string_view path) {
    PathParts parts = split_path_parts(path);
    std::string ext = lower_ascii(parts.suffix);
    if (!ext.empty() && ext[0] == '.') ext.erase(0, 1);
    std::string name = lower_ascii(parts.name);

    auto make = [](std::string t, std::string f, std::string s) {
        return Classification{std::move(t), std::move(f), std::move(s)};
    };

    if (ext == "las") return make("well_log", ext, "indexed");
    if (in({"sgy", "segy"}, ext)) return make("seismic", ext, "indexed");
    if (ext == "geojson") return make("geojson", ext, "indexed");
    if (ext == "json") {
        if (contains_any(name, {"facies", "paleo", "map", "geo"})) {
            return make("geojson", "json", "indexed");
        }
        return make("tabular", "json", "indexed");
    }
    if (in({"shp", "gpkg"}, ext)) return make("vector", ext, "indexed");
    if (ext == "dat") {
        // Python: "td" in path_parts is exact part membership (CJK keywords
        // use substring `in part`, mirrored by any_part_contains below)
        if (path_has_exact_part(path, "td") ||
            any_part_contains(path, {"\xE6\x97\xB6\xE6\xB7\xB1"} /* 时深 */)) {
            return make("time_depth", ext, "indexed");
        }
        if (any_part_contains(path, {"\xE5\xB1\x82\xE4\xBD\x8D" /* 层位 */})) {
            return make("horizon", ext, "indexed");
        }
        if (any_part_contains(path, {"\xE4\xBA\x95\xE5\x88\x86\xE5\xB1\x82" /* 井分层 */})) {
            return make("well_stratification", ext, "indexed");
        }
        if (any_part_contains(path, {"\xE4\xBA\x95\xE4\xBD\x8D" /* 井位 */}) ||
            contains_any(name, {"wellhead", "well_head"})) {
            return make("well_head", ext, "indexed");
        }
        return make("tabular", ext, "indexed");
    }
    if (in({"xlsx", "xls"}, ext)) return make("spreadsheet", ext, "indexed");
    if (ext == "xml") {
        if (contains_any(name, {"well", "log",
                                "\xE6\xB5\x8B\xE4\xBA\x95" /* 测井 */,
                                "\xE6\x9B\xB2\xE7\xBA\xBF" /* 曲线 */,
                                "witsml", "las"}) ||
            any_part_contains(path, {"well", "log",
                                     "\xE6\xB5\x8B\xE4\xBA\x95",
                                     "\xE6\x9B\xB2\xE7\xBA\xBF",
                                     "\xE4\xBA\x95\xE6\x9B\xB2\xE7\xBA\xBF" /* 井曲线 */})) {
            return make("well_log", ext, "indexed");
        }
        return make("spreadsheet", ext, "indexed");
    }
    if (ext == "csv") return make("tabular", ext, "indexed");
    if (in({"pdf", "ppt", "pptx", "docx", "doc"}, ext)) {
        return make("document", ext, "indexed_reference");
    }
    if (in({"png", "jpg", "jpeg", "tif", "tiff", "bmp"}, ext)) {
        return make("image_reference", ext, "indexed_reference");
    }
    if (ext == "dfb" || contains_any(name, {"\xE7\x9B\xB8\xE5\x9B\xBE" /* 相图 */})) {
        return make("reference_map", ext.empty() ? "unknown" : ext,
                    "indexed_reference");
    }
    if (ext == "wlp") return make("well_reference", ext, "indexed_reference");
    if (ext == "zip") return make("archive", ext, "indexed_reference");
    if (in({"md", "markdown", "htm", "html"}, ext)) {
        return make("document", ext, "indexed_reference");
    }
    if (in({"wav", "mp3", "flac", "ogg", "m4a"}, ext)) {
        return make("unknown", ext, "indexed_reference");
    }
    if (in({"mp4", "mov", "webm", "mkv", "avi"}, ext)) {
        return make("video", ext, "indexed_reference");
    }
    return make("unknown", ext.empty() ? "none" : ext, "indexed_reference");
}

Classification classify_import_path(std::string_view path, std::string_view content) {
    PathParts parts = split_path_parts(path);
    std::string ext = lower_ascii(parts.suffix);
    if (!ext.empty() && ext[0] == '.') ext.erase(0, 1);
    if (ext == "xml") {
        try {
            if (is_well_location_xml_bytes(content)) {
                return Classification{"well_head", "xml", "indexed"};
            }
            if (is_well_log_xml_bytes(content)) {
                return Classification{"well_log", "xml", "indexed"};
            }
        } catch (const XmlError&) {
            // unreadable/vendor XML still indexes as a generic resource
        }
    }
    return classify_path(path);
}

const std::map<std::string, std::string>& type_labels() {
    static const std::map<std::string, std::string> labels = {
        {"well_log", "\xE6\xB5\x8B\xE4\xBA\x95"},                     // 测井
        {"seismic", "\xE5\x9C\xB0\xE9\x9C\x87"},                      // 地震
        {"horizon", "\xE5\xB1\x82\xE4\xBD\x8D"},                      // 层位
        {"well_head", "\xE4\xBA\x95\xE4\xBD\x8D"},                    // 井位
        {"well_stratification", "\xE4\xBA\x95\xE5\x88\x86\xE5\xB1\x82"},  // 井分层
        {"time_depth", "\xE6\x97\xB6\xE6\xB7\xB1"},                   // 时深
        {"tabular", "\xE8\xA1\xA8\xE6\xA0\xBC"},                      // 表格
        {"spreadsheet", "\xE7\x94\xB5\xE5\xAD\x90\xE8\xA1\xA8\xE6\xA0\xBC"},  // 电子表格
        {"document", "\xE6\x96\x87\xE6\xA1\xA3"},                     // 文档
        {"image_reference", "\xE5\xBD\xB1\xE5\x83\x8F"},              // 影像
        {"reference_map", "\xE5\x8F\x82\xE8\x80\x83\xE5\x9B\xBE"},    // 参考图
        {"well_reference", "\xE6\xB5\x8B\xE4\xBA\x95\xE5\x8F\x82\xE8\x80\x83"},  // 测井参考
        {"archive", "\xE5\x8E\x8B\xE7\xBC\xA9\xE5\x8C\x85"},          // 压缩包
        {"vector", "\xE7\x9F\xA2\xE9\x87\x8F"},                       // 矢量
        {"geojson", "GeoJSON\xE7\x9F\xA2\xE9\x87\x8F"},               // GeoJSON矢量
        {"unknown", "\xE6\x9C\xAA\xE7\x9F\xA5"},                      // 未知
    };
    return labels;
}

bool is_preferred_import_extension(std::string_view ext) {
    static const std::set<std::string, std::less<>> preferred = {
        "las", "sgy", "segy", "dat", "csv", "xlsx", "xls", "xml", "json",
        "geojson", "pdf", "png", "jpg", "jpeg", "tif", "tiff", "bmp", "md",
        "markdown", "html", "htm", "txt", "shp", "gpkg", "wlp", "dfb", "zip",
    };
    return preferred.count(ext) > 0;
}

const std::map<std::string, std::string>& role_by_type() {
    static const std::map<std::string, std::string> roles = {
        {"well_log", "input"}, {"seismic", "input"}, {"horizon", "input"},
        {"well_head", "input"}, {"well_stratification", "input"},
        {"time_depth", "input"}, {"tabular", "input"},
        {"spreadsheet", "input"}, {"document", "reference"},
        {"image_reference", "reference"}, {"reference_map", "reference"},
        {"well_reference", "reference"}, {"archive", "reference"},
        {"vector", "reference"}, {"geojson", "input"}, {"unknown", "reference"},
    };
    return roles;
}

}  // namespace pwb::ingest
