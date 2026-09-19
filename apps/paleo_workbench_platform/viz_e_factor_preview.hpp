// VIZ-E — factor/horizon surface preview compute (plan V6 presentation
// half): real mapping_kernel interpolation → SurfaceHost data with
// provenance (factor name / method / unit / CRS / statistics / source
// identity), contour lines via the viz_charts marching-squares kernel.
// Cancel/expiry runs through the product JobCenter (generation guard), not
// ad-hoc threads.
#pragma once

#include <QString>

#include <pwb/mapping/interpolator.hpp>
#include <pwb/viz_charts/marching_squares.hpp>

#include <cstdint>
#include <string>
#include <vector>

#include "viz_e_hosts.hpp"

namespace pwb::job {
class JobContext;
}

namespace pwb::viz_e {

// Input for a surface preview computed from real sample points (parsed from
// a horizon .dat asset, or produced by the factor_prepare worker closure).
struct FactorPreviewRequest {
    std::string asset_path;  // source asset identity (provenance)
    std::string asset_id;
    std::string factor_name = "horizon";
    std::string method = "idw";  // mapping_kernel vocabulary
    int grid_n = 50;
    // Declared metadata only — never inferred from coordinates (#1386
    // lesson; empty string = undeclared and surfaces as such).
    std::string crs;
    std::string unit;
    std::vector<pwb::mapping::SamplePoint> samples;
};

struct FactorPreviewOutcome {
    bool ok = false;
    QString error;                       // honest failure text (shown as-is)
    SurfaceHost::SurfaceData data;       // grid + levels + title + provenance
    pwb::mapping::GridStatistics statistics;
    // Contour polylines per level (marching-squares kernel, real values on
    // the same grid) for point-value spot checks in tests/consumers.
    std::vector<std::pair<double, std::vector<pwb::viz_charts::Polyline>>>
        contour_lines;
    std::uint64_t generation = 0;
};

// Bounded compute (grid ≤ 256² per the horizon budget) that observes the
// job's cancellation token between stages. Pure: no widgets touched.
FactorPreviewOutcome compute_factor_preview(const FactorPreviewRequest& request,
                                            pwb::job::JobContext& ctx);

// Six nice levels spanning the grid's finite value range (matches the
// geoviz surface preview's level cadence); empty when no finite values.
std::vector<double> preview_levels(double vmin, double vmax, int count = 6);

// ---------------------------------------------------------------------------
// ui_workers result → presentation adapters (the presentation端 of the
// contour_draft/factor_prepare workers). Both consume the REAL worker
// output structures — no recompute, metadata transits verbatim.
// ---------------------------------------------------------------------------

struct FactorTaskSlice;   // pwb::ui_workers (worker_common.hpp)
struct ContourDraftSlice; // pwb::ui_workers (contour_draft.hpp)

// A factor_prepare task result (grid + metadata) → surface presentation
// with provenance from the task's own fields (factor name/method/unit/CRS
// only when the task declared them — never guessed).
SurfaceHost::SurfaceData surface_data_from_factor_task(
    const std::vector<double>& grid_x, const std::vector<double>& grid_y,
    const std::vector<double>& grid_z, const std::string& factor_name,
    const std::string& method, const std::string& crs,
    const std::string& unit, const std::string& source_identity);

}  // namespace pwb::viz_e
