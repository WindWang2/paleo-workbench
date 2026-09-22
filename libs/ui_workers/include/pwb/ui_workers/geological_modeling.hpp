#pragma once

// UI-04 — geological_modeling_workers.py port (4 worker roles):
//   * GeologicalModelingWorker  — synthetic demo scene generation
//   * StratalWorker             — proportional-slice surfaces
//   * ExportWorker              — legacy GridSpec + V2 domain exports
//   * AdvisorWorker             — borehole/fault consistency checks
//
// None of these workers expose cooperative cancellation in Python (plain
// run() with progress signals and no cancel surface); the C++ specs keep
// that contract — they still run through job_runtime so scheduling /
// teardown semantics are uniform, and the JobContext token is checked at
// the same coarse points Python emits progress.

#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/geomodel/domain_contract.hpp>
#include <pwb/geomodel/export_contract.hpp>
#include <pwb/job_runtime/job_contract.hpp>
#include <pwb/ui_workers/geomodel_primitives.hpp>
#include <pwb/ui_workers/stratal.hpp>

namespace pwb::ui_workers {

using pwb::domain::Json;

// ---- GeologicalModelingWorker --------------------------------------------

// One named GL-ready mesh — {"name", "v", "f", "c"} in Python.
struct NamedGeom {
    std::string name;
    GeomPrimitive geom;
};

// Raw layer dict parity (kept as Json so the host can round-trip the
// exact Python record — lithology names are non-ASCII).
struct GeoModelingInput {
    std::string density;    // "低"/"中"/else → dim 40/80/120
    std::string algorithm;  // echoed back into the completed dict
    bool demo = true;
    // The Python worker sleeps between progress marks; the port emits
    // the same progress sequence (10,30,60,80,95,100) but the sleeps are
    // a no-op seam so tests do not stall. Default injects real sleeps.
    std::function<void(double seconds)> sleep_fn;
};

struct GeoModelingResult {
    std::vector<std::uint8_t> volume_data;  // dim³ uint8, (i,j,k) row-major
    int dim = 0;
    std::vector<NamedGeom> boreholes;
    std::vector<NamedGeom> tunnels;
    std::vector<NamedGeom> faults;
    Json bh_raw;      // the hardcoded borehole records (verbatim dicts)
    Json faults_raw;  // the hardcoded fault records
    bool demo = true;
    std::string source;     // "synthetic/demo" | "real_data"
    std::string algorithm;
};

GeoModelingResult run_geological_modeling(const GeoModelingInput& input,
                                        job::JobContext& ctx);

job::JobSpec make_geological_modeling_job_spec(
    GeoModelingInput input,
    std::function<void(const GeoModelingResult&)> on_done = {},
    std::function<void(const std::string&)> on_fail = {},
    std::function<void()> on_cancel = {});

// ---- StratalWorker --------------------------------------------------------

struct StratalInput {
    bool demo = false;
    std::vector<double> fractions = {0.25, 0.50, 0.75};
    std::array<std::size_t, 3> demo_shape = {16, 20, 32};
    // Demo-path noise seam (PCG64 parity deferred).
    DemoNoiseFn demo_noise_fn;
    // Non-demo path: the caller resolves the ms grids (.dat parsing /
    // interpretation artifacts stay engine-side). The seam returns
    // nullopt to mirror "survey/registration 不可用…" (Python
    // build_stratal_grids returning None). It also receives the
    // interpretation paths when set — the host picks which input to use.
    std::string top_path, bottom_path;
    std::string top_interp_path, bottom_interp_path;
    std::function<std::optional<std::pair<Grid2D, Grid2D>>(
        const StratalInput&, std::size_t n_i_prev, std::size_t n_x_prev,
        double stride_i, double stride_x, double dt_ms, double t0_ms,
        int sample_stride)>
        grids_fn;
    // Worker-only, bounded volume reader; returns amplitude maps aligned to surfaces.
    std::function<std::vector<Grid2D>(const std::vector<Grid2D>&,
                                      job::JobContext&)> amplitudes_fn;
    // Registration parameters for the default grid path (ms-grids
    // already aligned to preview indices when provided directly).
    std::size_t n_i_prev = 0, n_x_prev = 0, n_s_prev = 0;
    double stride_i = 1.0, stride_x = 1.0;
    double dt_ms = 1.0, t0_ms = 0.0;
    int sample_stride = 1;
    // When the caller already has preview-aligned sample-index grids it
    // may bypass grids_fn entirely.
    std::optional<std::pair<Grid2D, Grid2D>> preview_grids;
};

struct StratalResult {
    bool demo = false;
    std::optional<Volume3D> volume;  // demo path only
    std::vector<Grid2D> surfaces;
    std::vector<Grid2D> amplitudes;
    std::vector<std::string> labels;  // "k=%.2f" per fraction
};

// Python failure strings (parity for the two graceful-fail emits):
//   "survey/registration 不可用或体数据未就绪，无法对齐 horizon。"
//   "horizon 对全部倒转或无效，未生成切片。"
struct StratalSoftFail : std::runtime_error {
    using std::runtime_error::runtime_error;
};

StratalResult run_stratal(const StratalInput& input, job::JobContext& ctx);

job::JobSpec make_stratal_job_spec(
    StratalInput input,
    std::function<void(const StratalResult&)> on_done = {},
    std::function<void(const std::string&)> on_fail = {},
    std::function<void()> on_cancel = {});

// ---- ExportWorker ---------------------------------------------------------

// Legacy GridSpec (the Python dataclass slice).
struct GridSpecSlice {
    int nx = 0, ny = 0, nz = 0;
    double dx = 0, dy = 0, dz = 0;
};

struct ExportInput {
    std::string filename;
    std::string mode;  // flac3d | abaqus | obj | stl | vtp
    GridSpecSlice grid_spec;
    // V2 path inputs (volume/surface are the Python `self.volume` /
    // `self.surface`; presence switches to _run_v2).
    std::optional<pwb::geomodel::DomainObject> volume;
    std::optional<pwb::geomodel::DomainObject> surface;
    std::optional<pwb::geomodel::HorizonGrid> top;
    std::optional<pwb::geomodel::HorizonGrid> base;
    std::vector<std::pair<std::string, std::vector<double>>> point_data;
};

struct ExportResult {
    std::string filename;   // completed.emit(filename) parity
    // The export bytes + provenance sidecar — run_export persists them
    // to `filename` (Python exporters write inside the worker too), so
    // `written` is the record of what was written.
    pwb::geomodel::ExportWritten written;
};

// mode dispatch parity: legacy flac3d/abaqus over grid_spec when no V2
// object; otherwise the V2 exporters; unknown mode → ValueError text.
ExportResult run_export(const ExportInput& input, job::JobContext& ctx);

job::JobSpec make_export_job_spec(
    ExportInput input,
    std::function<void(const ExportResult&)> on_done = {},
    std::function<void(const std::string&)> on_fail = {},
    std::function<void()> on_cancel = {});

// ---- AdvisorWorker --------------------------------------------------------

// completed.emit(bh_report, fault_report) — reports stay Json (the same
// dicts the Python advisor returns; pwb::geomodel already owns the
// rules).
struct AdvisorInput {
    Json boreholes;  // list of BoreholeRecord/dict
    Json faults;     // list of FaultRecord/dict
};

struct AdvisorResult {
    Json bh_report;
    Json fault_report;
};

AdvisorResult run_advisor(const AdvisorInput& input, job::JobContext& ctx);

job::JobSpec make_advisor_job_spec(
    AdvisorInput input,
    std::function<void(const AdvisorResult&)> on_done = {},
    std::function<void(const std::string&)> on_fail = {},
    std::function<void()> on_cancel = {});

}  // namespace pwb::ui_workers
