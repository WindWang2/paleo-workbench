#pragma once

// pwb::factor_host — deterministic scientific fingerprints for factor
// interpolation, a faithful C++ port of the pure leaves of
// paleo_workbench/workflow/interpolation_fingerprint.py (CONV-08).
//
// Fingerprints are SHA-256 over the Python-canonical JSON encoding of the
// payload dicts (see canonical_json.hpp). Dirty classification prefers
// false DIRTY over false CLEAN. The project/task-resolution glue
// (fingerprints_for_task + its request memo) stays on the host: the C++
// entry point consumes the already-normalized sample set, exactly the set
// the Python engine consumes (V8 M3).
// Qt-free, Python-free, numpy-free.

#include <pwb/domain/json.hpp>

#include <optional>
#include <string>

namespace pwb::factor_host {

using pwb::domain::Json;

inline constexpr int kFingerprintSchemaVersion = 1;
inline constexpr const char* kDefaultGeneratorVersion = "factor-interp-v1";
inline constexpr const char* kConstrainedIdwLabel = "constrained_idw";

// SHA-256 of the canonical JSON encoding of *payload*.
std::string stable_sha256(const Json& payload);

// float(value) with finite filtering and -0.0 → 0.0 normalization
// (sign-of-zero must not flip a fingerprint). nullopt = Python None.
std::optional<double> finite_double(const Json& value);

// Ordered (x, y, z) sample records with the extract_xy_values validity
// rules; directional-engine extras (q / b_i / qc_flag) ride along.
// Input: JSON array of sample objects (null tolerated). Output: JSON array.
Json extract_sample_records(const Json& sample_points);

// METHOD_TO_BACKEND table (UI label → engine backend), keyed by UTF-8 label.
const Json& method_backend_table();

std::string resolve_backend(const std::string& method);
bool backend_uses_breaks(std::string_view backend);
bool backend_uses_directions(std::string_view backend);
bool backend_uses_power(std::string_view backend);
bool backend_uses_anisotropy(std::string_view backend);

// Normalize polylines without reordering vertices or polylines; polylines
// with fewer than two surviving points are dropped.
Json normalize_polylines(const Json& polylines);

// Direction-line parameter dicts: coordinates ≥ 2 points, string id,
// optional float semi_major / semi_minor / azimuth_deg.
Json normalize_direction_params(const Json& params);

struct FactorFingerprints {
    std::string geometry;
    std::string values;
    std::string algorithm;
    std::string constraints;
    std::string result;
    std::string backend = "idw";
    int schema_version = kFingerprintSchemaVersion;

    Json to_dict() const;
};

struct BuildFingerprintsArgs {
    const Json* sample_points = nullptr;  // array (null treated as empty)
    std::string method;
    int grid_n = 50;
    double power = 2.0;
    double azimuth_deg = 0.0;
    double semi_major = 1.0;
    double semi_minor = 0.4;
    const Json* fault_polylines = nullptr;
    const Json* direction_params = nullptr;
    std::string crs;               // "" = no CRS
    std::string generator_version = kDefaultGeneratorVersion;
    std::string target_horizon;    // "" = none
    std::optional<std::string> duplicate_policy;
};

FactorFingerprints build_factor_fingerprints(const BuildFingerprintsArgs& args);

enum class FactorDirtyState {
    CLEAN,
    DIRTY_VALUES,
    DIRTY_GEOMETRY,
    DIRTY_ALGORITHM,
    DIRTY_CONSTRAINTS,
    MISSING_OUTPUT,
    UNKNOWN,
};

std::string to_string(FactorDirtyState state);

// Plain-data view of a FactorMapTask for the classification leaves.
// parameters / grid_metadata may be null; callers without a live factor-grid
// session cache leave has_live_factor_grid = false.
struct FactorTaskView {
    const Json* parameters = nullptr;
    const Json* grid_metadata = nullptr;
    std::string status;
    std::string input_snapshot_hash;  // "" = none
    std::string grid_artifact_path;   // "" = none
    bool has_live_factor_grid = false;
};

// Recover previously stored component fingerprints, if present; nullopt for
// legacy tasks that only carry the monolithic input_snapshot_hash.
std::optional<FactorFingerprints> stored_fingerprints_from_task(
    const FactorTaskView& task);

// True if the task has live cache, an existing artifact path, or a truthy
// legacy inline grid. The artifact-path branch uses std::filesystem.
bool task_has_numerical_output(const FactorTaskView& task);

FactorDirtyState classify_factor_recompute(const FactorTaskView& task,
                                           const FactorFingerprints& current,
                                           bool force = false);

}  // namespace pwb::factor_host
