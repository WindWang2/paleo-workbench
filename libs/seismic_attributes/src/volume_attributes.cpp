// S-line volume-structural attribute kernels: sweetness, relative_impedance,
// dip_il, dip_xl, dip_azimuth, curvature_mean. Ported symbol-for-symbol from
// the geoviz oracle (geo-viz-engine@08851951, geoviz_seismic/attributes.py —
// compute_sweetness / compute_relative_impedance / compute_dip /
// compute_azimuth / _compute_slope / compute_curvature(kind="mean")); no new
// algorithms. Semantics frozen in cpp-seismic-native-stack v3-contracts §2.
//
// Parity notes:
//   * Sweetness composes the float32 OUTPUTS of the envelope and
//     instantaneous-frequency chains (the oracle astype(float32)s each
//     intermediate), then freq_safe = |freq| < 1e-6 ? 1e-6 : |freq| and
//     env / sqrt(freq_safe) in float32.
//   * relative_impedance is numpy's float32 cumsum: sequential float32
//     accumulation, NaN poisons the rest of the trace.
//   * dip / curvature chains replicate numpy float32 gradient arithmetic
//     (NEP 50 weak scalars): f32(spacing) edge, f32(2*spacing) central.
//   * curvature smoothing is scipy uniform_filter(size=2w+1, mode="reflect")
//     = symmetric-fold sliding mean, computed as a float64 running sum per
//     axis pass with a float32 round between passes (same protocol the
//     E-line RMS kernel validated against the pinned oracle).

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <limits>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#include <pwb/science/registry.hpp>

#include <pwb/seismic_attributes/attributes.hpp>

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
using detail::gradient_f32_line;
using detail::gradient_spacing1;
using detail::kMaxHalfWindow;
using detail::kTwoPi;
using detail::symmetric_index;
using detail::unwrap_phase;
using detail::utc_now_iso;

enum class VolumeKind { sweetness, relative_impedance, dip_il, dip_xl,
                         dip_azimuth, curvature_mean };

struct VolumeKindInfo {
    const char* algorithm_id;
    const char* output_name;
    const char* output_unit;
    const char* display_name;
};

constexpr VolumeKindInfo volume_kind_info(VolumeKind kind) {
    switch (kind) {
    case VolumeKind::sweetness:
        return {"seismic.sweetness", "sweetness", "", "Sweetness"};
    case VolumeKind::relative_impedance:
        return {"seismic.relative_impedance", "relative_impedance", "",
                "Relative acoustic impedance"};
    case VolumeKind::dip_il:
        return {"seismic.dip_il", "dip_il", "rad", "Apparent dip (inline)"};
    case VolumeKind::dip_xl:
        return {"seismic.dip_xl", "dip_xl", "rad",
                "Apparent dip (crossline)"};
    case VolumeKind::dip_azimuth:
        return {"seismic.dip_azimuth", "dip_azimuth", "rad",
                "Structural azimuth"};
    case VolumeKind::curvature_mean:
        return {"seismic.curvature_mean", "curvature_mean", "",
                "Mean curvature (slope-gradient method)"};
    }
    return {"", "", "", ""};
}

struct NumberParam {
    const char* name;
    double default_value;
    const char* unit;
};

// Per-kind parameter tables (defaults = the production KERNELS table).
constexpr NumberParam sweetness_params[] = {
    {"sample_interval", 1.0, "s"}};
constexpr NumberParam dip_params[] = {
    {"dt", 1.0, "s"}, {"dx_il", 1.0, "m"}, {"dx_xl", 1.0, "m"}};
constexpr char const* curvature_params[] = {"win_il", "win_xl", "win_t"};

// One symmetric-fold sliding mean along ONE axis of a packed (ni, nc, ns)
// f32 volume, between two buffers. scipy uniform_filter(mode="reflect")
// parity: float64 running sum (sequential (s - oldest) + newest), float32
// round after the pass. window = 2*half + 1. `base_of` maps a line index
// (enumerating the (n_lines) lines parallel to the axis in any order) to
// the buffer address of that line's first element.
void sliding_mean_axis(const float* src, float* dst, std::int64_t n_along,
                       std::int64_t n_lines,
                       const std::function<std::int64_t(std::int64_t)>& base_of,
                       std::int64_t stride_along, std::int64_t half) {
    const std::int64_t window = 2 * half + 1;
    const std::size_t padded_len =
        static_cast<std::size_t>(n_along + 2 * half);
    std::vector<double> padded(padded_len);
    for (std::int64_t line = 0; line < n_lines; ++line) {
        const std::int64_t base = base_of(line);
        // Padded fetch with symmetric folding (scipy's "reflect"); the axis
        // has stride_along between consecutive elements.
        for (std::size_t j = 0; j < padded_len; ++j) {
            const std::int64_t idx = symmetric_index(
                static_cast<std::int64_t>(j) - half, n_along);
            padded[j] =
                static_cast<double>(src[base + idx * stride_along]);
        }
        double sum = 0.0;
        for (std::int64_t j = 0; j < window; ++j) {
            sum += padded[static_cast<std::size_t>(j)];
        }
        for (std::int64_t t = 0; t < n_along; ++t) {
            if (t > 0) {
                sum = (sum - padded[static_cast<std::size_t>(t - 1)])
                      + padded[static_cast<std::size_t>(t + window - 1)];
            }
            dst[base + t * stride_along] =
                static_cast<float>(sum / static_cast<double>(window));
        }
    }
}

// float32 gradient of a packed volume along axis `axis` (0/1/2) with the
// f64 spacing scalar cast per numpy NEP 50. src == dst is allowed ONLY via
// the scratch copy the caller manages; here they must differ.
void gradient_axis_f32(const std::vector<float>& src, std::vector<float>& dst,
                       std::int64_t ni, std::int64_t nc, std::int64_t ns,
                       std::size_t axis, double spacing) {
    const std::array<std::int64_t, 3> shape{ni, nc, ns};
    const std::array<std::int64_t, 3> strides{nc * ns, ns, 1};
    const std::int64_t n = shape[axis];
    const std::int64_t lines = (ni * nc * ns) / n;
    std::vector<float> line(static_cast<std::size_t>(n));
    std::vector<float> out_line(static_cast<std::size_t>(n));
    for (std::int64_t line_idx = 0; line_idx < lines; ++line_idx) {
        // Decompose line_idx into coordinates of the other two axes.
        std::int64_t rest = line_idx;
        std::array<std::int64_t, 3> coord{0, 0, 0};
        for (std::size_t a = 0; a < 3; ++a) {
            if (a != axis) {
                coord[a] = rest % shape[a];
                rest /= shape[a];
            }
        }
        const std::int64_t base = coord[0] * strides[0] + coord[1] * strides[1]
                                  + coord[2] * strides[2];
        const std::int64_t step = strides[axis];
        for (std::int64_t i = 0; i < n; ++i) {
            line[static_cast<std::size_t>(i)] =
                src[static_cast<std::size_t>(base + i * step)];
        }
        gradient_f32_line(line.data(), spacing, out_line.data(),
                          static_cast<std::size_t>(n));
        for (std::int64_t i = 0; i < n; ++i) {
            dst[static_cast<std::size_t>(base + i * step)] =
                out_line[static_cast<std::size_t>(i)];
        }
    }
}

// Computes (dip_il, dip_xl) float32 volumes exactly like the oracle's
// compute_dip over a packed (ni, nc, ns) input.
void compute_dip_volumes(const std::vector<float>& vol, std::int64_t ni,
                         std::int64_t nc, std::int64_t ns, double dt,
                         double dx_il, double dx_xl, std::vector<float>& dip_il,
                         std::vector<float>& dip_xl) {
    std::vector<float> grad_il(vol.size());
    std::vector<float> grad_xl(vol.size());
    std::vector<float> grad_t(vol.size());
    gradient_axis_f32(vol, grad_il, ni, nc, ns, 0, dx_il);
    gradient_axis_f32(vol, grad_xl, ni, nc, ns, 1, dx_xl);
    gradient_axis_f32(vol, grad_t, ni, nc, ns, 2, dt);
    dip_il.resize(vol.size());
    dip_xl.resize(vol.size());
    constexpr float kTiny = 1e-10f;
    for (std::size_t i = 0; i < vol.size(); ++i) {
        const float gt = std::fabs(grad_t[i]) < kTiny ? kTiny : grad_t[i];
        dip_il[i] = std::atan(grad_il[i] / gt);
        dip_xl[i] = std::atan(grad_xl[i] / gt);
    }
}

// Shared compute body for the dip family (the azimuth variant post-processes
// the two dip volumes).
Result<AlgorithmResultV1> run_dip_family(const AlgorithmRequestV1& request,
                                         VolumeKind kind, double dt,
                                         double dx_il, double dx_xl,
                                         const VolumeView& input,
                                         const std::string& build_identity,
                                         const AlgorithmDescriptor& descriptor,
                                         ProgressSink progress,
                                         std::stop_token stop) {
    const std::chrono::steady_clock::time_point start =
        std::chrono::steady_clock::now();
    const std::string started_utc = utc_now_iso();
    const std::int64_t ni = input.shape[0];
    const std::int64_t nc = input.shape[1];
    const std::int64_t ns = input.shape[2];
    const std::array<std::int64_t, 3> strides = input.effective_strides();

    // Materialise the input in canonical order (values unchanged — float32
    // copy). The dip chain is a float32 numpy chain end to end.
    std::vector<float> vol(static_cast<std::size_t>(ni * nc * ns));
    for (std::int64_t il = 0; il < ni; ++il) {
        if (stop.stop_requested()) {
            return TaskCancelled{"inlines " + std::to_string(il) + "/" +
                                 std::to_string(ni)};
        }
        for (std::int64_t xl = 0; xl < nc; ++xl) {
            const std::int64_t base =
                strides[0] * il + strides[1] * xl + strides[2] * 0;
            float* dst = &vol[static_cast<std::size_t>((il * nc + xl) * ns)];
            for (std::int64_t t = 0; t < ns; ++t) {
                dst[t] = input.data[base + strides[2] * t];
            }
        }
    }

    std::vector<float> dip_il;
    std::vector<float> dip_xl;
    compute_dip_volumes(vol, ni, nc, ns, dt, dx_il, dx_xl, dip_il, dip_xl);

    auto output_storage = std::make_shared<std::vector<float>>(
        static_cast<std::size_t>(ni * nc * ns));
    if (kind == VolumeKind::dip_azimuth) {
        // compute_azimuth: atan2(dip_xl, dip_il), wrapped to [0, 2*pi).
        for (std::size_t i = 0; i < output_storage->size(); ++i) {
            double az = std::atan2(static_cast<double>(dip_xl[i]),
                                   static_cast<double>(dip_il[i]));
            if (az < 0.0) {
                az += kTwoPi;
            }
            (*output_storage)[i] = static_cast<float>(az);
        }
    } else {
        const std::vector<float>& selected =
            kind == VolumeKind::dip_il ? dip_il : dip_xl;
        *output_storage = selected;
    }

    const std::chrono::steady_clock::time_point finish =
        std::chrono::steady_clock::now();
    AlgorithmResultV1 result;
    result.request_id = request.request_id;
    VolumeView output_view;
    output_view.data = output_storage->data();
    output_view.shape = input.shape;
    output_view.strides = {nc * ns, ns, 1};
    output_view.lifetime = output_storage;
    const VolumeKindInfo info = volume_kind_info(kind);
    ProducedVolume produced;
    produced.name = info.output_name;
    produced.volume = output_view;
    produced.unit = info.output_unit;
    result.outputs.push_back(std::move(produced));

    ProvenanceRecord& provenance = result.provenance;
    provenance.algorithm_id = descriptor.algorithm_id;
    provenance.algorithm_version = descriptor.version;
    provenance.build_identity = build_identity;
    provenance.params_json = request.params_json;
    provenance.input_refs = request.input_refs;
    provenance.started_utc = started_utc;
    provenance.finished_utc = utc_now_iso();
    provenance.approximate = false;
    provenance.wall_time_ms = static_cast<std::uint64_t>(
        std::chrono::duration_cast<std::chrono::milliseconds>(finish - start)
            .count());
    if (progress) {
        progress(ProgressReport{1.0, "done"});
    }
    return result;
}

class VolumeAttributeAlgorithm final : public IAlgorithm {
public:
    VolumeAttributeAlgorithm(VolumeKind kind, std::string build_identity)
        : kind_(kind),
          build_identity_(std::move(build_identity)),
          descriptor_{} {
        const VolumeKindInfo info = volume_kind_info(kind);
        descriptor_.algorithm_id = info.algorithm_id;
        descriptor_.version = "1.0.0";
        descriptor_.display_name = info.display_name;
        descriptor_.family = "seismic_attribute";
        descriptor_.inputs.push_back(
            PortSpec{"volume", PortKind::volume_f32, "", true});
        descriptor_.outputs.push_back(PortSpec{info.output_name,
                                               PortKind::volume_f32,
                                               info.output_unit, true});
        auto add_number = [this](const char* name, double default_value,
                                 const char* unit) {
            ParamSpec spec;
            spec.name = name;
            spec.type = ParamSpec::Type::number;
            spec.unit = unit;
            spec.default_json = std::to_string(default_value);
            descriptor_.parameters.push_back(spec);
        };
        auto add_integer = [this](const char* name, int default_value) {
            ParamSpec spec;
            spec.name = name;
            spec.type = ParamSpec::Type::integer;
            spec.minimum = 0;
            spec.maximum = static_cast<double>(kMaxHalfWindow);
            spec.default_json = std::to_string(default_value);
            descriptor_.parameters.push_back(spec);
        };
        switch (kind_) {
        case VolumeKind::sweetness:
            for (const NumberParam& p : sweetness_params) {
                add_number(p.name, p.default_value, p.unit);
            }
            break;
        case VolumeKind::dip_il:
        case VolumeKind::dip_xl:
        case VolumeKind::dip_azimuth:
            for (const NumberParam& p : dip_params) {
                add_number(p.name, p.default_value, p.unit);
            }
            break;
        case VolumeKind::curvature_mean:
            add_integer(curvature_params[0], 3);
            add_integer(curvature_params[1], 3);
            add_integer(curvature_params[2], 3);
            break;
        case VolumeKind::relative_impedance:
            break;
        }
        descriptor_.supports_cancel = true;
        descriptor_.deterministic = true;
        descriptor_.approximate = false;
        descriptor_.build_identity = build_identity_;
    }

    [[nodiscard]] const AlgorithmDescriptor& descriptor() const override {
        return descriptor_;
    }

    Result<AlgorithmResultV1> run(const AlgorithmRequestV1& request,
                                  ProgressSink progress,
                                  std::stop_token stop) override {
        const std::vector<Diagnostic> problems =
            pwb::science::validate_request(descriptor_, request);
        if (!problems.empty()) {
            return AlgorithmError{problems};
        }
        switch (kind_) {
        case VolumeKind::sweetness:
            return run_sweetness(request, progress, stop);
        case VolumeKind::relative_impedance:
            return run_relative_impedance(request, progress, stop);
        case VolumeKind::dip_il:
        case VolumeKind::dip_xl:
        case VolumeKind::dip_azimuth:
            return run_dip(request, progress, stop);
        case VolumeKind::curvature_mean:
            return run_curvature(request, progress, stop);
        }
        return AlgorithmError{{Diagnostic{"algorithm.kind.unknown",
                                          "unknown kernel kind", "error"}}};
    }

private:
    [[nodiscard]] Result<std::array<double, 3>> number_params(
        const AlgorithmRequestV1& request, std::initializer_list<const char*> names) const {
        std::array<double, 3> values{1.0, 1.0, 1.0};
        std::size_t slot = 0;
        for (const char* name : names) {
            for (const ParamSpec& spec : descriptor_.parameters) {
                if (spec.name == name) {
                    const auto value = pwb::science::request_param_number(
                        request, spec);
                    if (!value.has_value()) {
                        return AlgorithmError{value.error().diagnostics};
                    }
                    if (!(value.value() > 0.0)) {
                        return AlgorithmError{{Diagnostic{
                            std::string("param.") + name + ".not_positive",
                            std::string(name) + " must be > 0; got "
                                + std::to_string(value.value()),
                            "error"}}};
                    }
                    values[slot] = value.value();
                }
            }
            ++slot;
        }
        return values;
    }

    Result<AlgorithmResultV1> run_sweetness(const AlgorithmRequestV1& request,
                                            ProgressSink progress,
                                            std::stop_token stop) {
        const auto params = number_params(request, {"sample_interval"});
        if (!params.has_value()) {
            return AlgorithmError{params.error().diagnostics};
        }
        const double sample_interval = params.value()[0];
        const VolumeView& input = request.input_volumes[0];
        const std::int64_t n_il = input.shape[0];
        const std::int64_t n_xl = input.shape[1];
        const std::int64_t n_t = input.shape[2];
        if (n_t < 2) {
            return AlgorithmError{{Diagnostic{
                "input.sample_count.too_small",
                "sweetness needs at least 2 samples per trace (the "
                "frequency chain gradients along time); got "
                    + std::to_string(n_t),
                "error"}}};
        }
        const std::array<std::int64_t, 3> strides = input.effective_strides();
        const std::int64_t total_traces = n_il * n_xl;
        const std::size_t trace_len = static_cast<std::size_t>(n_t);

        const std::chrono::steady_clock::time_point start =
            std::chrono::steady_clock::now();
        auto output_storage = std::make_shared<std::vector<float>>(
            static_cast<std::size_t>(total_traces * n_t), 0.0f);

        const std::int64_t batch = batch_trace_count(n_t);
        std::vector<std::complex<double>> complex_buffer(
            static_cast<std::size_t>(batch) * trace_len);
        std::vector<double> phase(trace_len);
        std::vector<double> unwrapped(trace_len);
        std::vector<double> grad(trace_len);
        constexpr float kFreqFloor = 1e-6f;
        constexpr double kInvTwoPi = 1.0 / kTwoPi;

        std::int64_t completed = 0;
        for (std::int64_t first = 0; first < total_traces; first += batch) {
            if (stop.stop_requested()) {
                return TaskCancelled{"traces " + std::to_string(completed)
                                     + "/" + std::to_string(total_traces)};
            }
            const std::int64_t last = std::min(first + batch, total_traces);
            const std::size_t n_batch = static_cast<std::size_t>(last - first);
            for (std::size_t b = 0; b < n_batch; ++b) {
                const std::int64_t trace = first + static_cast<std::int64_t>(b);
                const std::int64_t base =
                    strides[0] * (trace / n_xl) + strides[1] * (trace % n_xl);
                std::complex<double>* row =
                    complex_buffer.data() + b * trace_len;
                for (std::size_t t = 0; t < trace_len; ++t) {
                    row[t] = {static_cast<double>(
                                  input.data[base
                                             + strides[2]
                                                   * static_cast<std::int64_t>(
                                                       t)]),
                              0.0};
                }
            }
            analytic_signal(complex_buffer, trace_len, n_batch);
            for (std::size_t b = 0; b < n_batch; ++b) {
                const std::int64_t trace = first + static_cast<std::int64_t>(b);
                const std::complex<double>* row =
                    complex_buffer.data() + b * trace_len;
                float* dst = output_storage->data()
                             + static_cast<std::size_t>(trace) * trace_len;
                // Pass 1: the float32 envelope and frequency outputs.
                for (std::size_t t = 0; t < trace_len; ++t) {
                    phase[t] = std::atan2(row[t].imag(), row[t].real());
                }
                unwrap_phase(phase.data(), unwrapped.data(), trace_len);
                gradient_spacing1(unwrapped.data(), sample_interval,
                                  grad.data(), trace_len);
                for (std::size_t t = 0; t < trace_len; ++t) {
                    const float env = static_cast<float>(std::abs(row[t]));
                    const float freq = static_cast<float>(grad[t] * kInvTwoPi);
                    // compute_sweetness: clamp |freq| below 1e-6, then the
                    // float32 ratio env / sqrt(freq_safe). NaN freq (poisoned
                    // phase) fails the clamp comparison and passes through.
                    const float abs_freq = std::fabs(freq);
                    const float freq_safe =
                        abs_freq < kFreqFloor ? kFreqFloor : abs_freq;
                    dst[t] = env / std::sqrt(freq_safe);
                }
            }
            completed = last;
            if (progress) {
                progress(ProgressReport{
                    static_cast<double>(completed)
                        / static_cast<double>(total_traces),
                    "traces"});
            }
        }

        const std::chrono::steady_clock::time_point finish =
            std::chrono::steady_clock::now();
        AlgorithmResultV1 result;
        result.request_id = request.request_id;
        VolumeView output_view;
        output_view.data = output_storage->data();
        output_view.shape = input.shape;
        output_view.strides = {n_xl * n_t, n_t, 1};
        output_view.lifetime = output_storage;
        const VolumeKindInfo info = volume_kind_info(kind_);
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
        provenance.started_utc = utc_now_iso();
        provenance.finished_utc = utc_now_iso();
        provenance.approximate = false;
        provenance.wall_time_ms = static_cast<std::uint64_t>(
            std::chrono::duration_cast<std::chrono::milliseconds>(finish
                                                                  - start)
                .count());
        result.diagnostics.push_back(Diagnostic{
            "algorithm.sweetness_semantics",
            "sweetness = envelope / sqrt(max(|instantaneous_frequency|, "
            "1e-6)); sample_interval=" + std::to_string(sample_interval) + " s",
            "info"});
        if (progress) {
            progress(ProgressReport{1.0, "done"});
        }
        return result;
    }

    Result<AlgorithmResultV1> run_relative_impedance(
        const AlgorithmRequestV1& request, ProgressSink progress,
        std::stop_token stop) {
        const VolumeView& input = request.input_volumes[0];
        const std::int64_t n_il = input.shape[0];
        const std::int64_t n_xl = input.shape[1];
        const std::int64_t n_t = input.shape[2];
        const std::array<std::int64_t, 3> strides = input.effective_strides();
        const auto start = std::chrono::steady_clock::now();
        auto output_storage = std::make_shared<std::vector<float>>(
            static_cast<std::size_t>(n_il * n_xl * n_t), 0.0f);
        // numpy float32 cumsum: sequential accumulation in float32; NaN
        // poisons the rest of the trace; -0.0 preserved by IEEE addition.
        for (std::int64_t il = 0; il < n_il; ++il) {
            if (stop.stop_requested()) {
                return TaskCancelled{"inlines " + std::to_string(il) + "/" +
                                     std::to_string(n_il)};
            }
            for (std::int64_t xl = 0; xl < n_xl; ++xl) {
                const std::int64_t base = strides[0] * il + strides[1] * xl;
                const float* src = input.data + base;
                float* dst = &(*output_storage)[static_cast<std::size_t>(
                    (il * n_xl + xl) * n_t)];
                float acc = 0.0f;
                for (std::int64_t t = 0; t < n_t; ++t) {
                    acc += src[strides[2] * t];
                    dst[t] = acc;
                }
            }
        }
        const auto finish = std::chrono::steady_clock::now();
        AlgorithmResultV1 result;
        result.request_id = request.request_id;
        VolumeView output_view;
        output_view.data = output_storage->data();
        output_view.shape = input.shape;
        output_view.strides = {n_xl * n_t, n_t, 1};
        output_view.lifetime = output_storage;
        const VolumeKindInfo info = volume_kind_info(kind_);
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
        provenance.started_utc = utc_now_iso();
        provenance.finished_utc = utc_now_iso();
        provenance.approximate = false;
        provenance.wall_time_ms = static_cast<std::uint64_t>(
            std::chrono::duration_cast<std::chrono::milliseconds>(finish
                                                                  - start)
                .count());
        if (progress) {
            progress(ProgressReport{1.0, "done"});
        }
        return result;
    }

    Result<AlgorithmResultV1> run_dip(const AlgorithmRequestV1& request,
                                      ProgressSink progress,
                                      std::stop_token stop) {
        const auto params =
            number_params(request, {"dt", "dx_il", "dx_xl"});
        if (!params.has_value()) {
            return AlgorithmError{params.error().diagnostics};
        }
        const VolumeView& input = request.input_volumes[0];
        for (std::size_t axis = 0; axis < 3; ++axis) {
            if (input.shape[axis] < 2) {
                return AlgorithmError{{Diagnostic{
                    "input.axis.too_small",
                    "dip attributes need at least 2 samples on every axis "
                    "(np.gradient raises below that); got "
                        + std::to_string(input.shape[axis]) + " on axis "
                        + std::to_string(axis),
                    "error"}}};
            }
        }
        auto result = run_dip_family(request, kind_, params.value()[0],
                                     params.value()[1], params.value()[2],
                                     input, build_identity_, descriptor_,
                                     std::move(progress), std::move(stop));
        return result;
    }

    Result<AlgorithmResultV1> run_curvature(const AlgorithmRequestV1& request,
                                            ProgressSink progress,
                                            std::stop_token stop) {
        std::array<std::int64_t, 3> wins{3, 3, 3};
        std::size_t slot = 0;
        for (const char* name : curvature_params) {
            for (const ParamSpec& spec : descriptor_.parameters) {
                if (spec.name == name) {
                    const auto value =
                        pwb::science::request_param_integer(request, spec);
                    if (!value.has_value()) {
                        return AlgorithmError{value.error().diagnostics};
                    }
                    wins[slot] = value.value();
                }
            }
            ++slot;
        }
        const VolumeView& input = request.input_volumes[0];
        const std::int64_t ni = input.shape[0];
        const std::int64_t nc = input.shape[1];
        const std::int64_t ns = input.shape[2];
        for (std::size_t axis = 0; axis < 3; ++axis) {
            if (input.shape[axis] < 2) {
                return AlgorithmError{{Diagnostic{
                    "input.axis.too_small",
                    "curvature needs at least 2 samples on every axis "
                    "(np.gradient raises below that); got "
                        + std::to_string(input.shape[axis]) + " on axis "
                        + std::to_string(axis),
                    "error"}}};
            }
        }
        const auto start = std::chrono::steady_clock::now();
        const std::array<std::int64_t, 3> strides = input.effective_strides();

        // Materialise float32 input in canonical order.
        std::vector<float> vol(static_cast<std::size_t>(ni * nc * ns));
        for (std::int64_t il = 0; il < ni; ++il) {
            for (std::int64_t xl = 0; xl < nc; ++xl) {
                const std::int64_t base =
                    strides[0] * il + strides[1] * xl;
                float* dst = &vol[static_cast<std::size_t>((il * nc + xl) * ns)];
                for (std::int64_t t = 0; t < ns; ++t) {
                    dst[t] = input.data[base + strides[2] * t];
                }
            }
        }
        if (stop.stop_requested()) {
            return TaskCancelled{"input materialisation"};
        }

        // 1. Slopes: spatial_grad / grad_t_safe in float32 (unit spacing —
        // the oracle's _compute_slope gradients carry no physical spacing).
        std::vector<float> grad_il(vol.size());
        std::vector<float> grad_xl(vol.size());
        std::vector<float> grad_t(vol.size());
        gradient_axis_f32(vol, grad_il, ni, nc, ns, 0, 1.0);
        gradient_axis_f32(vol, grad_xl, ni, nc, ns, 1, 1.0);
        gradient_axis_f32(vol, grad_t, ni, nc, ns, 2, 1.0);
        std::vector<float> slope_il(vol.size());
        std::vector<float> slope_xl(vol.size());
        constexpr float kTiny = 1e-10f;
        for (std::size_t i = 0; i < vol.size(); ++i) {
            const float gt = std::fabs(grad_t[i]) < kTiny ? kTiny : grad_t[i];
            slope_il[i] = grad_il[i] / gt;
            slope_xl[i] = grad_xl[i] / gt;
        }

        // 2. Smooth the slopes: uniform_filter(size=2w+1, mode="reflect")
        // per axis, float64 running sums, float32 between passes. Line
        // bases (packed il*nc*ns + xl*ns + t): axis0 lines are (xl, t) ->
        // base = xl*ns + t; axis1 lines are (il, t) -> base =
        // il*nc*ns + t; axis2 lines are (il, xl) -> base =
        // il*nc*ns + xl*ns.
        auto smooth_all = [&](std::vector<float>& slope) {
            std::vector<float> scratch(vol.size());
            sliding_mean_axis(
                slope.data(), scratch.data(), ni, nc * ns,
                [](std::int64_t line) { return line; }, nc * ns, wins[0]);
            sliding_mean_axis(
                scratch.data(), slope.data(), nc, ni * ns,
                [nc, ns](std::int64_t line) {
                    return (line / ns) * (nc * ns) + (line % ns);
                },
                ns, wins[1]);
            sliding_mean_axis(
                slope.data(), scratch.data(), ns, ni * nc,
                [nc, ns](std::int64_t line) {
                    return (line / nc) * (nc * ns) + (line % nc) * ns;
                },
                1, wins[2]);
            slope.swap(scratch);
        };
        smooth_all(slope_il);
        smooth_all(slope_xl);
        if (stop.stop_requested()) {
            return TaskCancelled{"slope smoothing"};
        }

        // 3. Second derivatives (float32 chains).
        std::vector<float> d2_il(vol.size());
        std::vector<float> d2_xl(vol.size());
        std::vector<float> d2_il_xl(vol.size());
        {
            std::vector<float> tmp(vol.size());
            gradient_axis_f32(slope_il, tmp, ni, nc, ns, 0, 1.0);
            gradient_axis_f32(tmp, d2_il, ni, nc, ns, 0, 1.0);
            gradient_axis_f32(slope_xl, tmp, ni, nc, ns, 1, 1.0);
            gradient_axis_f32(tmp, d2_xl, ni, nc, ns, 1, 1.0);
            gradient_axis_f32(slope_il, tmp, ni, nc, ns, 1, 1.0);
            gradient_axis_f32(tmp, d2_il_xl, ni, nc, ns, 0, 1.0);
        }

        // 4. mean curvature = (d2_il + d2_xl) / 2 (float32 arithmetic).
        auto output_storage = std::make_shared<std::vector<float>>(vol.size());
        for (std::size_t i = 0; i < output_storage->size(); ++i) {
            (*output_storage)[i] = (d2_il[i] + d2_xl[i]) / 2.0f;
        }

        const auto finish = std::chrono::steady_clock::now();
        AlgorithmResultV1 result;
        result.request_id = request.request_id;
        VolumeView output_view;
        output_view.data = output_storage->data();
        output_view.shape = input.shape;
        output_view.strides = {nc * ns, ns, 1};
        output_view.lifetime = output_storage;
        ProducedVolume produced;
        produced.name = "curvature_mean";
        produced.volume = output_view;
        produced.unit = "";
        result.outputs.push_back(std::move(produced));
        ProvenanceRecord& provenance = result.provenance;
        provenance.algorithm_id = descriptor_.algorithm_id;
        provenance.algorithm_version = descriptor_.version;
        provenance.build_identity = build_identity_;
        provenance.params_json = request.params_json;
        provenance.input_refs = request.input_refs;
        provenance.started_utc = utc_now_iso();
        provenance.finished_utc = utc_now_iso();
        provenance.approximate = false;
        provenance.wall_time_ms = static_cast<std::uint64_t>(
            std::chrono::duration_cast<std::chrono::milliseconds>(finish
                                                                  - start)
                .count());
        result.diagnostics.push_back(Diagnostic{
            "algorithm.curvature_semantics",
            "mean curvature via slope-gradient method: slopes are "
            "index-unit (unit spacing), smoothed with uniform_filter "
            "(reflect), then second gradients; win=("
                + std::to_string(wins[0]) + ", " + std::to_string(wins[1])
                + ", " + std::to_string(wins[2]) + ")",
            "info"});
        if (progress) {
            progress(ProgressReport{1.0, "done"});
        }
        return result;
    }

    VolumeKind kind_;
    std::string build_identity_;
    AlgorithmDescriptor descriptor_;
};

}  // namespace

std::unique_ptr<IAlgorithm> make_sweetness(std::string build_identity) {
    return std::make_unique<VolumeAttributeAlgorithm>(VolumeKind::sweetness,
                                                      std::move(build_identity));
}

std::unique_ptr<IAlgorithm> make_relative_impedance(std::string build_identity) {
    return std::make_unique<VolumeAttributeAlgorithm>(
        VolumeKind::relative_impedance, std::move(build_identity));
}

std::unique_ptr<IAlgorithm> make_dip_inline(std::string build_identity) {
    return std::make_unique<VolumeAttributeAlgorithm>(VolumeKind::dip_il,
                                                      std::move(build_identity));
}

std::unique_ptr<IAlgorithm> make_dip_crossline(std::string build_identity) {
    return std::make_unique<VolumeAttributeAlgorithm>(VolumeKind::dip_xl,
                                                      std::move(build_identity));
}

std::unique_ptr<IAlgorithm> make_dip_azimuth(std::string build_identity) {
    return std::make_unique<VolumeAttributeAlgorithm>(VolumeKind::dip_azimuth,
                                                      std::move(build_identity));
}

std::unique_ptr<IAlgorithm> make_curvature_mean(std::string build_identity) {
    return std::make_unique<VolumeAttributeAlgorithm>(
        VolumeKind::curvature_mean, std::move(build_identity));
}

}  // namespace pwb::seismic_attributes
