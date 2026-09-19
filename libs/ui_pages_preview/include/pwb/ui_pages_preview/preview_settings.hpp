#pragma once

// Port of paleo_workbench/resources/preview_settings.py (model + coercion)
// and the _MODE_CATEGORY map from ui/pages/preview_settings_panel.py (UI-07).
//
// NOTE: ui_data_core (UI-03) carries an identically shaped PreviewSettings in
// its own namespace; that lib is not on this branch's baseline, so this POD
// is defined here field-for-field against resources/preview_settings.py. Both
// may coexist on main — the integration slice maps or merges them.

#include <map>
#include <string>

#include <pwb/domain/json.hpp>

namespace pwb::ui_pages_preview {

// Immutable user preferences shared by every data preview request.
// Defaults and ranges mirror the Python dataclass exactly.
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
    std::string pdf_fit_mode = "width";  // page | width | custom
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
    std::string density = "comfortable";    // comfortable | compact
    std::string theme_mode = "light";       // light | system

    static PreviewSettings defaults() { return {}; }

    // Strict validation — Python __post_init__ parity:
    //   bool field non-bool        -> std::invalid_argument ("TypeError" kind)
    //   int field non-int/out of range -> std::invalid_argument
    //   pdf_fit_mode / density / theme_mode illegal -> std::invalid_argument
    // Unknown keys in `values` are ignored; missing keys take defaults.
    static PreviewSettings from_mapping(const domain::Json& values);

    domain::Json to_mapping() const;

    // sha256-16 hex of the compact sorted-JSON mapping
    // (json.dumps(sort_keys, separators) + hashlib.sha256[:16] parity).
    std::string fingerprint() const;

    bool operator==(const PreviewSettings&) const = default;
};

// _MODE_CATEGORY: preview mode → settings-panel category; "general" fallback.
std::string mode_category(const std::string& mode);

// The ordered field-name list (dataclass field order) — used by the store to
// iterate keys without reflection.
const std::vector<std::string>& preview_settings_fields();

}  // namespace pwb::ui_pages_preview
