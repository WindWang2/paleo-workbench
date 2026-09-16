#include <pwb/science/algorithms/coherence_c3.hpp>

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <ctime>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#include <pwb/science/registry.hpp>

namespace pwb::science::algorithms {

namespace {

constexpr int kDefaultHalfWindow = 5;
constexpr int kDefaultPowerIterations = 30;

std::string utc_now_iso() {
    const std::time_t now = std::time(nullptr);
    std::tm tm_buffer{};
#if defined(_MSC_VER)
    gmtime_s(&tm_buffer, &now);
#else
    gmtime_r(&now, &tm_buffer);
#endif
    char buffer[32];
    std::snprintf(buffer, sizeof(buffer), "%04d-%02d-%02dT%02d:%02d:%02dZ",
                  tm_buffer.tm_year + 1900, tm_buffer.tm_mon + 1, tm_buffer.tm_mday,
                  tm_buffer.tm_hour, tm_buffer.tm_min, tm_buffer.tm_sec);
    return buffer;
}

// np.pad(mode="reflect") index mapping: negative i folds to -i, i >= n folds
// to 2(n-1)-i, repeatedly. A length-1 axis reflects everything to 0.
inline std::int64_t reflect_index(std::int64_t i, std::int64_t n) {
    if (n <= 1) {
        return 0;
    }
    while (i < 0 || i >= n) {
        if (i < 0) {
            i = -i;
        } else {
            i = 2 * (n - 1) - i;
        }
    }
    return i;
}

class CoherenceC3Algorithm final : public IAlgorithm {
public:
    explicit CoherenceC3Algorithm(std::string build_identity)
        : build_identity_(std::move(build_identity)) {}

    [[nodiscard]] const AlgorithmDescriptor& descriptor() const override { return descriptor_; }

    Result<AlgorithmResultV1> run(const AlgorithmRequestV1& request, ProgressSink progress,
                                  std::stop_token stop) override;

private:
    AlgorithmDescriptor descriptor_ = [] {
        AlgorithmDescriptor descriptor;
        descriptor.algorithm_id = "seismic.coherence_c3";
        descriptor.version = "1.0.0";
        descriptor.display_name = "C3 eigenstructure coherence";
        descriptor.family = "seismic_attribute";
        descriptor.inputs.push_back(PortSpec{"volume", PortKind::volume_f32, "", true});
        descriptor.outputs.push_back(PortSpec{"coherence", PortKind::volume_f32, "", true});
        const auto int_param = [](const char* name, int minimum, int maximum,
                                  const char* default_json) {
            ParamSpec spec;
            spec.name = name;
            spec.type = ParamSpec::Type::integer;
            spec.minimum = minimum;
            spec.maximum = maximum;
            spec.default_json = default_json;
            return spec;
        };
        descriptor.parameters.push_back(int_param("win_il", 1, 512, "5"));
        descriptor.parameters.push_back(int_param("win_xl", 1, 512, "5"));
        descriptor.parameters.push_back(int_param("win_t", 1, 512, "5"));
        // Oracle freezes 30 iterations; kept as a parameter so provenance
        // records what actually ran.
        descriptor.parameters.push_back(int_param("power_iterations", 1, 10000, "30"));
        descriptor.supports_cancel = true;
        descriptor.deterministic = true;  // same inputs -> same outputs
        descriptor.approximate = true;    // power iteration, not exact eigenvalue
        return descriptor;
    }();
    std::string build_identity_;
};

// float32 power iteration on the implicit covariance A Aᵀ where A is
// (n_traces x samples). Mirrors geoviz_seismic._power_iteration_c3: v starts
// as ones, each iteration normalizes by max(norm, 1e-10), lambda_max is the
// squared norm of Aᵀv (Rayleigh quotient for the unit v).
float window_coherence(const float* window, std::size_t n_traces, std::size_t samples,
                       int iterations, std::vector<float>& v, std::vector<float>& w) {
    std::fill(v.begin(), v.end(), 1.0f);
    for (int iter = 0; iter < iterations; ++iter) {
        // w = Aᵀ v
        for (std::size_t k = 0; k < samples; ++k) {
            float sum = 0.0f;
            for (std::size_t j = 0; j < n_traces; ++j) {
                sum += window[j * samples + k] * v[j];
            }
            w[k] = sum;
        }
        // u = A w; then v = u / max(||u||, 1e-10)
        float norm_squared = 0.0f;
        for (std::size_t j = 0; j < n_traces; ++j) {
            float sum = 0.0f;
            for (std::size_t k = 0; k < samples; ++k) {
                sum += window[j * samples + k] * w[k];
            }
            v[j] = sum;
            norm_squared += sum * sum;
        }
        const float norm = std::sqrt(norm_squared);
        const float divisor = norm > 1e-10f ? norm : 1e-10f;
        for (std::size_t j = 0; j < n_traces; ++j) {
            v[j] /= divisor;
        }
    }
    // lambda_max = ||Aᵀ v||² (v is unit norm after the last normalization).
    float lambda = 0.0f;
    for (std::size_t k = 0; k < samples; ++k) {
        float sum = 0.0f;
        for (std::size_t j = 0; j < n_traces; ++j) {
            sum += window[j * samples + k] * v[j];
        }
        lambda += sum * sum;
    }
    float total_energy = 0.0f;
    for (std::size_t idx = 0; idx < n_traces * samples; ++idx) {
        total_energy += window[idx] * window[idx];
    }
    // Oracle: np.where(total_energy > 0, lambda/total, 1.0) — a NaN energy
    // fails the comparison and maps to 1.0, NaN-free parity.
    if (!(total_energy > 0.0f)) {
        return 1.0f;
    }
    return lambda / total_energy;
}

Result<AlgorithmResultV1> CoherenceC3Algorithm::run(const AlgorithmRequestV1& request,
                                                    ProgressSink progress,
                                                    std::stop_token stop) {
    const std::vector<Diagnostic> problems = validate_request(descriptor_, request);
    if (!problems.empty()) {
        return AlgorithmError{problems};
    }

    long long win_il = kDefaultHalfWindow;
    long long win_xl = kDefaultHalfWindow;
    long long win_t = kDefaultHalfWindow;
    long long iterations = kDefaultPowerIterations;
    for (const ParamSpec& spec : descriptor_.parameters) {
        const auto value = request_param_integer(request, spec);
        if (!value.has_value()) {
            return AlgorithmError{value.error().diagnostics};
        }
        if (spec.name == "win_il") {
            win_il = value.value();
        } else if (spec.name == "win_xl") {
            win_xl = value.value();
        } else if (spec.name == "win_t") {
            win_t = value.value();
        } else if (spec.name == "power_iterations") {
            iterations = value.value();
        }
    }

    const std::chrono::steady_clock::time_point start = std::chrono::steady_clock::now();
    const std::string started_utc = utc_now_iso();
    const VolumeView& input = request.input_volumes[0];
    const std::int64_t n_il = input.shape[0];
    const std::int64_t n_xl = input.shape[1];
    const std::int64_t n_t = input.shape[2];
    const std::array<std::int64_t, 3> strides = input.effective_strides();

    // Window extents: min(2w+1, n), then forced odd (matches the oracle).
    auto axis_window = [](std::int64_t half, std::int64_t n) {
        std::int64_t size = std::min(2 * half + 1, n);
        if (size % 2 == 0) {
            size -= 1;
        }
        return std::max<std::int64_t>(size, 1);
    };
    const std::int64_t wil = axis_window(win_il, n_il);
    const std::int64_t wxl = axis_window(win_xl, n_xl);
    const std::int64_t wt = axis_window(win_t, n_t);
    const std::int64_t pad_il = (wil - 1) / 2;
    const std::int64_t pad_xl = (wxl - 1) / 2;
    const std::int64_t pad_t = (wt - 1) / 2;
    const std::size_t n_traces = static_cast<std::size_t>(wil * wxl);

    auto output_storage = std::make_shared<std::vector<float>>(
        static_cast<std::size_t>(n_il * n_xl * n_t), 1.0f);
    float* out = output_storage->data();

    std::vector<float> window(n_traces * static_cast<std::size_t>(wt));
    std::vector<float> v(n_traces);
    std::vector<float> w(static_cast<std::size_t>(wt));

    for (std::int64_t il = 0; il < n_il; ++il) {
        if (stop.stop_requested()) {
            return TaskCancelled{"inline " + std::to_string(il)};
        }
        if (progress) {
            progress(ProgressReport{static_cast<double>(il) / static_cast<double>(n_il),
                                    "inline"});
        }
        for (std::int64_t xl = 0; xl < n_xl; ++xl) {
            for (std::int64_t t = 0; t < n_t; ++t) {
                // Gather the (wil x wxl x wt) analysis window with reflect
                // padding into a trace-major (n_traces x wt) buffer.
                std::size_t trace = 0;
                for (std::int64_t di = -pad_il; di <= pad_il; ++di) {
                    const std::int64_t si =
                      strides[0] * reflect_index(il + di, n_il);
                    for (std::int64_t dj = -pad_xl; dj <= pad_xl; ++dj) {
                        const std::int64_t sj =
                          strides[1] * reflect_index(xl + dj, n_xl);
                        float* dst = window.data() + trace * static_cast<std::size_t>(wt);
                        for (std::int64_t dt = -pad_t; dt <= pad_t; ++dt) {
                            const std::int64_t source =
                                si + sj + strides[2] * reflect_index(t + dt, n_t);
                            dst[dt + pad_t] = input.data[source];
                        }
                        ++trace;
                    }
                }
                const float coherence =
                    window_coherence(window.data(), n_traces, static_cast<std::size_t>(wt),
                                     static_cast<int>(iterations), v, w);
                out[(il * n_xl + xl) * n_t + t] = coherence;
            }
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
    output_view.lifetime = output_storage; // keeps the buffer alive with the result
    ProducedVolume produced;
    produced.name = "coherence";
    produced.volume = output_view;
    produced.unit = "";
    result.outputs.push_back(std::move(produced));

    ProvenanceRecord& provenance = result.provenance;
    provenance.algorithm_id = descriptor_.algorithm_id;
    provenance.algorithm_version = descriptor_.version;
    provenance.build_identity = build_identity_;
    provenance.params_json = request.params_json;
    provenance.input_refs = request.input_refs;
    provenance.started_utc = started_utc;
    provenance.finished_utc = utc_now_iso();
    provenance.approximate = descriptor_.approximate;
    provenance.wall_time_ms = static_cast<std::uint64_t>(
        std::chrono::duration_cast<std::chrono::milliseconds>(finish - start).count());
    result.diagnostics.push_back(Diagnostic{
        "algorithm.approximate",
        "lambda_max estimated by " + std::to_string(iterations) + " power iterations",
        "info"});
    return result;
}

} // namespace (anonymous utilities + algorithm class)

std::unique_ptr<IAlgorithm> make_coherence_c3(std::string build_identity) {
    return std::make_unique<CoherenceC3Algorithm>(std::move(build_identity));
}

} // namespace pwb::science::algorithms
