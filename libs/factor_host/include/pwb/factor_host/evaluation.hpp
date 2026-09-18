#pragma once

// pwb::factor_host — unified interpolation accuracy evaluation, a faithful
// C++ port of the pure leaves of
// paleo_workbench/workflow/interpolation_evaluation.py (CONV-08).
//
// Not ported (host / engine territory): recommend_interpolation_methods
// (constraint_capabilities matrix), kriging_leave_one_out /
// kriging_diagnostics (direct geoviz engine calls). The CRS half of the
// fail-closed context gate is injected (see CrsValidator) because Python
// leans on pyproj.
// Qt-free, Python-free, numpy-free.

#include <pwb/domain/json.hpp>

#include <functional>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

namespace pwb::factor_host {

using pwb::domain::Json;

inline constexpr int kDefaultCvFolds = 4;

struct EvaluationMetrics {
    std::optional<double> rmse;
    std::optional<double> mae;
    std::optional<double> bias;        // mean(observed - predicted)
    std::optional<double> r_squared;   // signed (#844)
    int n_samples = 0;
    int n_skipped = 0;

    // Throws std::invalid_argument with the Python message when the array
    // lengths differ. Non-finite pairs are counted as skipped, never silent.
    static EvaluationMetrics from_arrays(const std::vector<double>& observed,
                                         const std::vector<double>& predicted);

    Json to_dict() const;
};

// Bilinear sample of a row-major (len(grid_y) × len(grid_x)) grid at map
// coordinates; nullopt for off-grid queries, non-finite window, or nodata.
std::optional<double> bilinear_sample_grid(const std::vector<double>& grid_z,
                                           const std::vector<double>& grid_x,
                                           const std::vector<double>& grid_y,
                                           double px, double py);

// Signed R² over paired samples (never clamped; #844 convention).
double signed_r_squared(const std::vector<double>& observed,
                        const std::vector<double>& predicted);

// Deterministic spatial fold ids: round-robin by angle around the centroid.
// Throws std::invalid_argument for k < 2 ("k must be >= 2, got k") and for
// x/y size mismatch; empty input → empty vector.
std::vector<std::vector<int>> spatial_fold_assignment(
    const std::vector<double>& x, const std::vector<double>& y, int k);

// Fold indices grouping samples by well identity (well_id, falling back to
// name); unnamed samples are anonymous single-sample wells keyed
// __anonymous_{index}. Fold order = first-seen group order.
std::vector<std::vector<int>> leave_one_well_out_folds(const Json& points);

struct GridFrame {
    std::vector<double> grid_x;
    std::vector<double> grid_y;
    std::vector<double> grid_z;  // row-major (grid_y.size() × grid_x.size())
};

// Fold engines raise this to reproduce the Python detail text
// "fold {i} failed: {exc_type}: {message}".
class FoldEngineError : public std::runtime_error {
public:
    FoldEngineError(std::string exc_type, const std::string& message)
        : std::runtime_error(message), exc_type_(std::move(exc_type)) {}
    const std::string& exc_type() const noexcept { return exc_type_; }

private:
    std::string exc_type_;
};

struct CrossValidationReport {
    std::string method;
    std::string scheme;  // "kfold_surface" | "unavailable"
    int k = 0;
    EvaluationMetrics metrics;
    Json folds = Json::array();
    Json residuals = Json::array();
    std::string engine;
    std::string detail;

    Json to_dict() const;
};

// Spatial K-fold cross-validation of a surface engine. run_fold receives the
// training points (JSON array) and returns the production-shaped grid.
// Returns nullopt when evaluation cannot honestly run (scorable < k + 2).
// Points missing "x"/"y" throw std::invalid_argument (Python crashes too).
std::optional<CrossValidationReport> cross_validate_surface(
    const Json& points,
    const std::function<GridFrame(const Json& train)>& run_fold,
    int k = kDefaultCvFolds, std::string method_label = std::string(),
    std::string engine = std::string());

// In-sample surface residuals (anchoring fidelity — NOT cross-validated
// accuracy). Points missing "x"/"y" throw std::invalid_argument.
std::pair<Json, EvaluationMetrics> surface_residuals(
    const Json& points, const std::vector<double>& grid_x,
    const std::vector<double>& grid_y, const std::vector<double>& grid_z);

// GeoJSON-style point features for a residual layer (display concern).
Json residual_features(const Json& residuals);

using CrsValidator = std::function<bool(const std::string&)>;

struct RecommendationContext {
    std::vector<std::string> warnings;
    std::optional<std::string> gate;  // "unit_unknown" / "crs_invalid" / nullopt
};

// Fail-closed gates shared by every method entry (V8 M4). The CRS check is
// injected: an empty validator treats every non-empty CRS as invalid
// (fail-closed, pyproj-less default).
RecommendationContext validate_recommendation_context(
    const std::optional<std::string>& unit,
    const std::optional<std::string>& crs,
    CrsValidator crs_valid = nullptr);

// Shared recommendation adjudication (V8 M4): gate → disqualification →
// metric-best among eligible entries. Mutates entries with
// recommended/rationale; returns (entries, recommended_method).
std::pair<Json, std::optional<std::string>> adjudicate_recommendation(
    Json entries, const std::optional<std::string>& gate,
    const std::optional<std::vector<std::string>>& unknown_constraints,
    std::string_view scheme_caveat = std::string_view());

}  // namespace pwb::factor_host
