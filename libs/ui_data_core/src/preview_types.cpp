// Preview value types — see preview_types.hpp for the contract.

#include "pwb/ui_data_core/preview_types.hpp"

#include "pwb/domain/sha256.hpp"
#include "pwb/ui_data_core/json_util.hpp"

#include <algorithm>
#include <map>
#include <stdexcept>

namespace pwb::ui_data_core {

// ---------------------------------------------------------------------------
// parser_formats — preview_parsers/models.py format vocabularies
// ---------------------------------------------------------------------------

namespace parser_formats {

namespace {
const std::vector<std::string>& make_set(std::initializer_list<const char*> v) {
    static const std::vector<std::string> storage = [&v] {
        std::vector<std::string> out;
        out.reserve(v.size());
        for (const char* s : v) out.emplace_back(s);
        return out;
    }();
    return storage;
}
}  // namespace

const std::vector<std::string>& text_formats() {
    static const auto& s = make_set({"txt", "text", "log", "dat", "xml"});
    return s;
}
const std::vector<std::string>& table_formats() {
    static const auto& s = make_set({"csv", "tsv"});
    return s;
}
const std::vector<std::string>& excel_formats() {
    static const auto& s = make_set({"xlsx", "xls"});
    return s;
}
const std::vector<std::string>& image_formats() {
    static const auto& s = make_set({"png", "jpg", "jpeg", "tif", "tiff", "bmp"});
    return s;
}
const std::vector<std::string>& pdf_formats() {
    static const auto& s = make_set({"pdf"});
    return s;
}
const std::vector<std::string>& las_formats() {
    static const auto& s = make_set({"las"});
    return s;
}
const std::vector<std::string>& segy_formats() {
    static const auto& s = make_set({"sgy", "segy"});
    return s;
}
const std::vector<std::string>& markdown_formats() {
    static const auto& s = make_set({"md", "markdown", "htm", "html"});
    return s;
}
const std::vector<std::string>& html_formats() {
    static const auto& s = make_set({"htm", "html"});
    return s;
}
const std::vector<std::string>& json_formats() {
    static const auto& s = make_set({"json", "geojson"});
    return s;
}
const std::vector<std::string>& geotiff_formats() {
    static const auto& s = make_set({"tif", "tiff"});
    return s;
}
const std::vector<std::string>& audio_formats() {
    static const auto& s = make_set({"wav", "mp3", "flac", "ogg", "m4a"});
    return s;
}
const std::vector<std::string>& video_formats() {
    static const auto& s = make_set({"mp4", "mov", "webm", "mkv", "avi"});
    return s;
}

bool in(std::string_view fmt, const std::vector<std::string>& set) {
    return std::find(set.begin(), set.end(), fmt) != set.end();
}

}  // namespace parser_formats

// ---------------------------------------------------------------------------
// GeovizPreviewOptions
// ---------------------------------------------------------------------------

std::string GeovizPreviewOptions::fingerprint() const {
    const std::string raw =
        profile + "|" + std::to_string(max_curves) + "|" +
        std::to_string(max_depth_samples) + "|" + std::to_string(max_slice_axis) +
        "|" + std::to_string(max_points) + "|" +
        std::to_string(surface_grid_size) + "|schema=" +
        std::to_string(kPayloadSchemaVersion);
    return domain::Sha256::of_bytes(raw).substr(0, 16);
}

// ---------------------------------------------------------------------------
// PreviewSettings — _INTEGER_RANGES / _BOOLEAN_FIELDS
// ---------------------------------------------------------------------------

const std::vector<std::pair<std::string, std::pair<int, int>>>&
preview_settings_integer_ranges() {
    // _INTEGER_RANGES declaration order.
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

const std::vector<std::string>& preview_settings_boolean_fields() {
    static const std::vector<std::string> fields = {
        "show_metadata",   "wrap_text",  "auto_fit_columns",
        "smooth_images",   "show_geo_metadata", "media_autoplay",
    };
    return fields;
}

namespace {

int int_field(const PreviewSettings& s, const std::string& name) {
    if (name == "font_size") return s.font_size;
    if (name == "text_limit_kib") return s.text_limit_kib;
    if (name == "table_max_rows") return s.table_max_rows;
    if (name == "table_max_columns") return s.table_max_columns;
    if (name == "geotiff_thumbnail_px") return s.geotiff_thumbnail_px;
    if (name == "pdf_zoom_percent") return s.pdf_zoom_percent;
    if (name == "json_limit_mib") return s.json_limit_mib;
    if (name == "json_array_collapse_threshold")
        return s.json_array_collapse_threshold;
    if (name == "json_expand_depth") return s.json_expand_depth;
    if (name == "media_volume") return s.media_volume;
    if (name == "geoviz_max_curves") return s.geoviz_max_curves;
    if (name == "geoviz_max_depth_samples") return s.geoviz_max_depth_samples;
    if (name == "geoviz_max_slice_axis") return s.geoviz_max_slice_axis;
    if (name == "geoviz_max_points") return s.geoviz_max_points;
    if (name == "geoviz_surface_grid_size") return s.geoviz_surface_grid_size;
    return 0;
}

bool bool_field(const PreviewSettings& s, const std::string& name) {
    if (name == "show_metadata") return s.show_metadata;
    if (name == "wrap_text") return s.wrap_text;
    if (name == "auto_fit_columns") return s.auto_fit_columns;
    if (name == "smooth_images") return s.smooth_images;
    if (name == "show_geo_metadata") return s.show_geo_metadata;
    if (name == "media_autoplay") return s.media_autoplay;
    return false;
}

// is_int_json: isinstance(v, int) and not isinstance(v, bool) — floats are
// NOT ints (5.5 → TypeError) and neither are bools.
bool is_int_json(const domain::Json& value) {
    return !value.is_boolean() &&
           (value.is_number_integer() || value.is_number_unsigned());
}

void set_int_field(PreviewSettings& s, const std::string& name, int v) {
    if (name == "font_size") s.font_size = static_cast<int>(v);
    else if (name == "text_limit_kib") s.text_limit_kib = static_cast<int>(v);
    else if (name == "table_max_rows") s.table_max_rows = static_cast<int>(v);
    else if (name == "table_max_columns") s.table_max_columns = static_cast<int>(v);
    else if (name == "geotiff_thumbnail_px") s.geotiff_thumbnail_px = static_cast<int>(v);
    else if (name == "pdf_zoom_percent") s.pdf_zoom_percent = static_cast<int>(v);
    else if (name == "json_limit_mib") s.json_limit_mib = static_cast<int>(v);
    else if (name == "json_array_collapse_threshold")
        s.json_array_collapse_threshold = static_cast<int>(v);
    else if (name == "json_expand_depth") s.json_expand_depth = static_cast<int>(v);
    else if (name == "media_volume") s.media_volume = static_cast<int>(v);
    else if (name == "geoviz_max_curves") s.geoviz_max_curves = static_cast<int>(v);
    else if (name == "geoviz_max_depth_samples")
        s.geoviz_max_depth_samples = static_cast<int>(v);
    else if (name == "geoviz_max_slice_axis")
        s.geoviz_max_slice_axis = static_cast<int>(v);
    else if (name == "geoviz_max_points") s.geoviz_max_points = static_cast<int>(v);
    else if (name == "geoviz_surface_grid_size")
        s.geoviz_surface_grid_size = static_cast<int>(v);
}

void set_bool_field(PreviewSettings& s, const std::string& name, bool v) {
    if (name == "show_metadata") s.show_metadata = v;
    else if (name == "wrap_text") s.wrap_text = v;
    else if (name == "auto_fit_columns") s.auto_fit_columns = v;
    else if (name == "smooth_images") s.smooth_images = v;
    else if (name == "show_geo_metadata") s.show_geo_metadata = v;
    else if (name == "media_autoplay") s.media_autoplay = v;
}

const std::vector<std::string>& known_fields() {
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

bool is_int_field(const std::string& name) {
    for (const auto& [n, _] : preview_settings_integer_ranges()) {
        if (n == name) return true;
    }
    return false;
}
bool is_bool_field(const std::string& name) {
    for (const auto& n : preview_settings_boolean_fields()) {
        if (n == name) return true;
    }
    return false;
}

}  // namespace

// __post_init__ runs AFTER every ctor assignment, so the first raised error
// follows this exact order: density → theme_mode → bool types → int
// types+ranges → pdf_fit_mode. The C++ port splices recorded type errors
// into the same positions.
void PreviewSettings::validate() const {
    validate_post_init(nullptr, nullptr);
}

void PreviewSettings::validate_post_init(
    const std::vector<std::string>* bool_type_errors,
    const std::vector<std::string>* int_type_errors) const {
    if (density != "comfortable" && density != "compact") {
        throw std::invalid_argument("density must be 'comfortable' or 'compact'");
    }
    if (theme_mode != "light" && theme_mode != "system") {
        throw std::invalid_argument("theme_mode must be 'light' or 'system'");
    }
    if (bool_type_errors != nullptr && !bool_type_errors->empty()) {
        throw std::invalid_argument(bool_type_errors->front() +
                                    " must be a boolean");
    }
    for (const auto& [name, range] : preview_settings_integer_ranges()) {
        if (int_type_errors != nullptr &&
            std::find(int_type_errors->begin(), int_type_errors->end(), name) !=
                int_type_errors->end()) {
            throw std::invalid_argument(name + " must be an integer");
        }
        const int value = int_field(*this, name);
        if (value < range.first || value > range.second) {
            throw std::invalid_argument(name + " must be between " +
                                        std::to_string(range.first) + " and " +
                                        std::to_string(range.second));
        }
    }
    if (pdf_fit_mode != "page" && pdf_fit_mode != "width" &&
        pdf_fit_mode != "custom") {
        throw std::invalid_argument("pdf_fit_mode must be page, width, or custom");
    }
}

PreviewSettings PreviewSettings::from_mapping(const domain::Json& values) {
    PreviewSettings out;
    std::vector<std::string> bool_type_errors, int_type_errors;
    if (values.is_object()) {
        for (const auto& name : known_fields()) {
            const auto it = values.find(name);
            if (it == values.end()) {
                continue;
            }
            if (is_int_field(name)) {
                if (is_int_json(*it)) {
                    set_int_field(out, name,
                                  static_cast<int>(it->get<long long>()));
                } else {
                    int_type_errors.push_back(name);
                }
            } else if (is_bool_field(name)) {
                if (it->is_boolean()) {
                    set_bool_field(out, name, it->get<bool>());
                } else {
                    bool_type_errors.push_back(name);
                }
            } else {
                // pdf_fit_mode / density / theme_mode carry no type check —
                // the ctor stores any value and the vocab test raises
                // ValueError. A non-string lands as an out-of-vocab sentinel.
                const std::string v =
                    it->is_string() ? it->get<std::string>() : "\x01<non-string>";
                if (name == "pdf_fit_mode") out.pdf_fit_mode = v;
                else if (name == "density") out.density = v;
                else out.theme_mode = v;
            }
        }
    }
    out.validate_post_init(&bool_type_errors, &int_type_errors);
    return out;
}

domain::Json PreviewSettings::to_mapping() const {
    // asdict() in dataclass field order — fingerprint sorts keys anyway.
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
    // json.dumps(ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    // — domain::Json (ordered_json) serializes objects sorted by key when
    // built through the object() map; here we serialize via a sorted map.
    std::map<std::string, domain::Json> sorted;
    for (auto it = to_mapping().begin(); it != to_mapping().end(); ++it) {
        sorted.emplace(it.key(), it.value());
    }
    domain::Json sorted_json = domain::Json::object();
    for (const auto& [k, v] : sorted) {
        sorted_json[k] = v;
    }
    // nlohmann compact dump uses separators (",", ":") by default;
    // ensure_ascii=true gives Python's \uXXXX escaping for non-ASCII.
    const std::string payload = sorted_json.dump(-1, ' ', true);
    return domain::Sha256::of_bytes(payload).substr(0, 16);
}

GeovizPreviewOptions PreviewSettings::to_geoviz_options() const {
    GeovizPreviewOptions out;
    out.profile = "local";
    out.max_curves = geoviz_max_curves;
    out.max_depth_samples = geoviz_max_depth_samples;
    out.max_slice_axis = geoviz_max_slice_axis;
    out.max_points = geoviz_max_points;
    out.surface_grid_size = geoviz_surface_grid_size;
    return out;
}

}  // namespace pwb::ui_data_core
