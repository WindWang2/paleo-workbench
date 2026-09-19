#pragma once

// UI-04 — shared vocabulary for the page-worker cores.
//
// Every ported worker is a Qt-free callable: input slice (host-collected,
// never a live ProjectDocument) -> progress/cancel through pwb::job::JobContext
// plus typed hooks -> copyable output DTO carried in std::any. The
// collect->compute->apply split mirrors CONV-30: the GUI thread collects the
// slice, the worker computes, the GUI thread applies the result DTO.
//
// Error-text parity: workers that emitted failed("<PyClass>: <msg>")
// (f"{exc.__class__.__name__}: {exc}") keep that wire text via PyStyleError —
// exc.what() carries "Class: msg". Workers that emitted failed(str(exc))
// (integrity, stratal, the four geomodel workers) keep plain messages —
// run_plain() below strips the class prefix at the worker boundary.

#include <any>
#include <cmath>
#include <cstdint>
#include <exception>
#include <functional>
#include <map>
#include <optional>
#include <set>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <pwb/job_runtime/job_contract.hpp>

namespace pwb::ui_workers {

// ---------------------------------------------------------------------------
// Python-typed failure. what() is "<py_class>: <message>" — the exact string
// the Python failed(str) signal carried. py_message() is str(exc).
// ---------------------------------------------------------------------------
class PyStyleError : public std::runtime_error {
public:
    PyStyleError(std::string py_class, std::string message)
        : std::runtime_error(py_class + ": " + message),
          py_class_(std::move(py_class)),
          py_message_(std::move(message)) {}
    [[nodiscard]] const std::string& py_class() const noexcept {
        return py_class_;
    }
    [[nodiscard]] const std::string& py_message() const noexcept {
        return py_message_;
    }

private:
    std::string py_class_;
    std::string py_message_;
};

// Python ValueError parity.
struct PyValueError : PyStyleError {
    explicit PyValueError(std::string message)
        : PyStyleError("ValueError", std::move(message)) {}
};

// Python RuntimeError parity (engine/missing-capability failures).
struct PyRuntimeError : PyStyleError {
    explicit PyRuntimeError(std::string message)
        : PyStyleError("RuntimeError", std::move(message)) {}
};

// Python ImportError parity (optional engine/facade absent).
struct PyImportError : PyStyleError {
    explicit PyImportError(std::string message)
        : PyStyleError("ImportError", std::move(message)) {}
};

// A compute seam that has no real binding configured. Surfaces as the
// Python worker's honest failure text instead of silently fake results.
struct KernelUnavailable : PyStyleError {
    explicit KernelUnavailable(std::string what_is_missing)
        : PyStyleError("RuntimeError",
                       "kernel unavailable: " + std::move(what_is_missing)) {}
};

// Re-raise any non-PyStyle exception as the worker's failed text,
// duck-typing the std::exception family onto the closest Python class
// (invalid_argument->ValueError, out_of_range->IndexError,
// runtime_error->RuntimeError, filesystem/system_error->OSError,
// else "Exception") — parity of f"{exc.__class__.__name__}: {exc}".
[[noreturn]] void rethrow_as_py_error(const std::exception& exc);

// The exc.__class__.__name__ half of the mapping (no message) — used by
// soft-fail surfaces like VizAdapter.resolve's "解析失败: <class>".
[[nodiscard]] std::string py_error_class_name(
    const std::exception& exc);

// Run `body` translating failures into PyStyleError (worker-boundary wrap
// for the "Class: msg" workers). JobCancelled and PyStyleError pass through.
template <typename F>
decltype(auto) with_py_errors(F&& body) {
    try {
        return std::forward<F>(body)();
    } catch (const PyStyleError&) {
        throw;
    } catch (const job::JobCancelled&) {
        throw;
    } catch (const std::exception& exc) {
        rethrow_as_py_error(exc);
    }
}

// Run `body` translating failures so exc.what() is the PLAIN message —
// parity of failed(str(exc)) workers (integrity, stratal, geomodel).
// PyStyleError degrades to its py_message; other std::exceptions keep what().
template <typename F>
decltype(auto) with_plain_errors(F&& body) {
    try {
        return std::forward<F>(body)();
    } catch (const PyStyleError& exc) {
        throw std::runtime_error(exc.py_message());
    } catch (const job::JobCancelled&) {
        throw;
    }
}

// ---------------------------------------------------------------------------
// Python math helpers (frozen semantics).
// ---------------------------------------------------------------------------

// Python round(x, n) — round-half-even at the decimal digit.
double py_round(double value, int digits);

// Python math.isclose — rel_tol=1e-9, abs_tol=0.0 defaults.
bool py_isclose(double a, double b, double rel_tol = 1e-9,
                double abs_tol = 0.0) noexcept;

// np.linspace(lo, hi, n) — inclusive endpoints.
std::vector<double> np_linspace(double lo, double hi, std::size_t n);

// os.environ integer read with Python int()/strip() semantics; `fallback`
// when unset/unparseable.
int env_int(const char* name, int fallback);

// ---------------------------------------------------------------------------
// Grid / value containers (row-major, NaN = nodata like the numpy sources).
// ---------------------------------------------------------------------------

// 2-D float grid (rows x cols, row-major data[ r*cols + c ]).
struct Grid2D {
    std::size_t rows = 0;
    std::size_t cols = 0;
    std::vector<double> data;

    [[nodiscard]] double& at(std::size_t r, std::size_t c) {
        return data[r * cols + c];
    }
    [[nodiscard]] double at(std::size_t r, std::size_t c) const {
        return data[r * cols + c];
    }
    [[nodiscard]] bool empty() const { return data.empty(); }
};

// 3-D float volume (nI x nX x nS, data[i*nX*nS + x*nS + s]) — the seismic
// (inline, crossline, sample) convention.
struct Volume3D {
    std::size_t n_i = 0, n_x = 0, n_s = 0;
    std::vector<float> data;

    [[nodiscard]] float at(std::size_t i, std::size_t x, std::size_t s) const {
        return data[(i * n_x + x) * n_s + s];
    }
    [[nodiscard]] bool empty() const { return data.empty(); }
};

// ---------------------------------------------------------------------------
// Shared input slices (host-collected on the GUI thread).
// ---------------------------------------------------------------------------

// ResourceItem slice — the fields the workers read.
struct ResourceSlice {
    std::string id;
    std::string name;
    std::string path;
    std::string type;
    std::string format;
};

// VizRef slice (viz/models.py VizRef).
struct VizRefSlice {
    std::string kind;  // well_log | seismic | map | cross_well | engine_preview | prediction
    std::string id;
    std::string path;
    std::string label;
    std::string source;
    std::vector<std::string> related_ids;
};

// VizPayload slice — `well_log` is type-erased (the engine WellLogData
// equivalent lives behind the resolve/load seams).
struct VizPayloadSlice {
    std::string kind;  // well_log | seismic | map | message | ...
    std::string label;
    std::any well_log;
    std::vector<std::any> well_logs;
    std::vector<std::string> well_names;
    std::string seismic_path;
    std::string message;
    std::string warning;
};

// FactorMapTask slice — the union of fields the contour-draft and
// factor-prepare paths read (parameters stays a dict: the scheduler checks
// "sample_points" presence and "last_error"; the seam layer owns the rest).
struct FactorTaskSlice {
    std::string id;
    std::string name;
    std::string status;
    std::string target_horizon;
    std::string factor_type;
    std::string method;
    std::string source_kind;
    std::optional<int> seed;
    std::map<std::string, std::any> parameters;

    // The classify/stored-fingerprint path (interpolation_fingerprint.py)
    // reads these task attributes alongside `parameters`: grid_metadata is a
    // separate bag (its algorithm_parameters sub-dict feeds _get()), and the
    // two scalars drive the legacy-hash / missing-artifact branches of
    // classify_factor_recompute. Empty == absent attribute.
    std::map<std::string, std::any> grid_metadata;
    std::string input_snapshot_hash;
    std::string grid_artifact_path;

    // Resolved factor grid (factor_grid_result_for_task output collected
    // host-side): 1-D x/y coordinate axes + 2-D z. nullopt when the
    // artifact store has no usable grid (the legacy `parameters` grid_x /
    // grid_y / grid_z lists then apply, exactly like _grid_from_task).
    std::optional<std::vector<double>> grid_x;
    std::optional<std::vector<double>> grid_y;
    std::optional<Grid2D> grid_z;

    // Engine contours stored on the grid result (#928 refined isolines):
    // level-string -> list of (x,y) polylines, plus the levels they were
    // generated at (algorithm_parameters["contour_levels"]).
    using EngineContourLines =
        std::map<std::string, std::vector<std::vector<std::pair<double, double>>>>;
    std::optional<EngineContourLines> engine_contours;
    std::optional<std::vector<double>> stored_contour_levels;
};

// FactorTaskSlice::parameters helpers (Python dict.get semantics).
[[nodiscard]] bool param_has(const FactorTaskSlice& task,
                             const std::string& key);
[[nodiscard]] std::optional<std::string> param_str(const FactorTaskSlice& task,
                                                   const std::string& key);
[[nodiscard]] std::optional<double> param_double(const FactorTaskSlice& task,
                                                 const std::string& key);
[[nodiscard]] std::optional<int> param_int(const FactorTaskSlice& task,
                                           const std::string& key);
// Python truthiness of parameters[key] for the "sample_points" check:
// missing -> false; vector<any>/vector<array> -> non-empty; any other
// value -> true.
[[nodiscard]] bool param_truthy(const FactorTaskSlice& task,
                                const std::string& key);

// ---------------------------------------------------------------------------
// Path helpers — paleo_workbench.project.paths / VizAdapter._absolute_path /
// stratigraphy_correlation._resource_path ports.
// ---------------------------------------------------------------------------

// is_within_directory: resolve() both sides, descendant-or-equal test.
bool is_within_directory(const std::string& path,
                         const std::string& directory);

// VizAdapter._absolute_path parity: expanduser; existing file -> resolve();
// absolute -> bare candidate; else confined project_root join.
std::string absolute_resource_path(const std::string& path,
                                   const std::string& project_root);

// stratigraphy_correlation._resource_path parity: expanduser; file-or-
// absolute hit -> BARE candidate; else confined project_root join.
std::string resource_path(const std::string& path,
                          const std::string& project_root);

// Cooperative-checkpoint convenience — the geoviz CancellationToken
// `raise_if_cancelled` protocol mapped onto the JobContext token.
inline void raise_if_cancelled(const job::JobContext& ctx) {
    ctx.check_cancelled();
}

}  // namespace pwb::ui_workers
