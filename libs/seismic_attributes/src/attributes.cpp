#include <pwb/seismic_attributes/attributes.hpp>

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <complex>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#include <pwb/science/registry.hpp>

#include "detail/attribute_math.hpp"

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

using detail::analytic_signal;
using detail::batch_trace_count;
using detail::gradient_spacing1;
using detail::kMaxHalfWindow;
using detail::kPi;
using detail::kTwoPi;
using detail::symmetric_index;
using detail::unwrap_phase;
using detail::utc_now_iso;

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

// Analytic signal / unwrap / gradient / symmetric folding / batching come
// from detail/attribute_math.hpp (shared with volume_attributes.cpp).

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
    // Fixed order: envelope, phase, frequency, rms, sweetness,
    // relative_impedance, dip_il, dip_xl, dip_azimuth, curvature_mean.
    std::unique_ptr<IAlgorithm> candidates[] = {
        make_envelope(build_identity),
        make_instantaneous_phase(build_identity),
        make_instantaneous_frequency(build_identity),
        make_rms_amplitude(build_identity),
        make_sweetness(build_identity),
        make_relative_impedance(build_identity),
        make_dip_inline(build_identity),
        make_dip_crossline(build_identity),
        make_dip_azimuth(build_identity),
        make_curvature_mean(std::move(build_identity)),
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
