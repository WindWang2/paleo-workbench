#pragma once

// UI-04 — geoviz_seismic.stratal + paleo_workbench.viz.stratal_adapter
// pure-math port. The heavy engine seams (HorizonParser .dat parsing,
// interpretation-artifact IO, SEGY volume access, PCG64 demo noise) stay
// behind injected callables; the proportional-surface / slice /
// resample math is ported exactly.
//
// Grid convention matches numpy row-major: Grid2D values[i][x] is
// (nI × nX); Volume3D values[i][x][s] is (nI × nX × nS) flattened
// row-major. NaN marks absent picks and propagates like numpy.

#include <array>
#include <cstdint>
#include <functional>
#include <optional>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

#include <pwb/ui_workers/worker_common.hpp>

namespace pwb::ui_workers {

// Grid2D / Volume3D come from worker_common.hpp (row-major, NaN =
// nodata) — Grid2D values[i][x] is (nI × nX); Volume3D data[i][x][s] is
// (nI × nX × nS) flattened row-major.

// Grid2D filled with a constant (the np.full equivalent).
Grid2D grid2d_filled(std::size_t rows, std::size_t cols, double v);

enum class StratalMode { kRms, kMean, kMax };

// validate_horizon_pair — throws std::invalid_argument on shape mismatch
// (Python ValueError). volume_shape==nullptr skips the [0,nS) clip.
std::vector<bool> validate_horizon_pair(
    const Grid2D& top, const Grid2D& bottom,
    const std::size_t* n_samples = nullptr);

// build_proportional_surfaces — fractions are clipped to [0,1]; each
// surface = top + k*(bottom-top), clamped into [min,max](top,bottom)
// exactly like np.clip (NaN propagates). One output grid per fraction.
std::vector<Grid2D> build_proportional_surfaces(
    const Grid2D& top, const Grid2D& bottom,
    const std::vector<double>& fractions);

// extract_stratal_slice — order=1 map_coordinates degenerates to 1-D
// linear interpolation along the sample axis (i/x are integer coords).
// window==0 → single interpolated sample; window>0 → rms/mean/max over
// the in-bounds offsets; all-NaN window → NaN (nanmax/nanmean parity).
// `order0` selects nearest-sample behaviour (Python order=0).
Grid2D extract_stratal_slice(const Volume3D& volume, const Grid2D& surface,
                             int window = 0,
                             StratalMode mode = StratalMode::kRms,
                             bool order0 = false);

// stratal_slice_volume — validate→mask→surfaces→extract; returns the
// attribute maps (one per fraction) and, when requested, the surfaces.
std::vector<Grid2D> stratal_slice_volume(
    const Volume3D& volume, const Grid2D& top, const Grid2D& bottom,
    const std::vector<double>& fractions, int window = 0,
    StratalMode mode = StratalMode::kRms, bool order0 = false,
    std::vector<Grid2D>* surfaces_out = nullptr);

// ---- stratal_adapter ports ------------------------------------------------

// ms_to_preview_sample_index — (ms - t0)/dt/stride; dt<=0 degrades to 1.
Grid2D ms_to_preview_sample_index(const Grid2D& ms, double dt_ms,
                                  double t0_ms, int sample_stride = 1);

// _ms_grids_to_preview_sample_indices — bilinear map_coordinates
// (order=1, mode="nearest") of the full-survey ms grids at preview
// coordinates ii*stride_i / xx*stride_x, then ms→preview-sample. The
// scene/registration lookup is replaced by direct strides+grid inputs.
std::pair<Grid2D, Grid2D> ms_grids_to_preview_sample_indices(
    const Grid2D& top_ms, const Grid2D& bot_ms, std::size_t n_i_prev,
    std::size_t n_x_prev, double stride_i, double stride_x, double dt_ms,
    double t0_ms, int sample_stride);

// build_stratal_surfaces — returns (surfaces, [top_c, bot_c]) or
// nullopt when every cell is invalid (Python returns None → worker
// emits the "horizon 对全部倒转或无效" failure).
std::optional<std::pair<std::vector<Grid2D>, std::array<Grid2D, 2>>>
build_stratal_surfaces(const Grid2D& top_sidx, const Grid2D& bot_sidx,
                       std::size_t n_samples,
                       const std::vector<double>& fractions);

// make_demo_stratal_grids — deterministic synthetic volume + bracketing
// horizons. The reflector math is ported exactly; the numpy
// default_rng(seed).standard_normal noise term rides an injected seam
// (PCG64 bit-parity is deliberately deferred — see findings ledger).
// `out` receives n_i*n_x*n_s raw float64 samples (the *0.05 scaling and
// f32 cast happen inside, matching `(... * 0.05).astype(np.float32)`);
// a null noise_fn = zeros.
using DemoNoiseFn = std::function<void(std::vector<double>& out)>;

Volume3D make_synthetic_demo_volume(std::size_t n_i, std::size_t n_x,
                                    std::size_t n_t, int n_reflectors = 3,
                                    const DemoNoiseFn& noise_fn = {});

std::tuple<Volume3D, Grid2D, Grid2D> make_demo_stratal_grids(
    std::size_t n_i = 16, std::size_t n_x = 20, std::size_t n_t = 32,
    const DemoNoiseFn& noise_fn = {});

}  // namespace pwb::ui_workers
