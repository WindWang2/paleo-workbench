#include <pwb/seismic_attributes/attributes.hpp>

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <complex>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <ctime>
#include <limits>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#include <pwb/science/registry.hpp>

// Vendored FFT: mreinecke/pocketfft (cpp branch) commit c90e55b3, BSD-3.
// Single-threaded, no plan cache — see v3-contracts.md §5.
#define POCKETFFT_NO_MULTITHREADING
#define POCKETFFT_CACHE_SIZE 0
#if defined(__GNUC__)
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wall"
#pragma GCC diagnostic ignored "-Wextra"
#pragma GCC diagnostic ignored "-Wpedantic"
#pragma GCC diagnostic ignored "-Wmaybe-uninitialized"
#endif
#include "detail/pocketfft_hdronly.h"
#if defined(__GNUC__)
#pragma GCC diagnostic pop
#endif

namespace pwb::seismic_attributes {

using pwb::science::AlgorithmDescriptor;
using pwb::science::AlgorithmError;
using pwb::science::AlgorithmRequestV1;
using pwb::science::AlgorithmResultV1;
using pwb::science::Diagnostic;
using pwb::science::IAlgorithm;
using pwb::science::ParamSpec;
using pwb::science::PortKind;
using pwb::science::PortSpec;
using pwb::science::ProducedVolume;
using pwb::science::ProgressReport;
using pwb::science::ProgressSink;
using pwb::science::ProvenanceRecord;
using pwb::science::Result;
using pwb::science::TaskCancelled;
using pwb::science::VolumeView;

namespace {

constexpr double kTwoPi = 6.283185307179586476925286766559;
constexpr double kPi = 3.141592653589793238462643383280;

std::string utc_now_iso() {
    const std::time_t now = std::time(nullptr);
    std::tm tm_buffer{};
#if defined(_MSC_VER)
    gmtime_s(&tm_buffer, &now);
#else
    gmtime_r(&now, &tm_buffer);
#endif
    char buffer[96]; // wide enough for the format-truncation analyzer
    std::snprintf(buffer, sizeof(buffer), "%04d-%02d-%02dT%02d:%02d:%02dZ",
                  tm_buffer.tm_year + 1900, tm_buffer.tm_mon + 1, tm_buffer.tm_mday,
                  tm_buffer.tm_hour, tm_buffer.tm_min, tm_buffer.tm_sec);
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

enum class AttributeKind { envelope, phase, freq, rms };

struct KindInfo {
    const char* algorithm_id;
    const char* output_name;
    const char* output_unit;
    const char* display_name;
};

constexpr KindInfo kind_info(AttributeKind kind) {
    switch (kind) {
    case AttributeKind::envelope:
        return {"seismic.envelope", "envelope", "",
                "Instantaneous amplitude (envelope)"};
    case AttributeKind::phase:
        return {"seismic.instantaneous_phase", "instantaneous_phase", "rad",
                "Instantaneous phase"};
    case AttributeKind::freq:
        return {"seismic.instantaneous_frequency", "instantaneous_frequency",
                "Hz", "Instantaneous frequency"};
    case AttributeKind::rms:
        return {"seismic.rms_amplitude", "rms_amplitude", "",
                "Windowed RMS amplitude"};
    }
    return {"", "", "", ""};
}

constexpr std::int64_t kMaxHalfWindow = 1048576;
// Spatial batching cap: float64 complex scratch for one batch stays below
// 64 MiB and below 512 traces; batching affects progress granularity and
// temporary memory only, never values.
constexpr double kBatchTempBytes = 64.0 * 1024.0 * 1024.0;
constexpr std::int64_t kMaxBatchTraces = 512;

std::int64_t batch_trace_count(std::int64_t n_t) {
    const double per_trace = 16.0 * static_cast<double>(n_t);
    std::int64_t by_bytes = static_cast<std::int64_t>(kBatchTempBytes / per_trace);
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
void analytic_signal(std::vector<std::complex<double>>& buffer, std::size_t n_t,
                     std::size_t n_traces) {
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
void unwrap_phase(const double* phase, double* out, std::size_t n) {
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
        const double corr = ddmod - dd; // multiple of 2*pi (or NaN)
        if (std::isnan(corr)) {
            poisoned = true;
        }
        correction = poisoned ? std::numeric_limits<double>::quiet_NaN()
                              : correction + corr;
        out[i] = phase[i] + correction;
    }
}

// np.gradient(edge_order=1) parity: second-order central difference inside,
// first-order one-sided at both edges. Caller guarantees n >= 2.
void gradient_spacing1(const double* p, double dt, double* out, std::size_t n) {
    const double inverse = 1.0 / dt;
    out[0] = (p[1] - p[0]) * inverse;
    for (std::size_t i = 1; i + 1 < n; ++i) {
        out[i] = (p[i + 1] - p[i - 1]) * (0.5 * inverse);
    }
    out[n - 1] = (p[n - 1] - p[n - 2]) * inverse;
}

// ---------------------------------------------------------------------------
// The algorithm
// ---------------------------------------------------------------------------

class TraceAttributeAlgorithm final : public IAlgorithm {
public:
    TraceAttributeAlgorithm(AttributeKind kind, std::string build_identity)
        : kind_(kind), build_identity_(std::move(build_identity)), descriptor_{} {
        const KindInfo info = kind_info(kind);
        descriptor_.algorithm_id = info.algorithm_id;
        descriptor_.version = "1.0.0";
        descriptor_.display_name = info.display_name;
        descriptor_.family = "seismic_attribute";
        descriptor_.inputs.push_back(PortSpec{"volume", PortKind::volume_f32, "", true});
        descriptor_.outputs.push_back(PortSpec{info.output_name, PortKind::volume_f32,
                                               info.output_unit, true});
        if (kind_ == AttributeKind::freq) {
            ParamSpec spec;
            spec.name = "sample_interval";
            spec.type = ParamSpec::Type::number;
            spec.unit = "s";
            spec.default_json = "1.0";
            descriptor_.parameters.push_back(spec);
        } else if (kind_ == AttributeKind::rms) {
            ParamSpec spec;
            spec.name = "window";
            spec.type = ParamSpec::Type::integer;
            spec.minimum = 0;
            spec.maximum = static_cast<double>(kMaxHalfWindow);
            spec.default_json = "21";
            descriptor_.parameters.push_back(spec);
        }
        descriptor_.supports_cancel = true;
        descriptor_.deterministic = true;
        descriptor_.approximate = false;
        descriptor_.build_identity = build_identity_;
    }

    [[nodiscard]] const AlgorithmDescriptor& descriptor() const override {
        return descriptor_;
    }

    Result<AlgorithmResultV1> run(const AlgorithmRequestV1& request, ProgressSink progress,
                                  std::stop_token stop) override;

private:
    AttributeKind kind_;
    std::string build_identity_;
    AlgorithmDescriptor descriptor_;
};

Result<AlgorithmResultV1> TraceAttributeAlgorithm::run(const AlgorithmRequestV1& request,
                                                        ProgressSink progress,
                                                        std::stop_token stop) {
    const std::vector<Diagnostic> problems =
        pwb::science::validate_request(descriptor_, request);
    if (!problems.empty()) {
        return AlgorithmError{problems};
    }

    double sample_interval = 1.0;
    std::int64_t half_window = 21;
    for (const ParamSpec& spec : descriptor_.parameters) {
        if (spec.name == "sample_interval") {
            const auto value = pwb::science::request_param_number(request, spec);
            if (!value.has_value()) {
                return AlgorithmError{value.error().diagnostics};
            }
            sample_interval = value.value();
            if (!(sample_interval > 0.0)) {
                return AlgorithmError{{Diagnostic{
                    "param.sample_interval.not_positive",
                    "sample_interval must be > 0 (seconds); got " +
                        std::to_string(sample_interval),
                    "error"}}};
            }
        } else if (spec.name == "window") {
            const auto value = pwb::science::request_param_integer(request, spec);
            if (!value.has_value()) {
                return AlgorithmError{value.error().diagnostics};
            }
            half_window = value.value();
        }
    }

    const VolumeView& input = request.input_volumes[0];
    const std::int64_t n_il = input.shape[0];
    const std::int64_t n_xl = input.shape[1];
    const std::int64_t n_t = input.shape[2];
    if (kind_ == AttributeKind::freq && n_t < 2) {
        return AlgorithmError{{Diagnostic{
            "input.sample_count.too_small",
            "instantaneous frequency needs at least 2 samples per trace "
            "(np.gradient raises on length-1 axes); got " +
                std::to_string(n_t),
            "error"}}};
    }
    const std::array<std::int64_t, 3> strides = input.effective_strides();
    const std::int64_t total_traces = n_il * n_xl;
    const std::size_t trace_len = static_cast<std::size_t>(n_t);

    const std::chrono::steady_clock::time_point start = std::chrono::steady_clock::now();
    const std::string started_utc = utc_now_iso();

    auto output_storage = std::make_shared<std::vector<float>>(
        static_cast<std::size_t>(total_traces * n_t), 0.0f);
    float* out = output_storage->data();

    const std::int64_t batch = batch_trace_count(n_t);
    const bool needs_analytic = kind_ != AttributeKind::rms;
    std::vector<std::complex<double>> complex_buffer(
        needs_analytic ? static_cast<std::size_t>(batch) * trace_len : 0u);
    // Per-trace double scratch for the frequency chain (phase/unwrap/grad).
    std::vector<double> phase(trace_len);
    std::vector<double> unwrapped(trace_len);
    std::vector<double> grad(trace_len);
    // RMS scratch: symmetric-padded prefix sums of sanitized squares plus
    // NaN and Inf prefix counts, over padded length n + 2*window.
    const std::size_t padded_len =
        kind_ == AttributeKind::rms
            ? trace_len + 2u * static_cast<std::size_t>(half_window)
            : 0u;
    std::vector<double> padded(kind_ == AttributeKind::rms ? padded_len : 0u);

    std::int64_t completed = 0;
    for (std::int64_t first = 0; first < total_traces; first += batch) {
        if (stop.stop_requested()) {
            return TaskCancelled{"traces " + std::to_string(completed) + "/" +
                                 std::to_string(total_traces)};
        }
        const std::int64_t last = std::min(first + batch, total_traces);
        const std::size_t n_batch = static_cast<std::size_t>(last - first);

        if (needs_analytic) {
            for (std::size_t b = 0; b < n_batch; ++b) {
                const std::int64_t trace = first + static_cast<std::int64_t>(b);
                const std::int64_t base =
                    strides[0] * (trace / n_xl) + strides[1] * (trace % n_xl);
                std::complex<double>* row = complex_buffer.data() + b * trace_len;
                for (std::size_t t = 0; t < trace_len; ++t) {
                    row[t] = {static_cast<double>(
                                  input.data[base + strides[2] * static_cast<std::int64_t>(t)]),
                              0.0};
                }
            }
            analytic_signal(complex_buffer, trace_len, n_batch);

            for (std::size_t b = 0; b < n_batch; ++b) {
                const std::int64_t trace = first + static_cast<std::int64_t>(b);
                const std::complex<double>* row = complex_buffer.data() + b * trace_len;
                float* dst = out + static_cast<std::size_t>(trace) * trace_len;
                switch (kind_) {
                case AttributeKind::envelope:
                    for (std::size_t t = 0; t < trace_len; ++t) {
                        dst[t] = static_cast<float>(std::abs(row[t]));
                    }
                    break;
                case AttributeKind::phase:
                    for (std::size_t t = 0; t < trace_len; ++t) {
                        dst[t] = static_cast<float>(
                            std::atan2(row[t].imag(), row[t].real()));
                    }
                    break;
                case AttributeKind::freq: {
                    for (std::size_t t = 0; t < trace_len; ++t) {
                        phase[t] = std::atan2(row[t].imag(), row[t].real());
                    }
                    unwrap_phase(phase.data(), unwrapped.data(), trace_len);
                    gradient_spacing1(unwrapped.data(), sample_interval, grad.data(),
                                      trace_len);
                    constexpr double kInvTwoPi = 1.0 / kTwoPi;
                    for (std::size_t t = 0; t < trace_len; ++t) {
                        dst[t] = static_cast<float>(grad[t] * kInvTwoPi);
                    }
                    break;
                }
                case AttributeKind::rms:
                    break; // unreachable; kept for exhaustive switch
                }
            }
        } else {
            // Windowed RMS over the symmetric-padded square sequence with a
            // scipy-identical running sum: sequential init over the first
            // window, then s = (s - oldest) + newest for every slide. This
            // replicates uniform_filter1d's exact non-finite topology,
            // measured on the pinned oracle: a NaN entering the sum poisons
            // the output for the REST of the trace; an Inf yields Inf while
            // inside the window and NaN from the step it leaves onward
            // (Inf - Inf). Finite values then differ only in float64
            // rounding order.
            const std::int64_t w = half_window;
            const std::int64_t n64 = static_cast<std::int64_t>(trace_len);
            const std::size_t window = static_cast<std::size_t>(2 * w + 1);
            for (std::size_t b = 0; b < n_batch; ++b) {
                const std::int64_t trace = first + static_cast<std::int64_t>(b);
                const std::int64_t base =
                    strides[0] * (trace / n_xl) + strides[1] * (trace % n_xl);
                float* dst = out + static_cast<std::size_t>(trace) * trace_len;
                for (std::size_t j = 0; j < padded_len; ++j) {
                    const std::int64_t idx =
                        symmetric_index(static_cast<std::int64_t>(j) - w, n64);
                    const double x = static_cast<double>(
                        input.data[base + strides[2] * idx]);
                    // x*x propagates NaN and maps +/-Inf to +Inf, like the
                    // oracle's float64 squaring.
                    padded[j] = x * x;
                }
                double sum = 0.0;
                for (std::size_t j = 0; j < window; ++j) {
                    sum += padded[j];
                }
                // np.sqrt(np.maximum(mean, 0)) with NaN passing through.
                for (std::size_t t = 0; t < trace_len; ++t) {
                    if (t > 0) {
                        sum = (sum - padded[t - 1]) + padded[t + window - 1];
                    }
                    const double mean = sum / static_cast<double>(window);
                    const double clamped = (std::isnan(mean) || mean > 0.0) ? mean : 0.0;
                    dst[t] = static_cast<float>(std::sqrt(clamped));
                }
            }
        }

        completed = last;
        if (progress) {
            progress(ProgressReport{
                static_cast<double>(completed) / static_cast<double>(total_traces),
                "traces"});
        }
    }
    if (progress) {
        progress(ProgressReport{1.0, "done"});
    }

    const std::chrono::steady_clock::time_point finish = std::chrono::steady_clock::now();
    AlgorithmResultV1 result;
    result.request_id = request.request_id;
    VolumeView output_view;
    output_view.data = out;
    output_view.shape = input.shape;
    output_view.strides = {n_xl * n_t, n_t, 1};
    output_view.lifetime = output_storage; // owns the float32 payload
    const KindInfo info = kind_info(kind_);
    ProducedVolume produced;
    produced.name = info.output_name;
    produced.volume = output_view;
    produced.unit = info.output_unit;
    result.outputs.push_back(std::move(produced));

    ProvenanceRecord& provenance = result.provenance;
    provenance.algorithm_id = descriptor_.algorithm_id;
    provenance.algorithm_version = descriptor_.version;
    provenance.build_identity = build_identity_;
    provenance.params_json = request.params_json;
    provenance.input_refs = request.input_refs;
    provenance.started_utc = started_utc;
    provenance.finished_utc = utc_now_iso();
    provenance.approximate = false;
    provenance.wall_time_ms = static_cast<std::uint64_t>(
        std::chrono::duration_cast<std::chrono::milliseconds>(finish - start).count());

    if (kind_ == AttributeKind::freq) {
        result.diagnostics.push_back(Diagnostic{
            "algorithm.unit_semantics",
            "sample_interval=" + std::to_string(sample_interval) +
                " s; output in Hz (cycles/s) = gradient(unwrapped phase)/(2*pi*dt)",
            "info"});
    } else if (kind_ == AttributeKind::rms) {
        result.diagnostics.push_back(Diagnostic{
            "algorithm.window_semantics",
            "window=" + std::to_string(half_window) + " is a HALF window; total " +
                std::to_string(2 * half_window + 1) +
                " samples, symmetric (edge-repeat) padding",
            "info"});
    }
    return result;
}

} // namespace

std::unique_ptr<IAlgorithm> make_envelope(std::string build_identity) {
    return std::make_unique<TraceAttributeAlgorithm>(AttributeKind::envelope,
                                                     std::move(build_identity));
}

std::unique_ptr<IAlgorithm> make_instantaneous_phase(std::string build_identity) {
    return std::make_unique<TraceAttributeAlgorithm>(AttributeKind::phase,
                                                     std::move(build_identity));
}

std::unique_ptr<IAlgorithm> make_instantaneous_frequency(std::string build_identity) {
    return std::make_unique<TraceAttributeAlgorithm>(AttributeKind::freq,
                                                     std::move(build_identity));
}

std::unique_ptr<IAlgorithm> make_rms_amplitude(std::string build_identity) {
    return std::make_unique<TraceAttributeAlgorithm>(AttributeKind::rms,
                                                     std::move(build_identity));
}

RegistrationReport register_seismic_attributes(pwb::science::AlgorithmRegistry& registry,
                                               std::string build_identity) {
    RegistrationReport report;
    // Fixed order: envelope, phase, frequency, rms.
    std::unique_ptr<IAlgorithm> candidates[] = {
        make_envelope(build_identity),
        make_instantaneous_phase(build_identity),
        make_instantaneous_frequency(build_identity),
        make_rms_amplitude(std::move(build_identity)),
    };
    for (auto& algorithm : candidates) {
        const std::string id = algorithm->descriptor().algorithm_id;
        const std::string rejection = registry.register_algorithm(std::move(algorithm));
        if (!rejection.empty()) {
            report.rejection = rejection; // e.g. "duplicate algorithm_id: ..."
            break;
        }
        report.registered_ids.push_back(id);
    }
    return report;
}

} // namespace pwb::seismic_attributes
