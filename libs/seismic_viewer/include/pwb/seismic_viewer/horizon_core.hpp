#pragma once

// VIZ-D horizon core — Qt-free port of the frozen geoviz oracle
// (geo-viz-engine@08851951, geoviz_seismic/horizon.py) plus the interactive
// pick model required by the D-line mandate:
//
//   * horizon_quad_faces — regular-grid triangulation (frozen winding);
//   * parse_horizon_text — HorizonParser.parse parity (numeric scraping,
//     duplicate last-wins, NaN gaps, axes offsets/scale);
//   * fill_nearest — exact Euclidean distance transform nearest fill with a
//     pixel-distance cap (scipy distance_transform_edt parity);
//   * fill_rbf — local linear-kernel RBF (degree 0, k nearest neighbours,
//     smoothing) parity of scipy.interpolate.RBFInterpolator;
//   * extract_along_horizon — amplitude extraction / windowed RMS along a
//     horizon grid (truncating sample index, NaN propagation);
//   * HorizonPickSet — pick/edit/delete model with STABLE source-volume
//     binding (volume id + revision, axis, slice index, time unit, schema
//     version) and JSON persistence + the oracle CSV export format.
//
// Grids are row-major (rows = inlines, cols = crosslines); gaps are NaN.

#include <array>
#include <cstdint>
#include <span>
#include <string>
#include <string_view>
#include <vector>

namespace pwb::seismic_viewer::horizon {

struct Grid2D {
    std::int64_t rows{0};
    std::int64_t cols{0};
    std::vector<double> values; // rows * cols, NaN where absent

    Grid2D() = default;
    Grid2D(std::int64_t r, std::int64_t c, double fill)
        : rows(r), cols(c), values(static_cast<std::size_t>(r * c), fill) {}

    [[nodiscard]] double at(std::int64_t r, std::int64_t c) const {
        return values[static_cast<std::size_t>(r * cols + c)];
    }
    double& at(std::int64_t r, std::int64_t c) {
        return values[static_cast<std::size_t>(r * cols + c)];
    }
};

// Triangle faces for an nI×nX regular grid, two triangles per quad, winding
// frozen to (p0, p1, p2) and (p1, p3, p2) with p0 = i*nX + j. Empty for
// either extent < 2.
[[nodiscard]] std::vector<std::array<std::int64_t, 3>>
horizon_quad_faces(std::int64_t n_i, std::int64_t n_x);

struct HorizonAxes {
    std::vector<std::int64_t> ilines;
    std::vector<std::int64_t> xlines;
};

struct ParsedHorizon {
    Grid2D grid;
    int points_read{0};   // (il, xl) pairs scraped from the file
    int matched{0};       // pairs that landed inside the axes
};

// HorizonParser.parse parity. Numeric scraping uses the oracle regex
// `[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?`; lines need >= 3 numbers; the first two
// map (after offsets) onto the axes, the third is scaled. Duplicate
// (il, xl) pairs: last wins. Zero scraped points throws std::invalid_argument
// with the oracle message; zero MATCHED points is not an error (the grid
// stays all-NaN, `matched` == 0 — callers surface that honestly).
[[nodiscard]] ParsedHorizon parse_horizon_text(std::string_view text,
                                               const HorizonAxes& axes,
                                               double scale = 1.0,
                                               std::int64_t iline_offset = 0,
                                               std::int64_t xline_offset = 0);

// Exact Euclidean nearest fill. `max_dist <= 0` means unlimited; otherwise
// gaps farther than that many PIXELS from the nearest sample stay NaN.
// Tie rule (two samples at identical distance): the lexicographically
// smallest (row, col) sample wins — deterministic in C++; the scipy oracle
// may resolve exact ties differently, fixtures avoid equidistant ties and
// the ledger declares the rule.
[[nodiscard]] Grid2D fill_nearest(const Grid2D& grid, double max_dist = 0.0);

// Local linear-kernel RBF fill (kernel phi(r) = r, degree 0 => constant
// polynomial term, k = min(neighbors, n_samples) nearest known cells,
// smoothing added to the kernel diagonal). Solved with dense Gaussian
// elimination with partial pivoting; parity vs scipy's lstsq solver is
// asserted within the oracle tolerance (declared there), not bit-exact.
[[nodiscard]] Grid2D fill_rbf(const Grid2D& grid, double max_dist = 0.0,
                              int neighbors = 24, double smoothing = 0.0);

// Amplitude extraction along a horizon grid over a packed float32 volume
// (n_i, n_x, n_s, row-major). Sample index = trunc((grid - t0_ms) / dt_ms)
// clipped to [0, n_s - 1] (int32 truncation parity); window == 0 reads the
// single sample, window == N computes the RMS over 2N+1 samples with
// out-of-bounds offsets contributing nothing (all-NaN windows stay NaN).
// Output is rows*cols float32, NaN where the grid is NaN.
[[nodiscard]] std::vector<float>
extract_along_horizon(std::span<const float> volume, std::int64_t n_i,
                      std::int64_t n_x, std::int64_t n_s, const Grid2D& grid,
                      double dt_ms, double t0_ms = 0.0, int window = 0);

// ---------------------------------------------------------------------------
// Interactive pick model with stable source binding (D-line addition: the
// Python oracle only kept loose (il, xl, t) triples with no binding).
// ---------------------------------------------------------------------------

struct HorizonPick {
    double inline_no{0.0};
    double crossline_no{0.0};
    double time_value{0.0};
};

struct HorizonPickSet {
    static constexpr std::uint32_t kSchemaVersion = 1;

    std::vector<HorizonPick> picks;
    // Stable binding to the source volume / view the picks were taken on.
    std::string volume_id;
    std::uint64_t volume_revision{0};
    std::string axis_name; // "inline" | "crossline" | "sample"
    std::int64_t slice_index{0};
    std::string time_unit; // geometry unit of the sample axis, e.g. "ms"
    std::uint32_t schema_version{kSchemaVersion};
};

// Edits. add appends (duplicates allowed — the oracle list did too).
void add_pick(HorizonPickSet& set, HorizonPick pick);
// Removes the pick nearest to (il, xl, t) when it lies within the given
// tolerances; returns false when nothing matched.
[[nodiscard]] bool remove_pick_near(HorizonPickSet& set, double inline_no,
                                    double crossline_no, double time_value,
                                    double tol_inline, double tol_crossline,
                                    double tol_time);
// Moves pick `index` (no-op out of range). Returns false when out of range.
[[nodiscard]] bool move_pick(HorizonPickSet& set, std::size_t index, HorizonPick pick);
void clear_picks(HorizonPickSet& set);

// JSON persistence (strict, fail-closed): a tiny fixed-schema codec, no
// external dependency. `to_json` always emits the binding block even when
// empty so a reloaded set carries its provenance.
[[nodiscard]] std::string to_json(const HorizonPickSet& set);

struct PickParseResult {
    bool ok{false};
    std::string error; // non-empty on failure (schema/shape violations)
    HorizonPickSet set;
};
[[nodiscard]] PickParseResult from_json(std::string_view text);

// CSV export parity with seismic_view._on_export_picks: header
// "inline,crossline,time_ms", rows "%.1f".
[[nodiscard]] std::string to_csv(const HorizonPickSet& set);

} // namespace pwb::seismic_viewer::horizon
