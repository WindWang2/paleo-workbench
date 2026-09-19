// Preview value types shared by the preview stack:
//
// * ``PreviewResult`` — resources/preview_parsers/models.py frozen dataclass.
// * ``PreviewSettings`` — resources/preview_settings.py immutable profile.
// * ``GeovizPreviewOptions`` — geoviz PreviewOptions DTO (fingerprint seam).
//
// ``engine_preview`` is an opaque payload owned by the geoviz bridge; the
// core stores a shared_ptr<void> so cache/disk logic can weigh and move it
// without knowing its type.
#pragma once

#include "pwb/domain/json.hpp"

#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

namespace pwb::ui_data_core {

// ---------------------------------------------------------------------------
// PreviewResult (resources/preview_parsers/models.py)
// ---------------------------------------------------------------------------

// PreviewMode vocabulary — kept as strings (Python Literal).
namespace preview_mode {
inline constexpr const char* kEmpty = "empty";
inline constexpr const char* kGeoviz = "geoviz";
inline constexpr const char* kPdf = "pdf";
inline constexpr const char* kImage = "image";
inline constexpr const char* kText = "text";
inline constexpr const char* kTable = "table";
inline constexpr const char* kWellLog = "well_log";
inline constexpr const char* kSeismic = "seismic";
inline constexpr const char* kMessage = "message";
inline constexpr const char* kRichText = "rich_text";
inline constexpr const char* kJsonTree = "json_tree";
inline constexpr const char* kGeotiff = "geotiff";
inline constexpr const char* kMedia = "media";
inline constexpr const char* kWebDocument = "web_document";
}  // namespace preview_mode

// Format vocabulary of preview_parsers (distinct from preview_strategy.py).
namespace parser_formats {
const std::vector<std::string>& text_formats();     // txt text log dat xml
const std::vector<std::string>& table_formats();    // csv tsv
const std::vector<std::string>& excel_formats();    // xlsx xls
const std::vector<std::string>& image_formats();    // png jpg jpeg tif tiff bmp
const std::vector<std::string>& pdf_formats();      // pdf
const std::vector<std::string>& las_formats();      // las
const std::vector<std::string>& segy_formats();     // sgy segy
const std::vector<std::string>& markdown_formats(); // md markdown htm html
const std::vector<std::string>& html_formats();     // htm html
const std::vector<std::string>& json_formats();     // json geojson
const std::vector<std::string>& geotiff_formats();  // tif tiff
const std::vector<std::string>& audio_formats();    // wav mp3 flac ogg m4a
const std::vector<std::string>& video_formats();    // mp4 mov webm mkv avi
bool in(std::string_view fmt, const std::vector<std::string>& set);
}  // namespace parser_formats

inline constexpr long long kMaxTextPreviewBytes = 256 * 1024;
inline constexpr int kMaxTableRows = 200;
inline constexpr int kMaxTableColumns = 40;
inline constexpr long long kMaxJsonParseBytes = 5 * 1024 * 1024;
inline constexpr int kJsonArrayCollapseThreshold = 100;

struct PreviewResult {
    std::string mode;                        // PreviewMode
    std::string title;
    std::string path;
    // revision tuple is opaque identity material (backend-defined shape).
    domain::Json revision = domain::Json(nullptr);
    std::string format;
    std::string status;
    std::string type_label;
    std::string message;
    std::string warning;
    std::string text;
    std::vector<std::string> table_headers;
    std::vector<std::vector<std::string>> table_rows;
    std::vector<std::pair<std::string, std::string>> summary_rows;
    std::vector<std::string> sheets;
    bool truncated = false;
    // Heavy payloads decoded/loaded off the UI thread.
    std::string image_bytes;                 // raw bytes (binary-safe)
    std::string pdf_bytes;
    std::string rich_html;
    domain::Json json_payload = domain::Json(nullptr);
    bool json_truncated = false;
    std::vector<std::pair<std::string, std::string>> geo_metadata;
    std::string media_path;
    std::shared_ptr<void> engine_preview;    // opaque geoviz PreparedPreview
    long long estimated_bytes = 0;
    bool visualization_available = false;
    // Transient build failures must be retried, never retained in caches.
    bool cacheable = true;
    bool retryable = false;
    std::vector<std::string> data_headers;
    std::vector<std::vector<std::string>> data_rows;
    // seismic_volume stays engine-side (numpy); out of the portable DTO.

    bool operator==(const PreviewResult&) const = default;
};

// ---------------------------------------------------------------------------
// GeovizPreviewOptions (geoviz PreviewOptions — fingerprint seam only)
// ---------------------------------------------------------------------------

struct GeovizPreviewOptions {
    std::string profile = "local";
    int max_curves = 12;
    int max_depth_samples = 2000;
    int max_slice_axis = 512;
    int max_points = 50000;
    int surface_grid_size = 256;

    // geoviz.PAYLOAD_SCHEMA_VERSION — the disk cache key bakes it in so
    // payload-format changes never collide with stale entries.
    static constexpr int kPayloadSchemaVersion = 1;

    static GeovizPreviewOptions local() { return {}; }

    // _options_fingerprint: sha256("p|c|d|a|p|g|schema=v")[:16].
    std::string fingerprint() const;
    bool operator==(const GeovizPreviewOptions&) const = default;
};

// ---------------------------------------------------------------------------
// PreviewSettings (resources/preview_settings.py)
// ---------------------------------------------------------------------------

struct PreviewSettings {
    int font_size = 12;
    bool show_metadata = true;
    int text_limit_kib = 256;
    bool wrap_text = false;
    int table_max_rows = 200;
    int table_max_columns = 40;
    bool auto_fit_columns = true;
    bool smooth_images = true;
    int geotiff_thumbnail_px = 256;
    bool show_geo_metadata = true;
    std::string pdf_fit_mode = "width";   // page | width | custom
    int pdf_zoom_percent = 100;
    int json_limit_mib = 5;
    int json_array_collapse_threshold = 100;
    int json_expand_depth = 2;
    bool media_autoplay = false;
    int media_volume = 70;
    int geoviz_max_curves = 12;
    int geoviz_max_depth_samples = 2000;
    int geoviz_max_slice_axis = 512;
    int geoviz_max_points = 50000;
    int geoviz_surface_grid_size = 256;
    std::string density = "comfortable";  // comfortable | compact
    std::string theme_mode = "light";     // light | system

    static PreviewSettings defaults() { return {}; }

    // __post_init__ validation: throws std::invalid_argument (ValueError /
    // TypeError both map there; the oracle distinguishes by message kind).
    void validate() const;  // throws std::invalid_argument

    // __post_init__ with pre-recorded type errors spliced into the Python
    // check order (density → theme → bool types → int types+ranges → pdf).
    void validate_post_init(
        const std::vector<std::string>* bool_type_errors,
        const std::vector<std::string>* int_type_errors) const;

    // PreviewSettings.from_mapping: unknown keys ignored; missing → default.
    // Json values must already carry the right types (int/bool/string) —
    // from_mapping passes them straight to the dataclass ctor, so a Json
    // string for an int field → TypeError in Python → invalid_argument here.
    static PreviewSettings from_mapping(const domain::Json& values);

    // asdict() — ordered by declaration order (dataclass field order).
    domain::Json to_mapping() const;

    // fingerprint(): sha256(json.dumps(mapping, sort_keys, separators))[:16].
    std::string fingerprint() const;

    // to_geoviz_options().
    GeovizPreviewOptions to_geoviz_options() const;

    bool operator==(const PreviewSettings&) const = default;
};

// _INTEGER_RANGES / _BOOLEAN_FIELDS — exposed for the settings store layer.
const std::vector<std::pair<std::string, std::pair<int, int>>>&
preview_settings_integer_ranges();
const std::vector<std::string>& preview_settings_boolean_fields();

}  // namespace pwb::ui_data_core
