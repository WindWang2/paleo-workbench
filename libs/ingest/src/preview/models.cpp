#include "pwb/ingest/preview/models.hpp"

#include <set>

#include "pwb/domain/sha256.hpp"

namespace pwb::ingest::preview {

namespace {

const std::set<std::string, std::less<>>& set_text_formats() {
    static const std::set<std::string, std::less<>> s = {"txt", "text", "log", "dat", "xml"};
    return s;
}
const std::set<std::string, std::less<>>& set_table_formats() {
    static const std::set<std::string, std::less<>> s = {"csv", "tsv"};
    return s;
}
const std::set<std::string, std::less<>>& set_excel_formats() {
    static const std::set<std::string, std::less<>> s = {"xlsx", "xls"};
    return s;
}
const std::set<std::string, std::less<>>& set_image_formats() {
    static const std::set<std::string, std::less<>> s = {"png", "jpg", "jpeg", "tif", "tiff", "bmp"};
    return s;
}
const std::set<std::string, std::less<>>& set_markdown_formats() {
    static const std::set<std::string, std::less<>> s = {"md", "markdown", "htm", "html"};
    return s;
}
const std::set<std::string, std::less<>>& set_html_formats() {
    static const std::set<std::string, std::less<>> s = {"htm", "html"};
    return s;
}
const std::set<std::string, std::less<>>& set_json_formats() {
    static const std::set<std::string, std::less<>> s = {"json", "geojson"};
    return s;
}
const std::set<std::string, std::less<>>& set_audio_formats() {
    static const std::set<std::string, std::less<>> s = {"wav", "mp3", "flac", "ogg", "m4a"};
    return s;
}
const std::set<std::string, std::less<>>& set_video_formats() {
    static const std::set<std::string, std::less<>> s = {"mp4", "mov", "webm", "mkv", "avi"};
    return s;
}

std::string json_escape_ascii(const std::string& s) {
    // Python json.dumps(ensure_ascii=True): escapes ", \, control chars
    // (\b \f \n \r \t named), and any non-ASCII as \uXXXX (lowercase hex,
    // surrogate pairs for astral code points).
    std::string out;
    out.reserve(s.size() + 8);
    out.push_back('"');
    auto append_u16 = [&out](unsigned long v) {
        char buf[8];
        std::snprintf(buf, sizeof(buf), "\\u%04lx", v);
        out += buf;
    };
    auto encode_cp = [&](unsigned long cp) {
        if (cp < 0x80) {
            out.push_back(static_cast<char>(cp));
        } else if (cp < 0x10000) {
            append_u16(cp);
        } else {
            unsigned long v = cp - 0x10000;
            append_u16(0xD800 + (v >> 10));
            append_u16(0xDC00 + (v & 0x3FF));
        }
    };
    for (size_t i = 0; i < s.size();) {
        unsigned char c = static_cast<unsigned char>(s[i]);
        if (c < 0x80) {
            switch (c) {
                case '"': out += "\\\""; break;
                case '\\': out += "\\\\"; break;
                case '\b': out += "\\b"; break;
                case '\f': out += "\\f"; break;
                case '\n': out += "\\n"; break;
                case '\r': out += "\\r"; break;
                case '\t': out += "\\t"; break;
                default:
                    if (c < 0x20) {
                        char buf[8];
                        std::snprintf(buf, sizeof(buf), "\\u%04x", unsigned(c));
                        out += buf;
                    } else {
                        out.push_back(static_cast<char>(c));
                    }
            }
            ++i;
            continue;
        }
        size_t len = c >= 0xF0 ? 4 : c >= 0xE0 ? 3 : 2;
        unsigned long cp = 0;
        if (i + len <= s.size() && (s[i + 1] & 0xC0) == 0x80 &&
            (len < 3 || (s[i + 2] & 0xC0) == 0x80) &&
            (len < 4 || (s[i + 3] & 0xC0) == 0x80)) {
            cp = c & (0xFF >> (len + 1));
            for (size_t k = 1; k < len; ++k) cp = (cp << 6) | (s[i + k] & 0x3F);
            encode_cp(cp);
            i += len;
        } else {
            encode_cp(c);  // invalid byte; fingerprint input is always valid
            ++i;
        }
    }
    out.push_back('"');
    return out;
}

std::string canonical_settings_json(const PreviewSettings& s) {
    // Ordered by key (sort_keys=True); bools lower-case; ints plain.
    std::string out = "{";
    auto entry = [&out](const std::string& key, const std::string& value,
                        bool first) {
        if (!first) out.push_back(',');
        out += json_escape_ascii(key);
        out.push_back(':');
        out += value;
    };
    entry("auto_fit_columns", s.auto_fit_columns ? "true" : "false", true);
    entry("density", json_escape_ascii(s.density), false);
    entry("font_size", std::to_string(s.font_size), false);
    entry("geotiff_thumbnail_px", std::to_string(s.geotiff_thumbnail_px), false);
    entry("geoviz_max_curves", std::to_string(s.geoviz_max_curves), false);
    entry("geoviz_max_depth_samples", std::to_string(s.geoviz_max_depth_samples), false);
    entry("geoviz_max_points", std::to_string(s.geoviz_max_points), false);
    entry("geoviz_max_slice_axis", std::to_string(s.geoviz_max_slice_axis), false);
    entry("geoviz_surface_grid_size", std::to_string(s.geoviz_surface_grid_size), false);
    entry("json_array_collapse_threshold", std::to_string(s.json_array_collapse_threshold), false);
    entry("json_expand_depth", std::to_string(s.json_expand_depth), false);
    entry("json_limit_mib", std::to_string(s.json_limit_mib), false);
    entry("media_autoplay", s.media_autoplay ? "true" : "false", false);
    entry("media_volume", std::to_string(s.media_volume), false);
    entry("pdf_fit_mode", json_escape_ascii(s.pdf_fit_mode), false);
    entry("pdf_zoom_percent", std::to_string(s.pdf_zoom_percent), false);
    entry("show_geo_metadata", s.show_geo_metadata ? "true" : "false", false);
    entry("show_metadata", s.show_metadata ? "true" : "false", false);
    entry("smooth_images", s.smooth_images ? "true" : "false", false);
    entry("table_max_columns", std::to_string(s.table_max_columns), false);
    entry("table_max_rows", std::to_string(s.table_max_rows), false);
    entry("text_limit_kib", std::to_string(s.text_limit_kib), false);
    entry("theme_mode", json_escape_ascii(s.theme_mode), false);
    entry("wrap_text", s.wrap_text ? "true" : "false", false);
    out += "}";
    return out;
}

}  // namespace

bool in_text_formats(std::string_view fmt) { return set_text_formats().count(fmt) > 0; }
bool in_table_formats(std::string_view fmt) { return set_table_formats().count(fmt) > 0; }
bool in_excel_formats(std::string_view fmt) { return set_excel_formats().count(fmt) > 0; }
bool in_image_formats(std::string_view fmt) { return set_image_formats().count(fmt) > 0; }
bool in_pdf_formats(std::string_view fmt) { return fmt == "pdf"; }
bool in_las_formats(std::string_view fmt) { return fmt == "las"; }
bool in_segy_formats(std::string_view fmt) { return fmt == "sgy" || fmt == "segy"; }
bool in_markdown_formats(std::string_view fmt) { return set_markdown_formats().count(fmt) > 0; }
bool in_html_formats(std::string_view fmt) { return set_html_formats().count(fmt) > 0; }
bool in_json_formats(std::string_view fmt) { return set_json_formats().count(fmt) > 0; }
bool in_geotiff_formats(std::string_view fmt) { return fmt == "tif" || fmt == "tiff"; }
bool in_audio_formats(std::string_view fmt) { return set_audio_formats().count(fmt) > 0; }
bool in_video_formats(std::string_view fmt) { return set_video_formats().count(fmt) > 0; }

std::string PreviewSettings::validate(const PreviewSettings& s) {
    if (s.density != "comfortable" && s.density != "compact") return "ValueError";
    if (s.theme_mode != "light" && s.theme_mode != "system") return "ValueError";
    auto check_int = [](int value, int lo, int hi) {
        return lo <= value && value <= hi;
    };
    if (!check_int(s.font_size, 8, 32)) return "ValueError";
    if (!check_int(s.text_limit_kib, 16, 4096)) return "ValueError";
    if (!check_int(s.table_max_rows, 20, 2000)) return "ValueError";
    if (!check_int(s.table_max_columns, 5, 200)) return "ValueError";
    if (!check_int(s.geotiff_thumbnail_px, 128, 2048)) return "ValueError";
    if (!check_int(s.pdf_zoom_percent, 25, 400)) return "ValueError";
    if (!check_int(s.json_limit_mib, 1, 64)) return "ValueError";
    if (!check_int(s.json_array_collapse_threshold, 10, 10000)) return "ValueError";
    if (!check_int(s.json_expand_depth, 0, 8)) return "ValueError";
    if (!check_int(s.media_volume, 0, 100)) return "ValueError";
    if (!check_int(s.geoviz_max_curves, 1, 64)) return "ValueError";
    if (!check_int(s.geoviz_max_depth_samples, 100, 50000)) return "ValueError";
    if (!check_int(s.geoviz_max_slice_axis, 64, 4096)) return "ValueError";
    if (!check_int(s.geoviz_max_points, 1000, 1000000)) return "ValueError";
    if (!check_int(s.geoviz_surface_grid_size, 32, 1024)) return "ValueError";
    if (s.pdf_fit_mode != "page" && s.pdf_fit_mode != "width" &&
        s.pdf_fit_mode != "custom") {
        return "ValueError";
    }
    return "";
}

PreviewSettings PreviewSettings::from_mapping(
    const std::vector<std::pair<std::string, long long>>& int_values,
    const std::vector<std::pair<std::string, bool>>& bool_values,
    const std::vector<std::pair<std::string, std::string>>& string_values,
    std::string* error,
    const std::vector<std::pair<std::string, double>>& float_values) {
    // Python dataclass strictness: a bool passed to an int field (or an
    // int/float to a bool field) raises TypeError before range checks.
    static const std::set<std::string> int_fields = {
        "font_size", "text_limit_kib", "table_max_rows", "table_max_columns",
        "geotiff_thumbnail_px", "pdf_zoom_percent", "json_limit_mib",
        "json_array_collapse_threshold", "json_expand_depth", "media_volume",
        "geoviz_max_curves", "geoviz_max_depth_samples", "geoviz_max_slice_axis",
        "geoviz_max_points", "geoviz_surface_grid_size"};
    static const std::set<std::string> bool_fields = {
        "show_metadata", "wrap_text", "auto_fit_columns", "smooth_images",
        "show_geo_metadata", "media_autoplay"};
    for (const auto& [k, v] : bool_values) {
        (void)v;
        if (int_fields.count(k)) {
            *error = "TypeError";
            return PreviewSettings{};
        }
    }
    for (const auto& [k, v] : int_values) {
        (void)v;
        if (bool_fields.count(k)) {
            *error = "TypeError";
            return PreviewSettings{};
        }
    }
    if (!float_values.empty()) {
        for (const auto& [k, v] : float_values) {
            (void)v;
            if (int_fields.count(k) || bool_fields.count(k)) {
                *error = "TypeError";
                return PreviewSettings{};
            }
        }
    }
    PreviewSettings s;
    auto apply_int = [&](const std::string& name, long long value) {
        int v = static_cast<int>(value);
        if (name == "font_size") s.font_size = v;
        else if (name == "text_limit_kib") s.text_limit_kib = v;
        else if (name == "table_max_rows") s.table_max_rows = v;
        else if (name == "table_max_columns") s.table_max_columns = v;
        else if (name == "geotiff_thumbnail_px") s.geotiff_thumbnail_px = v;
        else if (name == "pdf_zoom_percent") s.pdf_zoom_percent = v;
        else if (name == "json_limit_mib") s.json_limit_mib = v;
        else if (name == "json_array_collapse_threshold") s.json_array_collapse_threshold = v;
        else if (name == "json_expand_depth") s.json_expand_depth = v;
        else if (name == "media_volume") s.media_volume = v;
        else if (name == "geoviz_max_curves") s.geoviz_max_curves = v;
        else if (name == "geoviz_max_depth_samples") s.geoviz_max_depth_samples = v;
        else if (name == "geoviz_max_slice_axis") s.geoviz_max_slice_axis = v;
        else if (name == "geoviz_max_points") s.geoviz_max_points = v;
        else if (name == "geoviz_surface_grid_size") s.geoviz_surface_grid_size = v;
        // unknown keys are ignored, matching from_mapping
    };
    auto apply_bool = [&](const std::string& name, bool value) {
        if (name == "show_metadata") s.show_metadata = value;
        else if (name == "wrap_text") s.wrap_text = value;
        else if (name == "auto_fit_columns") s.auto_fit_columns = value;
        else if (name == "smooth_images") s.smooth_images = value;
        else if (name == "show_geo_metadata") s.show_geo_metadata = value;
        else if (name == "media_autoplay") s.media_autoplay = value;
    };
    auto apply_str = [&](const std::string& name, const std::string& value) {
        if (name == "pdf_fit_mode") s.pdf_fit_mode = value;
        else if (name == "density") s.density = value;
        else if (name == "theme_mode") s.theme_mode = value;
    };
    for (const auto& [k, v] : int_values) apply_int(k, v);
    for (const auto& [k, v] : bool_values) apply_bool(k, v);
    for (const auto& [k, v] : string_values) apply_str(k, v);
    *error = PreviewSettings::validate(s);
    return s;
}

std::string PreviewSettings::fingerprint() const {
    return pwb::domain::Sha256::of_bytes(canonical_settings_json(*this))
        .substr(0, 16);
}

}  // namespace pwb::ingest::preview
