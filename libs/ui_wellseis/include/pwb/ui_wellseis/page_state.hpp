#pragma once

// UI-09 — page-level lifecycle / enablement / honest-unavailable helpers
// (Qt-free).
//
// Ports:
//   well_seismic_joint_page.py   — "联合三维引擎不可用: {exc or 'unknown'}"
//   well_log_canvas_panel.py     — backend combo labels + env default
//   well_log_prediction_page.py  — engine export gate: PNG only, SVG/PDF
//                                  honestly redirect to Legacy
//   seismic_control_panel.py     — controls disabled without a task
//   well_map_panel.py            — work-area / reference counts

#include <optional>
#include <string>
#include <vector>

#include <pwb/ui_wellseis/slices.hpp>

namespace pwb::ui_wellseis {

// "{label}不可用: {error or 'unknown'}" — the joint page's placeholder.
std::string engine_unavailable_text(const std::string& engine_label,
                                    const std::string& error);

// Well-log canvas backends (BackendName parity).
inline const char* kWellLogBackendLegacy = "legacy";
inline const char* kWellLogBackendEngine = "engine";

// Backend combo labels ("Legacy (QPainter)" / "WellLogEngine").
std::string well_log_backend_label(const std::string& backend);

// PALEO_USE_WELLLOG_ENGINE default: engine ON unless the env says
// 0/legacy (string-level parity — the Qt shell reads the env itself and
// calls this for the verdict).
bool well_log_engine_env_enabled(const std::string& env_value);

// Engine-backend export gate: PNG screenshots always allowed; vector
// formats report the honest redirect (nullopt = allowed). `format_label`
// is the upper-cased user pick ("PNG" | "SVG" | "PDF").
std::optional<std::string> well_log_export_block_reason(
    const std::string& backend, const std::string& format_label);

// SeismicControlPanel rule — all controls enable exactly when a task is
// bound (update_state's set_controls_enabled calls).
bool seismic_controls_enabled(bool has_task);

// Well-map header counts: work-area vs reference wells.
struct WellMapCounts {
    std::size_t workarea = 0;
    std::size_t reference = 0;
};
WellMapCounts well_map_counts(const std::vector<WellSlice>& wells);
std::string well_map_counts_text(const WellMapCounts& counts);

}  // namespace pwb::ui_wellseis
