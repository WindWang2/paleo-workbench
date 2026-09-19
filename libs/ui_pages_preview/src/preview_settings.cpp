#include <pwb/ui_pages_preview/preview_settings.hpp>

#include <algorithm>
#include <stdexcept>
#include <vector>

#include <pwb/domain/sha256.hpp>

namespace pwb::ui_pages_preview {

namespace {

// _INTEGER_RANGES parity — Python dict insertion order preserved so the
// first-failing field in the error message matches on multi-invalid input.
const std::vector<std::pair<std::string, std::pair<int, int>>>& integer_ranges() {
    static const std::vector<std::pair<std::string, std::pair<int, int>>> ranges = {
        {"font_size", {8, 32}},
        {"text_limit_kib", {16, 4096}},
        {"table_max_rows", {20, 2000}},
        {"table_max_columns", {5, 200}},
        {"geotiff_thumbnail_px", {128, 2048}},
        {"pdf_zoom_percent", {25, 400}},
        {"json_limit_mib", {1, 64}},
        {"json_array_collapse_threshold", {10, 10000}},
        {"json_expand_depth", {0, 8}},
        {"media_volume", {0, 100}},
        {"geoviz_max_curves", {1, 64}},
        {"geoviz_max_depth_samples", {100, 50000}},
        {"geoviz_max_slice_axis", {64, 4096}},
        {"geoviz_max_points", {1000, 1000000}},
        {"geoviz_surface_grid_size", {32, 1024}},
    };
    return ranges;
}

bool is_int_value(const domain::Json& v) {
    // Python: isinstance(value, int) and not isinstance(value, bool).
    return v.is_number_integer() || v.is_number_unsigned();
}

[[noreturn]] void fail(const std::string& message) {
    throw std::invalid_argument(message);
}

}  // namespace

const std::vector<std::string>& preview_settings_fields() {
    static const std::vector<std::string> fields = {
        "font_size",
        "show_metadata",
        "text_limit_kib",
        "wrap_text",
        "table_max_rows",
        "table_max_columns",
        "auto_fit_columns",
        "smooth_images",
        "geotiff_thumbnail_px",
        "show_geo_metadata",
        "pdf_fit_mode",
        "pdf_zoom_percent",
        "json_limit_mib",
        "json_array_collapse_threshold",
        "json_expand_depth",
        "media_autoplay",
        "media_volume",
        "geoviz_max_curves",
        "geoviz_max_depth_samples",
        "geoviz_max_slice_axis",
        "geoviz_max_points",
        "geoviz_surface_grid_size",
        "density",
        "theme_mode",
    };
    return fields;
}

PreviewSettings PreviewSettings::from_mapping(const domain::Json& values) {
    PreviewSettings s;
    if (!values.is_object()) {
        return s;
    }
    auto get = [&](const std::string& key) -> const domain::Json* {
        auto it = values.find(key);
        return it == values.end() ? nullptr : &*it;
    };
    auto get_int = [&](const std::string& key, int& out) {
        if (const domain::Json* v = get(key)) {
            if (!is_int_value(*v)) fail(key + " must be an integer");
            out = static_cast<int>(v->get<long long>());
        }
    };
    auto get_bool = [&](const std::string& key, bool& out) {
        if (const domain::Json* v = get(key)) {
            if (!v->is_boolean()) fail(key + " must be a boolean");
            out = v->get<bool>();
        }
    };
    auto get_str = [&](const std::string& key, std::string& out) {
        if (const domain::Json* v = get(key)) {
            if (!v->is_string()) fail(key + " must be a string");
            out = v->get<std::string>();
        }
    };

    get_int("font_size", s.font_size);
    get_bool("show_metadata", s.show_metadata);
    get_int("text_limit_kib", s.text_limit_kib);
    get_bool("wrap_text", s.wrap_text);
    get_int("table_max_rows", s.table_max_rows);
    get_int("table_max_columns", s.table_max_columns);
    get_bool("auto_fit_columns", s.auto_fit_columns);
    get_bool("smooth_images", s.smooth_images);
    get_int("geotiff_thumbnail_px", s.geotiff_thumbnail_px);
    get_bool("show_geo_metadata", s.show_geo_metadata);
    get_str("pdf_fit_mode", s.pdf_fit_mode);
    get_int("pdf_zoom_percent", s.pdf_zoom_percent);
    get_int("json_limit_mib", s.json_limit_mib);
    get_int("json_array_collapse_threshold", s.json_array_collapse_threshold);
    get_int("json_expand_depth", s.json_expand_depth);
    get_bool("media_autoplay", s.media_autoplay);
    get_int("media_volume", s.media_volume);
    get_int("geoviz_max_curves", s.geoviz_max_curves);
    get_int("geoviz_max_depth_samples", s.geoviz_max_depth_samples);
    get_int("geoviz_max_slice_axis", s.geoviz_max_slice_axis);
    get_int("geoviz_max_points", s.geoviz_max_points);
    get_int("geoviz_surface_grid_size", s.geoviz_surface_grid_size);
    get_str("density", s.density);
    get_str("theme_mode", s.theme_mode);

    // __post_init__ validation order: density, theme_mode, bools, int ranges,
    // pdf_fit_mode.
    if (s.density != "comfortable" && s.density != "compact") {
        fail("density must be 'comfortable' or 'compact'");
    }
    if (s.theme_mode != "light" && s.theme_mode != "system") {
        fail("theme_mode must be 'light' or 'system'");
    }
    // (bool/int types already enforced by the getters — the Python post-init
    // re-check is only reachable when the constructor receives bad types,
    // which from_mapping cannot produce.)
    const std::map<std::string, int> ints = {
        {"font_size", s.font_size},
        {"text_limit_kib", s.text_limit_kib},
        {"table_max_rows", s.table_max_rows},
        {"table_max_columns", s.table_max_columns},
        {"geotiff_thumbnail_px", s.geotiff_thumbnail_px},
        {"pdf_zoom_percent", s.pdf_zoom_percent},
        {"json_limit_mib", s.json_limit_mib},
        {"json_array_collapse_threshold", s.json_array_collapse_threshold},
        {"json_expand_depth", s.json_expand_depth},
        {"media_volume", s.media_volume},
        {"geoviz_max_curves", s.geoviz_max_curves},
        {"geoviz_max_depth_samples", s.geoviz_max_depth_samples},
        {"geoviz_max_slice_axis", s.geoviz_max_slice_axis},
        {"geoviz_max_points", s.geoviz_max_points},
        {"geoviz_surface_grid_size", s.geoviz_surface_grid_size},
    };
    for (const auto& [name, range] : integer_ranges()) {
        const int value = ints.at(name);
        if (value < range.first || value > range.second) {
            fail(name + " must be between " + std::to_string(range.first) +
                 " and " + std::to_string(range.second));
        }
    }
    if (s.pdf_fit_mode != "page" && s.pdf_fit_mode != "width" &&
        s.pdf_fit_mode != "custom") {
        fail("pdf_fit_mode must be page, width, or custom");
    }
    return s;
}

domain::Json PreviewSettings::to_mapping() const {
    return domain::Json{
        {"font_size", font_size},
        {"show_metadata", show_metadata},
        {"text_limit_kib", text_limit_kib},
        {"wrap_text", wrap_text},
        {"table_max_rows", table_max_rows},
        {"table_max_columns", table_max_columns},
        {"auto_fit_columns", auto_fit_columns},
        {"smooth_images", smooth_images},
        {"geotiff_thumbnail_px", geotiff_thumbnail_px},
        {"show_geo_metadata", show_geo_metadata},
        {"pdf_fit_mode", pdf_fit_mode},
        {"pdf_zoom_percent", pdf_zoom_percent},
        {"json_limit_mib", json_limit_mib},
        {"json_array_collapse_threshold", json_array_collapse_threshold},
        {"json_expand_depth", json_expand_depth},
        {"media_autoplay", media_autoplay},
        {"media_volume", media_volume},
        {"geoviz_max_curves", geoviz_max_curves},
        {"geoviz_max_depth_samples", geoviz_max_depth_samples},
        {"geoviz_max_slice_axis", geoviz_max_slice_axis},
        {"geoviz_max_points", geoviz_max_points},
        {"geoviz_surface_grid_size", geoviz_surface_grid_size},
        {"density", density},
        {"theme_mode", theme_mode},
    };
}

std::string PreviewSettings::fingerprint() const {
    // Python: json.dumps(to_mapping(), sort_keys=True, separators=(",",":"))
    // -> sha256 hexdigest()[:16]. ordered_json preserves insertion order, so
    // the keys must be inserted in sorted order explicitly.
    std::vector<std::string> keys = preview_settings_fields();
    std::sort(keys.begin(), keys.end());
    const domain::Json mapping = to_mapping();
    domain::Json sorted = domain::Json::object();
    for (const auto& key : keys) {
        sorted[key] = mapping[key];
    }
    const std::string payload = sorted.dump(
        -1, ' ', true, nlohmann::ordered_json::error_handler_t::strict);
    return domain::Sha256::of_bytes(payload).substr(0, 16);
}

std::string mode_category(const std::string& mode) {
    static const std::map<std::string, std::string> categories = {
        {"text", "text"},       {"rich_text", "text"},
        {"web_document", "text"}, {"table", "table"},
        {"well_log", "table"},  {"seismic", "table"},
        {"image", "image"},     {"geotiff", "image"},
        {"pdf", "pdf"},         {"json_tree", "json"},
        {"media", "media"},     {"geoviz", "geoviz"},
    };
    auto it = categories.find(mode);
    return it != categories.end() ? it->second : "general";
}

}  // namespace pwb::ui_pages_preview
