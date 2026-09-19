#pragma once

// viz_e_dat_preview — VIZ-E preview line: well-head (Name/X/Y scatter) and
// horizon (XYZ surface) DAT parsing for the paleo workbench platform.
//
// 1:1 port of the parser half of geoviz/previews/dat.py (frozen behavior
// source @0885195, gitlink 08851951f3bbc0beb90886adf52e1928f4383c16):
//   * well head — dat.py:587-765 `_well_head_payload`: marker check
//     (:598-599), column mapping (:600-606, `_column_mapping` :167-194),
//     declared-width disambiguation (:607-622), UWI vote (:629-641),
//     SourceCRS/unit declarations (:643-653), per-row Chinese diagnostics
//     (:698-731), hard display cap (:715-718).
//   * horizon — dat.py:792-855 `_surface_payload` up to the axis decision:
//     marker check (:794-795), FIELD:x/y/z mapping (:799, `_horizon_field_
//     mapping` :227-247), sampled XYZ rows (:808-809 via
//     `representative_indices` :125-128), independent-geometry gate
//     (:815-822), axis ranges/size (:823-826).
//   * IDW interpolation (dat.py:828-839) is deliberately NOT ported — the
//     C++ side reuses mapping_kernel; this file stops at valid points plus
//     axis ranges/resolution. The `_MAX_IDW_POINT_CELLS` budget constrains
//     the interpolation input, not the grid resolution (dat.py:828-832).
//
// Documented deviations from the frozen Python (all narrow; none change
// which files PARSE — the *supported predicate* is separately declared
// strictly stronger below):
//   * PreviewOptions collapses into the `max_points` argument. The frozen
//     well-head path IGNORES options and hard-caps valid records at
//     `_MAX_POINTS` (dat.py:715-718, param named `_options` at :589), so
//     `WellHeadPreview::records` carries every valid row — no subsampling
//     exists on that path in Python (the "sampled" contract holds
//     vacuously: with the default cap of 50,000, representative_indices
//     (length, 50'000) is the identity for every file Python accepts).
//     Here the cap is `_sample_limit(max_points) = max(1, min(max_points,
//     50'000))` (dat.py:577-578), identical to Python for the default.
//     The horizon path DOES sample (dat.py:808); the port uses
//     numpy >= 1.20 `np.linspace(..., dtype=int64)` semantics: float64
//     `i * ((length-1)/(limit-1))`, floor, last index pinned to
//     length-1.
//   * horizon grid resolution uses `PreviewOptions.surface_grid_size`'s
//     frozen default 256 (geoviz/contracts.py:41) because the C++ API has
//     no options object; `grid_n = min(256, max(2, ceil(sqrt(n_sampled))))
//     (dat.py:823-824)`.
//   * Asset-supplied metadata (`request.source_version/source_crs/
//     coordinate_units/comparison_crs`, dat.py:591-665) has no C++ input
//     in this API: only file declarations are surfaced (`_merge_declared_
//     metadata` with empty asset metadata is exactly the declared value),
//     empty means undeclared/unknown — never guessed from coordinates.
//   * `HorizonPoints::source_crs/coordinate_units` are a documented
//     additive extension: Python's `SurfacePreviewPayload` carries no CRS/
//     unit metadata (dat.py:850-855), but the workbench host needs the
//     provenance line, so the identical declaration helpers (dat.py:250-
//     295) run on the horizon header too — including their
//     conflicting-declaration errors.
//   * `HorizonPoints::total_records` counts every non-comment data row;
//     `skipped_records = total_records - x.size()` is the row count
//     dropped by sampling (Python raises on any invalid sampled row, so
//     no "invalid" category exists on this path).
//   * Python `casefold`/`isalnum`/`int()`/`float()` accept exotic Unicode
//     (ß→ss, non-ASCII digits, underscore digit separators); QString
//     `toLower`/`isLetterOrNumber`/`toLongLong`/`toDouble` are used
//     instead. Python `str.isspace` also treats U+001C..1F/NEL as
//     whitespace; QChar::isSpace does not.
//   * UnicodeDecodeError detail text is approximated; the header budget
//     (:44-45, :155-159) counts UTF-16 code units where Python counts
//     code points (differs only for chars beyond the BMP).
//
// Failures throw std::runtime_error with the GeoVizError wording
// (dat.py:26, :581-584, :973-977):
//   * schema problems  → "DAT 数据结构与资源类型不匹配: <detail>"
//   * IO problems      → "无法读取 DAT 数据: <detail>"
//   * well-head cap    → "井位数据超过 <n> 个有效记录的显示上限" (RESOURCE_LIMIT
//                        message verbatim, no schema prefix).

#include <string>
#include <vector>

namespace pwb::viz_e {

// One valid well-head row (dat.py:672-690 parse_row: name non-empty,
// finite X/Y, optional UWI column value stripped).
struct WellHeadRecord {
    std::string name;
    double x = 0.0;
    double y = 0.0;
    std::string uwi;
};

// Result of `_well_head_payload` (dat.py:587-765) reduced to the fields
// the xy_scatter host renders. `records` holds every valid row (see the
// deviations block above for why Python never subsamples this path);
// `skipped_records = total_records - valid_records` mirrors
// XYPreviewDiagnostics.skipped_count (dat.py:61-63).
struct WellHeadPreview {
    std::vector<WellHeadRecord> records;   // all valid rows (cap-enforced)
    long long total_records = 0;
    long long valid_records = 0;
    long long skipped_records = 0;
    std::string source_crs;         // SourceCRS declaration value; undeclared = empty (never guessed)
    std::string coordinate_units;   // declared unit; unknown = empty
    std::string source_version;     // always empty (asset metadata not ported; dat.py:739)
};

// Parse failures throw std::runtime_error with the Chinese GeoVizError
// wording documented at the top of this file.
WellHeadPreview parse_well_head(const std::string& path, int max_points = 50'000);

// File-side predicate: well-head marker present AND the Name/X/Y column
// mapping resolves (dat.py:394-399 marker check; the mapping precheck is
// task-mandated, strictly stronger than Python's supports(), which checks
// the marker only). Reads the file head; any error → false.
bool well_head_supported(const std::string& path);

// Result of `_surface_payload` (dat.py:792-826) up to the axis decision.
// x/y/z hold the sampled rows (representative_indices, dat.py:808); every
// row is finite by construction (invalid sampled rows raise instead).
struct HorizonPoints {
    std::vector<double> x, y, z;    // valid (sampled) rows
    long long total_records = 0;
    long long skipped_records = 0;
    std::string source_crs, coordinate_units;
    // Axis decision copied from Python (dat.py:825-826):
    // grid = linspace(min, max, grid_n) per axis.
    double x_min = 0, x_max = 0, y_min = 0, y_max = 0;
    int grid_n = 0;                 // per-axis grid size decided by Python
                                    // (≤ _MAX_SURFACE_AXIS; dat.py:823-824)
};

HorizonPoints parse_horizon_points(const std::string& path, int max_points = 50'000);

// File-side predicate: horizon marker present AND the FIELD:x/y/z mapping
// resolves against the first data row's width (dat.py:402-407 marker
// check; the mapping precheck is strictly stronger than Python's
// supports()). Any error → false.
bool horizon_supported(const std::string& path);

// Per-axis grid resolution decided during parse_horizon_points after
// dat.py:823-824:
//   axis_limit = max(1, min(surface_grid_size=256, _MAX_SURFACE_AXIS=256))
//   grid_n     = min(axis_limit, max(2, ceil(sqrt(sampled_rows))))
// Returns the stored decision (0 for a default-constructed HorizonPoints).
int horizon_grid_resolution(const HorizonPoints& pts);

}  // namespace pwb::viz_e
