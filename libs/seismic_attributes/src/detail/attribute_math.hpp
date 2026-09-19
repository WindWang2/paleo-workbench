#pragma once

// Internal shared math for the seismic attribute kernels. Used by BOTH
// attributes.cpp (the four trace-global E-line kernels) and
// volume_attributes.cpp (the six S-line kernels). Nothing here is exported:
// the numerical contracts live in docs/development/*/v3-contracts.md.
//
// Parity targets (frozen):
//   * scipy.signal.hilbert on float64 (spectrum weights below)
//   * numpy unwrap (cumsum-diffusion NaN topology) + numpy gradient
//     (edge_order=1)
//   * numpy float32 chains for the S-line kernels (NEP 50: python-float
//     scalars are weak, so f32 arrays stay f32 through arithmetic)

#include <cmath>
#include <complex>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <ctime>
#include <limits>
#include <vector>

// Vendored FFT: mreinecke/pocketfft (cpp branch) commit c90e55b3, BSD-3.
// Single-threaded, no plan cache — see cpp-seismic-attributes v3-contracts §5.
#define POCKETFFT_NO_MULTITHREADING
#define POCKETFFT_CACHE_SIZE 0
#if defined(__GNUC__)
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wall"
#pragma GCC diagnostic ignored "-Wextra"
#pragma GCC diagnostic ignored "-Wpedantic"
#pragma GCC diagnostic ignored "-Wmaybe-uninitialized"
#endif
#include "pocketfft_hdronly.h"
#if defined(__GNUC__)
#pragma GCC diagnostic pop
#endif

namespace pwb::seismic_attributes::detail {

inline constexpr double kTwoPi = 6.283185307179586476925286766559;
inline constexpr double kPi = 3.141592653589793238462643383280;

inline std::string utc_now_iso() {
    const std::time_t now = std::time(nullptr);
    std::tm tm_buffer{};
#if defined(_MSC_VER)
    gmtime_s(&tm_buffer, &now);
#else
    gmtime_r(&now, &tm_buffer);
#endif
    char buffer[96];  // wide enough for the format-truncation analyzer
    std::snprintf(buffer, sizeof(buffer), "%04d-%02d-%02dT%02d:%02d:%02dZ",
                  tm_buffer.tm_year + 1900, tm_buffer.tm_mon + 1,
                  tm_buffer.tm_mday, tm_buffer.tm_hour, tm_buffer.tm_min,
                  tm_buffer.tm_sec);
    return buffer;
}

// np.pad(mode="symmetric") folding — what scipy.ndimage calls mode="reflect".
// Any integer index maps into [0, n); the edge element is repeated
// (... x1 x0 | x0 x1 ... xn-1 xn-1 | xn-2 ...), period 2n. n == 1 folds all
// to 0. (Distinct from coherence_c3's np.pad "reflect" without edge repeat.)
inline std::int64_t symmetric_index(std::int64_t i, std::int64_t n) {
    if (n <= 1) {
        return 0;
    }
    const std::int64_t period = 2 * n;
    std::int64_t r = i % period;
    if (r < 0) {
        r += period;
    }
    return r < n ? r : period - 1 - r;
}

// Spatial batching cap: float64 complex scratch for one batch stays below
// 64 MiB and below 512 traces; batching affects progress granularity and
// temporary memory only, never values.
inline constexpr double kBatchTempBytes = 64.0 * 1024.0 * 1024.0;
inline constexpr std::int64_t kMaxBatchTraces = 512;
inline constexpr std::int64_t kMaxHalfWindow = 1048576;

inline std::int64_t batch_trace_count(std::int64_t n_t) {
    const double per_trace = 16.0 * static_cast<double>(n_t);
    std::int64_t by_bytes =
        static_cast<std::int64_t>(kBatchTempBytes / per_trace);
    if (by_bytes < 1) {
        by_bytes = 1;
    }
    return std::min<std::int64_t>(by_bytes, kMaxBatchTraces);
}

// ---------------------------------------------------------------------------
// Hilbert analytic signal (scipy.signal.hilbert parity, float64)
// ---------------------------------------------------------------------------

// Spectrum weights h: DC kept (1), positive interior bins doubled, even-N
// Nyquist bin kept (1), negative bins zeroed — scipy's exact convention.
// In-place on the (n_traces x n_t) row-major complex buffer; each row is one
// full time trace (no time chunking).
inline void analytic_signal(std::vector<std::complex<double>>& buffer,
                            std::size_t n_t, std::size_t n_traces) {
    const pocketfft::shape_t shape{n_traces, n_t};
    const pocketfft::stride_t stride{
        static_cast<ptrdiff_t>(n_t * sizeof(std::complex<double>)),
        static_cast<ptrdiff_t>(sizeof(std::complex<double>))};
    auto* data = buffer.data();
    pocketfft::c2c<double>(shape, stride, stride, {1}, pocketfft::FORWARD,
                           data, data, 1.0);

    std::vector<double> weights(n_t, 0.0);
    weights[0] = 1.0;
    const std::size_t positive_end = (n_t % 2 == 0) ? n_t / 2 : (n_t + 1) / 2;
    for (std::size_t k = 1; k < positive_end; ++k) {
        weights[k] = 2.0;
    }
    if (n_t % 2 == 0 && n_t > 0) {
        weights[n_t / 2] = 1.0;
    }
    for (std::size_t trace = 0; trace < n_traces; ++trace) {
        std::complex<double>* row = buffer.data() + trace * n_t;
        for (std::size_t k = 0; k < n_t; ++k) {
            row[k] *= weights[k];
        }
    }

    pocketfft::c2c<double>(shape, stride, stride, {1}, pocketfft::BACKWARD,
                           data, data, 1.0 / static_cast<double>(n_t));
}

// np.unwrap(period=2*pi) parity on one trace: corrections are computed from
// diffs of the ORIGINAL values and accumulated (cumsum). A NaN diff makes the
// correction NaN, and every later output stays NaN — replicating numpy's
// cumsum propagation. An exact +pi jump is kept uncorrected.
inline void unwrap_phase(const double* phase, double* out, std::size_t n) {
    out[0] = phase[0];
    double correction = 0.0;
    bool poisoned = false;
    for (std::size_t i = 1; i < n; ++i) {
        const double dd = phase[i] - phase[i - 1];
        double ddmod = std::fmod(dd + kPi, kTwoPi);
        if (ddmod < 0.0) {
            ddmod += kTwoPi;
        }
        ddmod -= kPi;
        if (ddmod == -kPi && dd > 0.0) {
            ddmod = kPi;
        }
        const double corr = ddmod - dd;  // multiple of 2*pi (or NaN)
        if (std::isnan(corr)) {
            poisoned = true;
        }
        correction = poisoned ? std::numeric_limits<double>::quiet_NaN()
                              : correction + corr;
        out[i] = phase[i] + correction;
    }
}

// np.gradient(edge_order=1) parity, float64: second-order central difference
// inside, first-order one-sided at both edges. Caller guarantees n >= 2.
inline void gradient_spacing1(const double* p, double dt, double* out,
                              std::size_t n) {
    const double inverse = 1.0 / dt;
    out[0] = (p[1] - p[0]) * inverse;
    for (std::size_t i = 1; i + 1 < n; ++i) {
        out[i] = (p[i + 1] - p[i - 1]) * (0.5 * inverse);
    }
    out[n - 1] = (p[n - 1] - p[n - 2]) * inverse;
}

// ---------------------------------------------------------------------------
// numpy float32 gradient replication (S-line dip/curvature chains).
// NEP 50: an f32 array divided by a python-float scalar divides by the
// scalar cast to f32, in f32 arithmetic.
// ---------------------------------------------------------------------------

// np.gradient(f32, spacing, axis) along one contiguous f32 line. n >= 2
// guaranteed by the caller (numpy raises "shape too small" below that).
// `spacing` is the python-float (f64) scalar: numpy casts it to f32 per NEP
// 50 — central divides by f32(2*spacing), edges by f32(spacing), both
// computed in f64 first (2*spacing is an exact f64 scaling of the scalar).
inline void gradient_f32_line(const float* p, double spacing, float* out,
                              std::size_t n) {
    const float edge = static_cast<float>(spacing);
    const float central = static_cast<float>(2.0 * spacing);
    out[0] = (p[1] - p[0]) / edge;
    for (std::size_t i = 1; i + 1 < n; ++i) {
        out[i] = (p[i + 1] - p[i - 1]) / central;
    }
    out[n - 1] = (p[n - 1] - p[n - 2]) / edge;
}

}  // namespace pwb::seismic_attributes::detail
