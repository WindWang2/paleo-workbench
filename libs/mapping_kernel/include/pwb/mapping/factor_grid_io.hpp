#pragma once

// pwb::mapping — FactorGridResult JSON envelope codec, a faithful C++ port of
// the serialization surface of paleo_workbench/workflow/factor_grid_result.py
// (full-conversion plan M7 leaf; conversion task 18). Frozen against the
// Python implementation via committed oracle fixtures
// (tools/oracle/generate_grid_envelope_fixtures.py):
//   * from_legacy_task_parameters: interp_backend/backend `or` chain and the
//     "unknown" fallback; metadata descriptor fallbacks for crs/unit and
//     provenance; the algorithm_parameters update semantics (existing keys
//     keep position and value rules: r_squared always present, grid_label /
//     power are two-argument `get` (an explicit null wins), n_points is
//     `len(sample_points or []) or params.n_points`, n_break_lines defaults
//     through 0); grid_var / azimuth_deg branches gate on `is not None`;
//     grid_boundary truthiness (empty → no ring);
//   * canonical nodata: null (engine), NaN and ±Infinity (adapter / legacy
//     json.dumps) all normalize to float32 NaN; finite values round through
//     float32 (0.1 → 0.10000000149011612; 1e40 → inf → NaN);
//   * to_descriptor / to_legacy_dict / GridStatistics.to_dict key sets and
//     orders, with every non-finite number JSON-encoded as null (strict JSON,
//     `allow_nan=False` safe);
//   * error messages are contract: Python str(ValueError/KeyError) text,
//     e.g. "grid_x must contain only finite coordinates",
//     "grid_z shape (2, 2) does not match expected (2, 3)", "'grid_x'".
// Qt-free, Python-free, numpy-free; reuses the already-frozen
// pwb::mapping::grid_statistics kernel (M7) for the statistics block.
//
// Not ported here (see docs/development/cpp-conversion-swarm-20/ledgers/
// 18-decisions.md): the NPZ zip/.npy container of grid_artifact.py, the
// project-live-cache bridge, and from_constrained_idw_dict (separate slice).

#include <pwb/domain/json.hpp>
#include <pwb/mapping/interpolator.hpp>

#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace pwb::mapping {

using pwb::domain::Json;

// Workflow-level single-factor grid envelope (FactorGridResult minus the
// in-memory-only helpers). Statistics are always populated, matching the
// Python __post_init__/_finalise contract.
struct FactorGridEnvelope {
    int height = 0;
    int width = 0;
    std::vector<float> grid_z;         // row-major height*width, NaN = nodata
    std::vector<float> variance_grid;  // empty = absent (Kriging only)
    std::vector<double> grid_x;        // width column coordinates
    std::vector<double> grid_y;        // height row coordinates
    std::string factor_name;
    std::string algorithm_id;
    Json algorithm_parameters = Json::object();
    // Metadata values pass through verbatim (Python keeps whatever the
    // descriptor dict held); JSON null encodes Python None.
    Json crs = Json(nullptr);            // null == source XY, never guessed
    Json unit = Json(nullptr);
    Json generator_version = Json(nullptr);
    Json source_refs = Json::array();
    Json run_ref = Json(nullptr);
    Json created_at = Json(nullptr);
    std::optional<std::vector<std::pair<double, double>>> boundary;
    GridStatistics statistics;
};

// Parse JSON text written by Python json.dumps: NaN / Infinity / -Infinity
// literals are legal there but RFC-invalid, so nlohmann rejects them. They
// are carried through as the corresponding non-finite double values (the
// envelope turns them into float32 NaN / raises the finite-check errors
// exactly where Python does).
Json parse_json_python_tolerant(const std::string& text);

// FactorGridResult.from_legacy_task_parameters. `parameters` / `metadata`
// must be JSON objects (metadata may be null = absent). Exception mapping
// with the Python str(exc) message text: KeyError → std::out_of_range,
// ValueError → std::invalid_argument, TypeError → std::runtime_error.
FactorGridEnvelope from_legacy_task_parameters(
    const Json& parameters, const std::string& factor_name,
    const std::optional<std::string>& crs = std::nullopt,
    const std::optional<std::string>& unit = std::nullopt,
    const Json& metadata = Json());

// GridStatistics.to_dict — strict JSON (non-finite → null), fixed key order.
Json grid_statistics_to_json(const GridStatistics& stats);

// encode_legacy_grid_lists — nested [height][width] lists, non-finite cells
// as null, finite cells widened to double.
Json encode_legacy_grid_lists(const std::vector<float>& grid_z, int height,
                              int width);

// encode_legacy_axis_list — float64 list of numbers.
Json encode_legacy_axis_list(const std::vector<double>& axis);

// FactorGridResult.to_descriptor — metadata only, never grid arrays;
// contours are never emitted here (from_legacy cannot produce them).
Json to_descriptor(const FactorGridEnvelope& result);

// FactorGridResult.to_legacy_dict — the engine-style dict (grid_z nested
// lists with null nodata); no std/statistics/crs keys.
Json to_legacy_dict(const FactorGridEnvelope& result);

}  // namespace pwb::mapping
