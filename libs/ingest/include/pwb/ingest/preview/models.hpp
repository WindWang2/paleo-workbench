// Preview data models — port of resources/preview_parsers/models.py and
// resources/preview_settings.py (format tables, PreviewResult shape, and the
// validated PreviewSettings with its canonical fingerprint).
#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace pwb::ingest::preview {

bool in_text_formats(std::string_view fmt);
bool in_table_formats(std::string_view fmt);
bool in_excel_formats(std::string_view fmt);
bool in_image_formats(std::string_view fmt);
bool in_pdf_formats(std::string_view fmt);
bool in_las_formats(std::string_view fmt);
bool in_segy_formats(std::string_view fmt);
bool in_markdown_formats(std::string_view fmt);
bool in_html_formats(std::string_view fmt);
bool in_json_formats(std::string_view fmt);
bool in_geotiff_formats(std::string_view fmt);
bool in_audio_formats(std::string_view fmt);
bool in_video_formats(std::string_view fmt);

constexpr int kMaxTextPreviewBytes = 256 * 1024;
constexpr int kMaxTableRows = 200;
constexpr int kMaxTableColumns = 40;
constexpr long long kMaxJsonParseBytes = 5LL * 1024 * 1024;
constexpr int kJsonArrayCollapseThreshold = 100;
constexpr int kMaxArchiveNames = 500;
constexpr long long kMaxEmbeddedImageBytes = 16LL * 1024 * 1024;
constexpr long long kMaxCentralDirectoryBytes = 4LL * 1024 * 1024;
constexpr int kMaxCentralEntries = 10000;
constexpr long long kMaxCentralNameBytes = 1024 * 1024;

// Revision: either a bare (size, mtime_ns) stat tuple or the resource
// revision token ("resource", id, path, type, format, status, checksum, stat).
struct Revision {
    bool present = false;
    // token form when token.size() > 2, stat tuple otherwise
    std::vector<std::string> text_parts;
    bool has_stat = false;
    long long stat_size = 0;
    long long stat_mtime_ns = 0;
};

// The slice of ResourceItem the preview parsers consume.
struct ResourceRef {
    std::string id;
    std::string name;
    std::string path;
    std::string type;
    std::string format;
    std::string status;
    std::string checksum;
    Revision revision;
};

struct PreviewResult {
    std::string mode;
    std::string title;
    std::string path;
    Revision revision;
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
    std::string image_bytes;
    std::string rich_html;
    bool json_truncated = false;
    bool json_ok = false;  // json_payload is not None
    std::string media_path;
    long long estimated_bytes = 0;
    bool visualization_available = false;
    bool cacheable = true;
    bool retryable = false;
    std::vector<std::string> data_headers;
    std::vector<std::vector<std::string>> data_rows;
};

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
    std::string pdf_fit_mode = "width";
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
    std::string density = "comfortable";
    std::string theme_mode = "light";

    // __post_init__: returns the Python exception class name on violation
    // ("TypeError"/"ValueError"), empty when valid. The `bool_is_int` flags
    // let callers from int-typed sources mark booleans explicitly; C++ bool
    // is a distinct type like Python's.
    static std::string validate(const PreviewSettings& s);
    static PreviewSettings defaults() { return PreviewSettings{}; }
    // from_mapping: only known keys applied; type/range errors surface as
    // the Python exception class name via `error`.
    static PreviewSettings from_mapping(
        const std::vector<std::pair<std::string, long long>>& int_values,
        const std::vector<std::pair<std::string, bool>>& bool_values,
        const std::vector<std::pair<std::string, std::string>>& string_values,
        std::string* error,
        const std::vector<std::pair<std::string, double>>& float_values = {});
    // sha256 of json.dumps(to_mapping(), ensure_ascii=True, sort_keys=True,
    // separators=(",", ":")), first 16 hex chars.
    std::string fingerprint() const;
};

}  // namespace pwb::ingest::preview
