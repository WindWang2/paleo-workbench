#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include <vector>
#include <cmath>
#include <algorithm>
#include <limits>

namespace py = pybind11;

// OpenMP parallel regions are only worthwhile above a work-size threshold:
// team spawn/join barriers cost tens of microseconds per region regardless of
// workload, so on many-core hosts a 16K-260K element slice (i.e. everything up
// to a 512^3 slice) ran ~130x SLOWER with the default team size than serially
// (issue #384). Regions at or below the threshold execute serially through the
// `if` clause (no team is spawned), keeping the per-call overhead flat for all
// interactive slice sizes; only very large slices (> 524,288 elements, i.e.
// 1024^3+ volumes) parallelise, where a normal host's speedup outweighs the
// region cost.
static constexpr size_t kOmpMinParallelElems = 1u << 19;  // 524,288

// Fast 2D Slice Extraction from 3D Volume
py::array_t<float> fast_slice_extract(py::array_t<float, py::array::c_style | py::array::forcecast> input, int axis, int index) {
    auto buf = input.request();
    if (buf.ndim != 3) {
        throw std::runtime_error("Input volume must be 3D");
    }

    size_t dim0 = buf.shape[0];
    size_t dim1 = buf.shape[1];
    size_t dim2 = buf.shape[2];
    const float* ptr = static_cast<const float*>(buf.ptr);

    int ax = (axis % 3 + 3) % 3;
    if (index < 0) {
        throw std::out_of_range("slice index is negative");
    }
    if (ax == 0) {
        if (dim0 == 0) {
            throw std::out_of_range("cannot slice axis 0 of an empty volume");
        }
        if (static_cast<size_t>(index) >= dim0) {
            throw std::out_of_range("slice index out of range for axis 0");
        }
        size_t idx = static_cast<size_t>(index);
        auto result = py::array_t<float>({dim1, dim2});
        auto r_buf = result.request();
        float* r_ptr = static_cast<float*>(r_buf.ptr);
        size_t slice_size = dim1 * dim2;
        {
            py::gil_scoped_release release;
            std::copy(ptr + idx * slice_size, ptr + (idx + 1) * slice_size, r_ptr);
        }
        return result;
    } else if (ax == 1) {
        if (dim1 == 0) {
            throw std::out_of_range("cannot slice axis 1 of an empty volume");
        }
        if (static_cast<size_t>(index) >= dim1) {
            throw std::out_of_range("slice index out of range for axis 1");
        }
        size_t idx = static_cast<size_t>(index);
        auto result = py::array_t<float>({dim0, dim2});
        auto r_buf = result.request();
        float* r_ptr = static_cast<float*>(r_buf.ptr);
        {
            py::gil_scoped_release release;
            #if defined(_OPENMP)
            #pragma omp parallel for schedule(static) if(dim0 * dim2 > kOmpMinParallelElems)
            #endif
            for (size_t i = 0; i < dim0; ++i) {
                size_t src_offset = i * (dim1 * dim2) + idx * dim2;
                size_t dst_offset = i * dim2;
                std::copy(ptr + src_offset, ptr + src_offset + dim2, r_ptr + dst_offset);
            }
        }
        return result;
    } else {
        if (dim2 == 0) {
            throw std::out_of_range("cannot slice axis 2 of an empty volume");
        }
        if (static_cast<size_t>(index) >= dim2) {
            throw std::out_of_range("slice index out of range for axis 2");
        }
        size_t idx = static_cast<size_t>(index);
        auto result = py::array_t<float>({dim0, dim1});
        auto r_buf = result.request();
        float* r_ptr = static_cast<float*>(r_buf.ptr);
        {
            py::gil_scoped_release release;
            size_t total_elem = dim0 * dim1;
            #if defined(_OPENMP)
            #pragma omp parallel for schedule(static) if(total_elem > kOmpMinParallelElems)
            #endif
            for (size_t k = 0; k < total_elem; ++k) {
#if defined(__GNUC__) || defined(__clang__)
                __builtin_prefetch(&ptr[(k + 16) * dim2 + idx], 0, 0);
#endif
                r_ptr[k] = ptr[k * dim2 + idx];
            }
        }
        return result;
    }
}

// Fast 2D Slice Extraction directly into normalized uint8 Indexed8 array
py::tuple fast_slice_to_indexed8(py::array_t<float, py::array::c_style | py::array::forcecast> input, int axis, int index) {
    auto buf = input.request();
    if (buf.ndim != 3) {
        throw std::runtime_error("Input volume must be 3D");
    }

    size_t dim0 = buf.shape[0];
    size_t dim1 = buf.shape[1];
    size_t dim2 = buf.shape[2];
    const float* ptr = static_cast<const float*>(buf.ptr);

    int ax = (axis % 3 + 3) % 3;
    if (index < 0) {
        throw std::out_of_range("slice index is negative");
    }

    size_t rows = 0, cols = 0;
    if (ax == 0) {
        if (dim0 == 0) throw std::out_of_range("cannot slice axis 0 of an empty volume");
        if (static_cast<size_t>(index) >= dim0) throw std::out_of_range("slice index out of range for axis 0");
        rows = dim1; cols = dim2;
    } else if (ax == 1) {
        if (dim1 == 0) throw std::out_of_range("cannot slice axis 1 of an empty volume");
        if (static_cast<size_t>(index) >= dim1) throw std::out_of_range("slice index out of range for axis 1");
        rows = dim0; cols = dim2;
    } else {
        if (dim2 == 0) throw std::out_of_range("cannot slice axis 2 of an empty volume");
        if (static_cast<size_t>(index) >= dim2) throw std::out_of_range("slice index out of range for axis 2");
        rows = dim0; cols = dim1;
    }

    size_t idx = static_cast<size_t>(index);
    size_t total = rows * cols;
    auto u8_result = py::array_t<uint8_t>({rows, cols});
    auto u8_buf = u8_result.request();
    uint8_t* dst = static_cast<uint8_t*>(u8_buf.ptr);

    float min_val = std::numeric_limits<float>::infinity();
    float max_val = -std::numeric_limits<float>::infinity();

    {
        py::gil_scoped_release release;

        if (ax == 0) {
            const float* src = ptr + idx * (dim1 * dim2);
            #if defined(_OPENMP)
            #pragma omp parallel for reduction(min:min_val) reduction(max:max_val) schedule(static) if(total > kOmpMinParallelElems)
            #endif
            for (size_t i = 0; i < total; ++i) {
                float v = src[i];
                if (std::isnan(v) || std::isinf(v)) continue;
                if (v < min_val) min_val = v;
                if (v > max_val) max_val = v;
            }

            if (min_val >= max_val || std::isinf(min_val) || std::isinf(max_val)) {
                std::fill(dst, dst + total, static_cast<uint8_t>(0));
            } else {
                float inv_range = 255.0f / (max_val - min_val);
                #if defined(_OPENMP)
                #pragma omp parallel for schedule(static) if(total > kOmpMinParallelElems)
                #endif
                for (size_t i = 0; i < total; ++i) {
                    float v = src[i];
                    if (std::isnan(v) || std::isinf(v)) {
                        dst[i] = 0;
                    } else {
                        float norm = (v - min_val) * inv_range;
                        dst[i] = static_cast<uint8_t>(std::max(0.0f, std::min(255.0f, norm)));
                    }
                }
            }
        } else if (ax == 1) {
            #if defined(_OPENMP)
            #pragma omp parallel for reduction(min:min_val) reduction(max:max_val) schedule(static) if(total > kOmpMinParallelElems)
            #endif
            for (size_t i = 0; i < dim0; ++i) {
                size_t src_offset = i * (dim1 * dim2) + idx * dim2;
                for (size_t j = 0; j < dim2; ++j) {
                    float v = ptr[src_offset + j];
                    if (std::isnan(v) || std::isinf(v)) continue;
                    if (v < min_val) min_val = v;
                    if (v > max_val) max_val = v;
                }
            }

            if (min_val >= max_val || std::isinf(min_val) || std::isinf(max_val)) {
                std::fill(dst, dst + total, static_cast<uint8_t>(0));
            } else {
                float inv_range = 255.0f / (max_val - min_val);
                #if defined(_OPENMP)
                #pragma omp parallel for schedule(static) if(total > kOmpMinParallelElems)
                #endif
                for (size_t i = 0; i < dim0; ++i) {
                    size_t src_offset = i * (dim1 * dim2) + idx * dim2;
                    size_t dst_offset = i * dim2;
                    for (size_t j = 0; j < dim2; ++j) {
                        float v = ptr[src_offset + j];
                        if (std::isnan(v) || std::isinf(v)) {
                            dst[dst_offset + j] = 0;
                        } else {
                            float norm = (v - min_val) * inv_range;
                            dst[dst_offset + j] = static_cast<uint8_t>(std::max(0.0f, std::min(255.0f, norm)));
                        }
                    }
                }
            }
        } else {
            // axis == 2 (Time slice)
            // Strided min/max sample pass to avoid double full-volume cache miss
            size_t step = (total > 65536) ? 4 : 1;
            #if defined(_OPENMP)
            #pragma omp parallel for reduction(min:min_val) reduction(max:max_val) schedule(static) if(total > kOmpMinParallelElems)
            #endif
            for (size_t k = 0; k < total; k += step) {
#if defined(__GNUC__) || defined(__clang__)
                __builtin_prefetch(&ptr[(k + 16 * step) * dim2 + idx], 0, 0);
#endif
                float v = ptr[k * dim2 + idx];
                if (std::isnan(v) || std::isinf(v)) continue;
                if (v < min_val) min_val = v;
                if (v > max_val) max_val = v;
            }

            if (min_val >= max_val || std::isinf(min_val) || std::isinf(max_val)) {
                std::fill(dst, dst + total, static_cast<uint8_t>(0));
            } else {
                float inv_range = 255.0f / (max_val - min_val);
                #if defined(_OPENMP)
                #pragma omp parallel for schedule(static) if(total > kOmpMinParallelElems)
                #endif
                for (size_t k = 0; k < total; ++k) {
#if defined(__GNUC__) || defined(__clang__)
                    __builtin_prefetch(&ptr[(k + 16) * dim2 + idx], 0, 0);
#endif
                    float v = ptr[k * dim2 + idx];
                    if (std::isnan(v) || std::isinf(v)) {
                        dst[k] = 0;
                    } else {
                        float norm = (v - min_val) * inv_range;
                        dst[k] = static_cast<uint8_t>(std::max(0.0f, std::min(255.0f, norm)));
                    }
                }
            }
        }
    }

    if (min_val >= max_val || std::isinf(min_val) || std::isinf(max_val)) {
        return py::make_tuple(u8_result, 0.0f, 0.0f);
    }
    return py::make_tuple(u8_result, min_val, max_val);
}

// Fast 3D Volume Resampling
py::array_t<float> fast_resample_volume_3d(py::array_t<float, py::array::c_style | py::array::forcecast> input, py::tuple target_shape) {
    auto buf = input.request();
    if (buf.ndim != 3) {
        throw std::runtime_error("Input volume must be 3D");
    }

    size_t s0 = buf.shape[0];
    size_t s1 = buf.shape[1];
    size_t s2 = buf.shape[2];
    const float* src = static_cast<const float*>(buf.ptr);

    // Reject empty source volumes: otherwise std::min(s0-1, ...) underflows
    // size_t to SIZE_MAX and the read index goes far out of bounds. Also
    // validate target_shape: a negative element (e.g. -1) casts to SIZE_MAX
    // and py::array_t throws std::bad_alloc / length_error instead of a
    // clean error.
    if (s0 == 0 || s1 == 0 || s2 == 0) {
        throw std::invalid_argument("cannot resample a volume with a zero-sized dimension");
    }
    if (target_shape.size() != 3) {
        throw std::invalid_argument("target_shape must have exactly 3 elements");
    }
    // Cast through py::ssize_t (signed) first so negatives are visible.
    py::ssize_t st0 = target_shape[0].cast<py::ssize_t>();
    py::ssize_t st1 = target_shape[1].cast<py::ssize_t>();
    py::ssize_t st2 = target_shape[2].cast<py::ssize_t>();
    if (st0 <= 0 || st1 <= 0 || st2 <= 0) {
        throw std::invalid_argument("target_shape elements must all be positive");
    }
    size_t t0 = static_cast<size_t>(st0);
    size_t t1 = static_cast<size_t>(st1);
    size_t t2 = static_cast<size_t>(st2);

    auto result = py::array_t<float>({t0, t1, t2});
    auto r_buf = result.request();
    float* dst = static_cast<float*>(r_buf.ptr);

    // Peak-preserving stride-block decimation (issue #419): the old nearest
    // grid-point sampling dropped any thin reflection between stride samples,
    // so LOD previews lost events that the native traces still contain. Each
    // target cell now aggregates its source stride block [lo, hi] per axis
    // (hi of the last target forced to the source edge, since float32
    // rounding of t*step can land below s) and keeps the sample with the
    // largest |value|, sign preserved. A block containing any NaN is
    // conservatively NaN, matching the Python fallback and the NaN semantics
    // of the other kernels in this module. Blocks are contiguous and cover
    // the whole source; upsampling (step < 1) yields single-sample blocks
    // (the old nearest sample), so identity resampling is unchanged.
    float step0 = static_cast<float>(s0) / static_cast<float>(std::max<size_t>(1, t0));
    float step1 = static_cast<float>(s1) / static_cast<float>(std::max<size_t>(1, t1));
    float step2 = static_cast<float>(s2) / static_cast<float>(std::max<size_t>(1, t2));

    auto block_bounds = [](size_t s, size_t t, float step, std::vector<size_t>& lo, std::vector<size_t>& hi) {
        lo.resize(t);
        hi.resize(t);
        for (size_t i = 0; i < t; ++i) {
            lo[i] = static_cast<size_t>(i * step);
            if (i + 1 == t) {
                hi[i] = s - 1;
            } else {
                // Guarded decrement: trunc((i+1)*step) can be 0 when
                // upsampling (step < 1); size_t underflow would read OOB.
                size_t next = static_cast<size_t>((i + 1) * step);
                hi[i] = (next > 0) ? next - 1 : 0;
            }
            if (hi[i] < lo[i]) hi[i] = lo[i];  // upsampling: single sample
        }
    };
    std::vector<size_t> lo0, hi0, lo1, hi1, lo2, hi2;
    block_bounds(s0, t0, step0, lo0, hi0);
    block_bounds(s1, t1, step1, lo1, hi1);
    block_bounds(s2, t2, step2, lo2, hi2);

    const float nan = std::numeric_limits<float>::quiet_NaN();

    {
        py::gil_scoped_release release;
        for (size_t i = 0; i < t0; ++i) {
            for (size_t j = 0; j < t1; ++j) {
                size_t dst_base = (i * t1 + j) * t2;
                for (size_t k = 0; k < t2; ++k) {
                    float best = 0.0f;
                    float best_abs = 0.0f;
                    bool block_nan = false;
                    for (size_t si = lo0[i]; si <= hi0[i]; ++si) {
                        size_t row_base = si * (s1 * s2);
                        for (size_t sj = lo1[j]; sj <= hi1[j]; ++sj) {
                            size_t col_base = row_base + sj * s2;
                            for (size_t sk = lo2[k]; sk <= hi2[k]; ++sk) {
                                float v = src[col_base + sk];
                                if (std::isnan(v)) {
                                    block_nan = true;
                                    break;
                                }
                                float a = std::fabs(v);
                                if (a > best_abs) {
                                    best_abs = a;
                                    best = v;
                                }
                            }
                            if (block_nan) break;
                        }
                        if (block_nan) break;
                    }
                    dst[dst_base + k] = block_nan ? nan : best;
                }
            }
        }
    }

    return result;
}

// 3D Coherence Attribute Calculation
py::array_t<float> compute_coherence_3d(py::array_t<float, py::array::c_style | py::array::forcecast> input, int inline_window, int crossline_window, int sample_window) {
    auto buf = input.request();
    if (buf.ndim != 3) {
        throw std::runtime_error("Input volume must be 3D");
    }

    size_t ni = buf.shape[0];
    size_t nx = buf.shape[1];
    size_t nt = buf.shape[2];
    const float* src = static_cast<const float*>(buf.ptr);

    // Validate window parameters: negative/zero windows produced OOB reads
    // and writes (half = w/2 went negative -> negative int -> size_t index)
    // and even windows were silently floored to an effective odd window.
    // The algorithm assumes odd windows; reject anything else so caller bugs
    // surface instead of silently corrupting the output.
    auto validate_window = [](int w, const char* name) {
        if (w <= 0) {
            throw std::invalid_argument(
                std::string(name) + " must be a positive odd integer (got " + std::to_string(w) + ")");
        }
        if (w % 2 == 0) {
            throw std::invalid_argument(
                std::string(name) + " must be odd (got " + std::to_string(w) +
                "); even windows are not supported");
        }
    };
    validate_window(inline_window, "inline_window");
    validate_window(crossline_window, "crossline_window");
    validate_window(sample_window, "sample_window");

    auto result = py::array_t<float>({ni, nx, nt});
    auto r_buf = result.request();
    float* dst = static_cast<float*>(r_buf.ptr);
    std::fill(dst, dst + ni * nx * nt, 1.0f);

    if (ni == 0 || nx == 0 || nt == 0) {
        // Degenerate volume: the coherence default (1.0) is already filled.
        // Returning here avoids `nt - 1` underflowing to SIZE_MAX below, which
        // indexed the empty mean_sq/sum_sq vectors (segfault).
        return result;
    }

    // size_t loop variables avoid the int->size_t sign-conversion hazard at
    // extremely large dims (review M2) and keep the running-sum window math
    // in unsigned space consistently.
    size_t half_i = static_cast<size_t>(inline_window / 2);
    size_t half_x = static_cast<size_t>(crossline_window / 2);
    size_t half_t = static_cast<size_t>(sample_window / 2);
    double n_spatial = static_cast<double>((2 * half_i + 1) * (2 * half_x + 1));

    std::vector<double> mean_sq(nt);
    std::vector<double> sum_sq(nt);

    {
        py::gil_scoped_release release;
        // Iterate in size_t throughout: the outer-loop guards
        // (i < ni - half_i etc.) now use unsigned arithmetic, which is
        // correct for any dim size (no int overflow for huge volumes — M2).
        // half_* are validated small positives, so ni - half_i does not
        // underflow as long as ni >= 1 (guaranteed: a 0-dim volume has no
        // slices to iterate, and the loop body is simply skipped).
        for (size_t i = half_i; i + half_i < ni; ++i) {
            for (size_t j = half_x; j + half_x < nx; ++j) {
                // Per-sample spatial statistics for this trace column (computed once).
                for (size_t k = 0; k < nt; ++k) {
                    double trace_sum = 0.0;
                    double trace_sq_sum = 0.0;
                    for (size_t di = 0; di <= 2 * half_i; ++di) {
                        size_t ii = i + di - half_i;  // spans [i-half_i, i+half_i]
                        for (size_t dj = 0; dj <= 2 * half_x; ++dj) {
                            size_t jj = j + dj - half_x;  // spans [j-half_x, j+half_x]
                            float v = src[ii * (nx * nt) + jj * nt + k];
                            trace_sum += v;
                            trace_sq_sum += v * v;
                        }
                    }
                    double mean_val = trace_sum / n_spatial;
                    mean_sq[k] = mean_val * mean_val;
                    sum_sq[k] = trace_sq_sum;
                }

                // Running-sum over the clamped vertical window [k0, k1].
                // NaN safety (issue #385): a NaN sample makes run_num/run_den
                // NaN, and NaN - x == NaN, so the incremental updates can never
                // flush it once the sample leaves the window. Track how many
                // NaN samples the window currently contains and, when the last
                // one exits, rebuild the window sums from scratch to recover.
                size_t k0 = 0;
                size_t k1 = std::min(nt - 1, half_t);
                double run_num = 0.0;
                double run_den = 0.0;
                size_t nan_in_window = 0;
                for (size_t k = k0; k <= k1; ++k) {
                    run_num += mean_sq[k];
                    run_den += sum_sq[k];
                    if (std::isnan(mean_sq[k])) ++nan_in_window;
                }
                for (size_t k = 0; k < nt; ++k) {
                    double den = run_den / static_cast<double>(k1 - k0 + 1) + 1e-12;
                    // NaN propagates to 0.0 through the std::min/std::max clamp
                    // chain whenever the window overlaps a NaN sample, matching
                    // the Python fallback's per-window recompute semantics.
                    float coh_val = static_cast<float>(std::min(1.0, std::max(0.0, run_num / den)));
                    dst[i * (nx * nt) + j * nt + k] = coh_val;

                    // Advance window for k+1.
                    if (k + 1 < nt) {
                        size_t new_lo = (k + 1 >= half_t) ? k + 1 - half_t : 0;
                        size_t new_hi = std::min(nt - 1, k + 1 + half_t);
                        while (k1 < new_hi) {
                            ++k1;
                            run_num += mean_sq[k1];
                            run_den += sum_sq[k1];
                            if (std::isnan(mean_sq[k1])) ++nan_in_window;
                        }
                        while (k0 < new_lo) {
                            if (std::isnan(mean_sq[k0])) --nan_in_window;
                            run_num -= mean_sq[k0];
                            run_den -= sum_sq[k0];
                            ++k0;
                        }
                        if (nan_in_window == 0 && std::isnan(run_num)) {
                            // The window is NaN-free again but the accumulators
                            // were poisoned; rebuild them from the window data.
                            run_num = 0.0;
                            run_den = 0.0;
                            for (size_t kk = k0; kk <= k1; ++kk) {
                                run_num += mean_sq[kk];
                                run_den += sum_sq[kk];
                            }
                        }
                    }
                }
            }
        }
    }
    return result;
}

// 3D Isosurface Mesh Extraction via Marching Tetrahedra.
// Each cube is split into 6 tetrahedra around the body diagonal corner0->corner7.
// The face diagonals of this decomposition are consistent between axis-aligned
// neighbour cubes, so the resulting mesh is watertight by construction.
// Corner index layout: corner n -> offset (n&1, (n>>1)&1, (n>>2)&1).
py::tuple marching_cubes_3d(py::array_t<float, py::array::c_style | py::array::forcecast> input, float isovalue) {
    auto buf = input.request();
    if (buf.ndim != 3) {
        throw std::runtime_error("Input volume must be 3D");
    }

    size_t ni = buf.shape[0];
    size_t nx = buf.shape[1];
    size_t nt = buf.shape[2];
    const float* src = static_cast<const float*>(buf.ptr);

    // Grid points whose value equals the isovalue exactly would make cut edges
    // land exactly on corners, producing degenerate (zero-area) triangles and
    // non-manifold pinching (several triangle fans touching at one point).
    // Nudge such values slightly inside so every cut lands strictly inside an
    // edge; the shift (~1e-3) is far below any geometric tolerance. A grid
    // point exactly on the isovalue is therefore classified as *inside*
    // (value becomes isovalue + eps); the classification is consistent across
    // neighbouring cubes (same source value -> same nudge) so watertightness
    // holds. (cpp-core-review M6.)
    const float eps = 1e-3f * (std::fabs(isovalue) + 1.0f);

    static const int TETS[6][4] = {
        {0, 1, 3, 7}, {0, 1, 5, 7}, {0, 4, 5, 7},
        {0, 4, 6, 7}, {0, 2, 6, 7}, {0, 2, 3, 7},
    };
    static const int TET_EDGES[6][2] = {
        {0, 1}, {0, 2}, {0, 3}, {1, 2}, {1, 3}, {2, 3},
    };

    std::vector<float> verts;
    std::vector<int> faces;

    {
        py::gil_scoped_release release;
        for (size_t i = 0; i + 1 < ni; ++i) {
            for (size_t j = 0; j + 1 < nx; ++j) {
                for (size_t k = 0; k + 1 < nt; ++k) {
                    float cv[8];
                    float cp[8][3];
                    bool cube_has_nan = false;
                    for (int c = 0; c < 8; ++c) {
                        size_t ci = i + (c & 1);
                        size_t cj = j + ((c >> 1) & 1);
                        size_t ck = k + ((c >> 2) & 1);
                        float v = src[ci * (nx * nt) + cj * nt + ck];
                        // NaN voxels: a cube touching missing data has
                        // undefined inside/outside at those corners, and the
                        // edge interpolation t = (iso-cv[ca])/(cv[cb]-cv[ca])
                        // would go NaN and poison up to 8 neighbouring cubes'
                        // triangles (cpp-core-review I2). Skip the whole cube
                        // — the surface simply has a hole where data is
                        // missing, rather than emitting NaN vertices.
                        // Non-finite includes ±Inf: an +Inf corner classifies
                        // as inside, and Inf/Inf interpolation still yields
                        // NaN vertices (audit I5).
                        if (!std::isfinite(v)) {
                            cube_has_nan = true;
                            break;
                        }
                        cv[c] = v;
                        if (cv[c] == isovalue) cv[c] = isovalue + eps;
                        cp[c][0] = static_cast<float>(ci);
                        cp[c][1] = static_cast<float>(cj);
                        cp[c][2] = static_cast<float>(ck);
                    }
                    if (cube_has_nan) continue;
                    int cube_mask = 0;
                    for (int c = 0; c < 8; ++c) {
                        if (cv[c] >= isovalue) cube_mask |= (1 << c);
                    }
                    if (cube_mask == 0 || cube_mask == 0xFF) continue;

                    for (const auto& tet : TETS) {
                        int tmask = 0;
                        for (int c = 0; c < 4; ++c) {
                            if (cube_mask & (1 << tet[c])) tmask |= (1 << c);
                        }
                        if (tmask == 0 || tmask == 0xF) continue;

                        // Interpolated intersection point per cut edge.
                        float pt[6][3];
                        bool cut[6] = {};
                        for (int e = 0; e < 6; ++e) {
                            int a = TET_EDGES[e][0];
                            int b = TET_EDGES[e][1];
                            bool ina = (tmask >> a) & 1;
                            bool inb = (tmask >> b) & 1;
                            if (ina == inb) continue;
                            int ca = tet[a], cb = tet[b];
                            float t = (isovalue - cv[ca]) / (cv[cb] - cv[ca]);
                            for (int d = 0; d < 3; ++d) {
                                pt[e][d] = cp[ca][d] + t * (cp[cb][d] - cp[ca][d]);
                            }
                            cut[e] = true;
                        }

                        // Centroid of inside corners (for outward orientation).
                        float ci[3] = {0.0f, 0.0f, 0.0f};
                        int n_inside = 0;
                        for (int c = 0; c < 4; ++c) {
                            if ((tmask >> c) & 1) {
                                ++n_inside;
                                for (int d = 0; d < 3; ++d) ci[d] += cp[tet[c]][d];
                            }
                        }
                        for (int d = 0; d < 3; ++d) ci[d] /= n_inside;

                        // Collect cut points in a deterministic order.
                        int tri_src[4];
                        int nq = 0;
                        if (n_inside == 2) {
                            // Quad: inside pair (a,b), outside pair (c,d) ->
                            // cycle p(a-c), p(a-d), p(b-d), p(b-c).
                            int ins[2], out[2], ni_ = 0, no_ = 0;
                            for (int c = 0; c < 4; ++c) {
                                if ((tmask >> c) & 1) ins[ni_++] = c; else out[no_++] = c;
                            }
                            auto edge_idx = [&](int x, int y) {
                                for (int e = 0; e < 6; ++e) {
                                    if ((TET_EDGES[e][0] == x && TET_EDGES[e][1] == y) ||
                                        (TET_EDGES[e][0] == y && TET_EDGES[e][1] == x)) return e;
                                }
                                return -1;
                            };
                            tri_src[0] = edge_idx(ins[0], out[0]);
                            tri_src[1] = edge_idx(ins[0], out[1]);
                            tri_src[2] = edge_idx(ins[1], out[1]);
                            tri_src[3] = edge_idx(ins[1], out[0]);
                            nq = 4;
                        } else {
                            // n_inside == 1 or 3: exactly 3 cut edges.
                            for (int e = 0; e < 6 && nq < 3; ++e) {
                                if (cut[e]) tri_src[nq++] = e;
                            }
                        }

                        int n_tris = (nq == 4) ? 2 : 1;
                        for (int t = 0; t < n_tris; ++t) {
                            int i0 = tri_src[(t == 0) ? 0 : 0];
                            int i1 = tri_src[(t == 0) ? 1 : 2];
                            int i2 = tri_src[(t == 0) ? 2 : 3];
                            float v0[3], v1[3], v2[3];
                            for (int d = 0; d < 3; ++d) {
                                v0[d] = pt[i0][d]; v1[d] = pt[i1][d]; v2[d] = pt[i2][d];
                            }
                            // Orient the normal away from the inside-centroid.
                            float e1[3] = {v1[0] - v0[0], v1[1] - v0[1], v1[2] - v0[2]};
                            float e2[3] = {v2[0] - v0[0], v2[1] - v0[1], v2[2] - v0[2]};
                            float nrm[3] = {
                                e1[1] * e2[2] - e1[2] * e2[1],
                                e1[2] * e2[0] - e1[0] * e2[2],
                                e1[0] * e2[1] - e1[1] * e2[0],
                            };
                            float ctr[3] = {(v0[0] + v1[0] + v2[0]) / 3.0f - ci[0],
                                            (v0[1] + v1[1] + v2[1]) / 3.0f - ci[1],
                                            (v0[2] + v1[2] + v2[2]) / 3.0f - ci[2]};
                            int base = static_cast<int>(verts.size() / 3);
                            if (nrm[0] * ctr[0] + nrm[1] * ctr[1] + nrm[2] * ctr[2] < 0.0f) {
                                faces.push_back(base);
                                faces.push_back(base + 2);
                                faces.push_back(base + 1);
                            } else {
                                faces.push_back(base);
                                faces.push_back(base + 1);
                                faces.push_back(base + 2);
                            }
                            for (int d = 0; d < 3; ++d) {
                                verts.push_back(v0[d]);
                            }
                            for (int d = 0; d < 3; ++d) {
                                verts.push_back(v1[d]);
                            }
                            for (int d = 0; d < 3; ++d) {
                                verts.push_back(v2[d]);
                            }
                            // Note: every triangle emits 3 fresh vertices
                            // (no shared-vertex deduplication), so a large
                            // volume uses ~3x the memory of an indexed mesh.
                            // Intentional simplicity — see cpp-core-review M5.
                        }
                    }
                }
            }
        }
    }

    size_t num_verts = verts.size() / 3;
    size_t num_faces = faces.size() / 3;

    auto r_verts = py::array_t<float>({num_verts, size_t(3)});
    auto r_faces = py::array_t<int>({num_faces, size_t(3)});

    std::copy(verts.begin(), verts.end(), static_cast<float*>(r_verts.request().ptr));
    std::copy(faces.begin(), faces.end(), static_cast<int*>(r_faces.request().ptr));

    return py::make_tuple(r_verts, r_faces);
}

PYBIND11_MODULE(seismic_3d_core, m) {
    m.doc() = "Native 3D seismic volume processing and slice extraction acceleration";
    m.def("fast_slice_extract", &fast_slice_extract, py::arg("volume"), py::arg("axis"), py::arg("index"));
    m.def("fast_slice_to_indexed8", &fast_slice_to_indexed8, py::arg("volume"), py::arg("axis"), py::arg("index"));
    m.def("fast_resample_volume_3d", &fast_resample_volume_3d, py::arg("volume"), py::arg("target_shape"));
    m.def("compute_coherence_3d", &compute_coherence_3d, py::arg("volume"), py::arg("inline_window") = 3, py::arg("crossline_window") = 3, py::arg("sample_window") = 3);
    m.def("marching_cubes_3d", &marching_cubes_3d, py::arg("volume"), py::arg("isovalue") = 0.0);
}
