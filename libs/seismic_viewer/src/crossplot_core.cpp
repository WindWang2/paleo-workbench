#include <pwb/seismic_viewer/crossplot_core.hpp>

#include <algorithm>
#include <cmath>
#include <limits>
#include <memory>
#include <string>
#include <vector>

#include <pwb/science/algorithm.hpp>
#include <pwb/science/types.hpp>
#include <pwb/seismic_attributes/attributes.hpp>

#include <string_view>

namespace pwb::seismic_viewer::crossplot {
namespace {

double percentile_of(std::vector<double> values, double q) {
    if (values.empty()) {
        return std::numeric_limits<double>::quiet_NaN();
    }
    std::sort(values.begin(), values.end());
    const std::size_t n = values.size();
    if (n == 1) {
        return values[0];
    }
    const double rank = (q / 100.0) * static_cast<double>(n - 1);
    const std::size_t lo = static_cast<std::size_t>(std::floor(rank));
    if (lo + 1 >= n || rank == static_cast<double>(lo)) {
        return values[std::min(lo, n - 1)];
    }
    const double frac = rank - static_cast<double>(lo);
    return values[lo] + (values[lo + 1] - values[lo]) * frac;
}

// Runs one seismic_attributes kernel over the (n_traces, 1, n_samples)
// volume wrapping the slice plane; returns the per-sample output re-indexed
// to the numpy flatten order of the (n_samples, n_traces) source. An empty
// vector + diagnostic on failure (never a throw across this boundary).
// `resolver` (when given) is the product's executor authority (fresh owned
// kernel per call — see the AlgorithmResolver contract); null falls back
// to constructing the frozen kernels directly (headless parity; no
// TU-local registry — the paleo Processing provider owns discovery).
bool run_trace_kernel(const char* algorithm_id, std::span<const float> plane,
                      std::int64_t n_samples, std::int64_t n_traces,
                      double sample_interval_s,
                      const AlgorithmResolver& resolver,
                      std::vector<float>& out, std::string& diagnostic) {
    std::unique_ptr<pwb::science::IAlgorithm> algorithm;
    if (resolver) {
        algorithm = resolver(algorithm_id);
    } else if (std::string_view(algorithm_id) == "seismic.envelope") {
        algorithm = pwb::seismic_attributes::make_envelope("viz-d-crossplot");
    } else if (std::string_view(algorithm_id)
               == "seismic.instantaneous_frequency") {
        algorithm = pwb::seismic_attributes::make_instantaneous_frequency(
            "viz-d-crossplot");
    }
    if (algorithm == nullptr) {
        diagnostic = std::string("algorithm not registered: ") + algorithm_id;
        return false;
    }
    // Wrap the plane as (n_traces, 1, n_samples): each inline is one trace.
    // The incoming plane is sample-major ((n_samples, n_traces) numpy
    // order); transpose into a trace-major buffer so the packed volume view
    // is honest (the kernels only accept packed layouts).
    auto holder = std::make_shared<std::vector<float>>(plane.size());
    for (std::int64_t t = 0; t < n_traces; ++t) {
        for (std::int64_t s = 0; s < n_samples; ++s) {
            (*holder)[static_cast<std::size_t>(t * n_samples + s)] =
                plane[static_cast<std::size_t>(s * n_traces + t)];
        }
    }
    pwb::science::VolumeView view;
    view.data = holder->data();
    view.shape = {n_traces, 1, n_samples};
    view.strides = {0, 0, 0}; // packed C-order (trace-major)
    view.lifetime = holder;

    pwb::science::AlgorithmRequestV1 request;
    request.algorithm_id = algorithm_id;
    request.algorithm_version = algorithm->descriptor().version;
    request.params_json = {{"sample_interval", std::to_string(sample_interval_s)}};
    request.input_volumes.push_back(view);
    pwb::science::Result<pwb::science::AlgorithmResultV1> result =
        algorithm->run(request, nullptr, {});
    if (!result.has_value()) {
        diagnostic = std::string("kernel failed: ") + algorithm_id;
        if (result.is_error() && !result.error().diagnostics.empty()) {
            diagnostic += " (" + result.error().diagnostics.front().code + ")";
        }
        return false;
    }
    const auto& produced = result.value().outputs;
    if (produced.size() != 1) {
        diagnostic = std::string("kernel produced no volume: ") + algorithm_id;
        return false;
    }
    const pwb::science::VolumeView& volume = produced.front().volume;
    if (volume.size() != static_cast<std::int64_t>(plane.size())) {
        diagnostic = std::string("kernel output shape mismatch: ") + algorithm_id;
        return false;
    }
    // Kernel layout is (trace, 1, sample) => index t * n_samples + s; the
    // numpy source flattens (n_samples, n_traces) sample-major.
    out.assign(plane.size(), 0.0f);
    for (std::int64_t t = 0; t < n_traces; ++t) {
        for (std::int64_t s = 0; s < n_samples; ++s) {
            out[static_cast<std::size_t>(s * n_traces + t)] =
                volume.data[static_cast<std::size_t>(t * n_samples + s)];
        }
    }
    return true;
}

} // namespace

LithologyCrossplot analyze_lithology_crossplot(std::span<const double> gr,
                                               std::span<const double> ai,
                                               const std::vector<std::string>& lithology) {
    LithologyCrossplot crossplot;
    const std::size_t n = std::min(gr.size(), ai.size());
    crossplot.points.reserve(n);
    std::vector<std::vector<std::size_t>> groups;
    std::vector<std::string> labels;
    for (std::size_t i = 0; i < n; ++i) {
        const std::string& label = i < lithology.size() ? lithology[i] : std::string("Unknown");
        crossplot.points.push_back({gr[i], ai[i], label});
        auto it = std::find(labels.begin(), labels.end(), label);
        if (it == labels.end()) {
            labels.push_back(label);
            groups.emplace_back();
            it = labels.end() - 1;
        }
        groups[static_cast<std::size_t>(it - labels.begin())].push_back(i);
    }
    for (std::size_t g = 0; g < labels.size(); ++g) {
        LithologyCluster cluster;
        cluster.count = static_cast<std::int64_t>(groups[g].size());
        double sum_gr = 0.0;
        double sum_ai = 0.0;
        for (const std::size_t i : groups[g]) {
            sum_gr += gr[i];
            sum_ai += ai[i];
        }
        const double inv = 1.0 / static_cast<double>(cluster.count);
        cluster.mean_gr = sum_gr * inv;
        cluster.mean_ai = sum_ai * inv;
        double var_gr = 0.0;
        double var_ai = 0.0;
        for (const std::size_t i : groups[g]) {
            var_gr += (gr[i] - cluster.mean_gr) * (gr[i] - cluster.mean_gr);
            var_ai += (ai[i] - cluster.mean_ai) * (ai[i] - cluster.mean_ai);
        }
        var_gr *= inv; // population variance (numpy std, ddof = 0)
        var_ai *= inv;
        cluster.std_gr = std::sqrt(var_gr);
        cluster.std_ai = std::sqrt(var_ai);
        crossplot.clusters.emplace_back(labels[g], cluster);
    }
    return crossplot;
}

AttributeCrossplotData prepare_attribute_crossplot(std::span<const float> plane,
                                                   std::int64_t n_samples,
                                                   std::int64_t n_traces,
                                                   double sample_interval_s,
                                                   AlgorithmResolver resolver) {
    AttributeCrossplotData data;
    if (plane.size() != static_cast<std::size_t>(n_samples * n_traces) ||
        n_samples <= 0 || n_traces <= 0 || !(sample_interval_s > 0.0)) {
        data.diagnostic = "invalid plane shape or sample interval";
        return data;
    }
    std::vector<float> frequency;
    std::vector<float> envelope;
    std::string diagnostic;
    if (!run_trace_kernel("seismic.instantaneous_frequency", plane, n_samples, n_traces,
                          sample_interval_s, resolver, frequency, diagnostic)) {
        data.diagnostic = diagnostic;
        return data;
    }
    if (!run_trace_kernel("seismic.envelope", plane, n_samples, n_traces,
                          sample_interval_s, resolver, envelope, diagnostic)) {
        data.diagnostic = diagnostic;
        return data;
    }
    // Worker parity: step = max(1, size // 5000) over the flattened arrays.
    const std::size_t step = std::max<std::size_t>(
        1, envelope.size() / 5000); // Python int division then max(1, .)
    for (std::size_t i = 0; i < frequency.size() && i < envelope.size(); i += step) {
        data.frequency_hz.push_back(frequency[i]);
        data.envelope.push_back(envelope[i]);
    }
    data.x_limits = percentile_axis_limits(data.frequency_hz);
    data.y_limits = percentile_axis_limits(data.envelope);
    data.ok = true;
    return data;
}

AxisLimits percentile_axis_limits(std::span<const float> values) {
    std::vector<double> finite;
    finite.reserve(values.size());
    for (const float v : values) {
        if (std::isfinite(v)) {
            finite.push_back(static_cast<double>(v));
        }
    }
    AxisLimits limits;
    limits.lo = percentile_of(finite, 1.0);
    limits.hi = percentile_of(finite, 99.0);
    if (!std::isfinite(limits.lo) || !std::isfinite(limits.hi) || !(limits.hi > limits.lo)) {
        limits.hi = limits.lo + 1.0; // CrossplotCanvas degenerate guard
        if (!std::isfinite(limits.lo)) {
            limits.lo = 0.0;
            limits.hi = 1.0;
        }
    }
    return limits;
}

} // namespace pwb::seismic_viewer::crossplot
