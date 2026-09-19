#pragma once

// UI-09 — ProjectWellMapPage model semantics (Qt-free).
//
// Ports project_well_map_page.py::_rebuild_cache + CRS-warning / overlay
// gating and the domain helpers it calls:
//   - reference wells (spatial_scope == "reference") are withheld entirely
//   - display name "" -> "(未命名井)"
//   - coordinate_status_flag: untransformed -> " ⚠坐标未转换",
//     invalid -> " ⚠坐标无效", missing -> " ⚠无坐标", ok/other -> ""
//   - coords prefer (project_x, project_y) then fall back to surface;
//     either component absent/NaN -> row excluded from the scatter arrays
//   - is_ok = status == "ok" AND project coords present
//   - stable layout: OK block first, then flagged block (original order
//     preserved inside each block); row_to_array maps list row -> array idx
//   - CRS warnings: boundary/survey frames that don't match the project CRS
//     are withheld AND surfaced in the ⚠ banner
//   - crs_equivalent: exact match, else trimmed case-insensitive compare
//     (pyproj CRS.equals has no C++ equivalent here — see ledger)
//   - complete_survey_corners: 3 stored corners -> parallelogram 4th
//     (p1 + p3 - p2); any other count passes through

#include <map>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include <pwb/ui_wellseis/slices.hpp>

namespace pwb::ui_wellseis {

// domain.py::coordinate_status_flag parity.
std::string coordinate_status_flag(const std::string& status);

// domain.py::crs_equivalent parity — exact or trimmed case-insensitive.
bool crs_equivalent(const std::string& left, const std::string& right);

// domain.py::complete_survey_corners parity.
std::vector<std::pair<double, double>> complete_survey_corners(
    const std::vector<std::pair<double, double>>& corners);

// One well-list row (the list model + scatter-source rows, all wells).
struct WellMapListRow {
    std::string well_id;
    std::string display_name;  // "(未命名井)" when name empty
    std::string flag;          // coordinate_status_flag
};

// Rebuilt scatter state — mirrors the Python cached arrays.
struct WellMapModel {
    std::vector<WellMapListRow> rows;          // every non-reference well
    std::vector<std::pair<double, double>> scatter;  // OK block then flagged
    std::vector<std::string> ordered_labels;   // scatter order
    std::vector<int> ordered_list_rows;        // scatter idx -> list row
    std::map<int, int> row_to_array;           // list row -> scatter idx
    std::size_t ok_count = 0;                  // split point
};

WellMapModel build_well_map_model(const std::vector<WellSlice>& wells);

// _refresh_crs_warnings parity — one entry per withheld frame.
std::vector<std::string> crs_warnings(const ProjectSlice& project);

// Joined banner text: "⚠ a；b" ("" when no warnings).
std::string crs_warning_banner(const ProjectSlice& project);

// "工程 CRS: {crs or 未设置}".
std::string project_crs_label(const ProjectSlice& project);

// _render_boundary parity — closed ring in project CRS, empty when the
// frame mismatches (never silently overlay).
std::vector<std::pair<double, double>> boundary_ring(
    const ProjectSlice& project);

// _render_survey_extents parity — rings for CRS-compatible surveys only,
// each completed+closed, separated for the caller (one entry per survey).
std::vector<std::vector<std::pair<double, double>>> survey_extent_rings(
    const ProjectSlice& project);

// Vertex cap for reference-layer rendering (MAX_REFERENCE_VERTICES).
inline constexpr std::size_t kMaxReferenceVertices = 20000;

}  // namespace pwb::ui_wellseis
