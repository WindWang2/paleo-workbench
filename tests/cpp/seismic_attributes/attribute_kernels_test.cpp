// Oracle parity + analytic invariants for the four seismic attributes.
//
// Frozen case table mirrors tests/cpp/seismic_attributes/fixtures/<case>/
// manifest.json (the audit artifact): shapes, dt and half-windows must stay
// in sync with oracle/generate_attribute_fixtures.py. Comparison rules and
// tolerances are frozen in docs/development/cpp-seismic-attributes/
// v3-contracts.md §4 — a failure is fixed in the algorithm or the mapping,
// never by relaxing these numbers.

#include "fixture_io.hpp"
#include "pwb_test.hpp"

#include <array>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <map>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#include <pwb/science/algorithm.hpp>
#include <pwb/science/registry.hpp>
#include <pwb/science/types.hpp>
#include <pwb/seismic_attributes/attributes.hpp>

namespace {

using pwb::science::AlgorithmRegistry;
using pwb::science::AlgorithmRequestV1;
using pwb::science::AlgorithmResultV1;
using pwb::science::IAlgorithm;
using pwb::science::Result;
using pwb::science::VolumeView;

constexpr double kTwoPi = 6.283185307179586476925286766559;

struct ExpectedFile {
    const char* file;      // fixtures/<case>/<file>
    const char* kind;      // envelope | phase | freq | rms
    const char* algorithm_id;
    const char* param_name;  // nullptr when parameterless
    const char* param_value;
};

struct Case {
    const char* name;
    std::array<std::int64_t, 3> shape;
    std::vector<ExpectedFile> expected;
};

// Keep in sync with oracle/generate_attribute_fixtures.py.
const std::vector<Case>& cases() {
    static const std::vector<Case> table = {
        {"synth_mixed", {24, 20, 64},
         {{"expected_envelope.f32", "envelope", "seismic.envelope", nullptr, nullptr},
          {"expected_phase.f32", "phase", "seismic.instantaneous_phase", nullptr, nullptr},
          {"expected_freq.f32", "freq", "seismic.instantaneous_frequency",
           "sample_interval", "0.002"},
          {"expected_rms_w0.f32", "rms", "seismic.rms_amplitude", "window", "0"},
          {"expected_rms_w1.f32", "rms", "seismic.rms_amplitude", "window", "1"},
          {"expected_rms_w21.f32", "rms", "seismic.rms_amplitude", "window", "21"},
          {"expected_rms_w100.f32", "rms", "seismic.rms_amplitude", "window", "100"}}},
        {"synth_odd", {13, 17, 45},
         {{"expected_envelope.f32", "envelope", "seismic.envelope", nullptr, nullptr},
          {"expected_phase.f32", "phase", "seismic.instantaneous_phase", nullptr, nullptr},
          {"expected_freq.f32", "freq", "seismic.instantaneous_frequency",
           "sample_interval", "1.0"},
          {"expected_rms_w3.f32", "rms", "seismic.rms_amplitude", "window", "3"}}},
        {"synth_prime31", {6, 5, 31},
         {{"expected_envelope.f32", "envelope", "seismic.envelope", nullptr, nullptr},
          {"expected_phase.f32", "phase", "seismic.instantaneous_phase", nullptr, nullptr},
          {"expected_freq.f32", "freq", "seismic.instantaneous_frequency",
           "sample_interval", "0.002"}}},
        {"synth_nt2", {4, 3, 2},
         {{"expected_envelope.f32", "envelope", "seismic.envelope", nullptr, nullptr},
          {"expected_phase.f32", "phase", "seismic.instantaneous_phase", nullptr, nullptr},
          {"expected_freq.f32", "freq", "seismic.instantaneous_frequency",
           "sample_interval", "1.0"},
          {"expected_rms_w1.f32", "rms", "seismic.rms_amplitude", "window", "1"}}},
        {"synth_nt1", {4, 3, 1},
         {{"expected_envelope.f32", "envelope", "seismic.envelope", nullptr, nullptr},
          {"expected_phase.f32", "phase", "seismic.instantaneous_phase", nullptr, nullptr},
          {"expected_rms_w0.f32", "rms", "seismic.rms_amplitude", "window", "0"},
          {"expected_rms_w2.f32", "rms", "seismic.rms_amplitude", "window", "2"}}},
        {"zeros", {5, 5, 8},
         {{"expected_envelope.f32", "envelope", "seismic.envelope", nullptr, nullptr},
          {"expected_phase.f32", "phase", "seismic.instantaneous_phase", nullptr, nullptr},
          {"expected_freq.f32", "freq", "seismic.instantaneous_frequency",
           "sample_interval", "1.0"},
          {"expected_rms_w21.f32", "rms", "seismic.rms_amplitude", "window", "21"}}},
        {"constant_pos", {5, 5, 8},
         {{"expected_envelope.f32", "envelope", "seismic.envelope", nullptr, nullptr},
          {"expected_phase.f32", "phase", "seismic.instantaneous_phase", nullptr, nullptr},
          {"expected_freq.f32", "freq", "seismic.instantaneous_frequency",
           "sample_interval", "0.002"},
          {"expected_rms_w21.f32", "rms", "seismic.rms_amplitude", "window", "21"}}},
        {"constant_neg", {5, 5, 8},
         {{"expected_envelope.f32", "envelope", "seismic.envelope", nullptr, nullptr},
          {"expected_phase.f32", "phase", "seismic.instantaneous_phase", nullptr, nullptr},
          {"expected_freq.f32", "freq", "seismic.instantaneous_frequency",
           "sample_interval", "0.002"},
          {"expected_rms_w21.f32", "rms", "seismic.rms_amplitude", "window", "21"}}},
        {"impulse", {8, 8, 32},
         {{"expected_envelope.f32", "envelope", "seismic.envelope", nullptr, nullptr},
          {"expected_phase.f32", "phase", "seismic.instantaneous_phase", nullptr, nullptr},
          {"expected_freq.f32", "freq", "seismic.instantaneous_frequency",
           "sample_interval", "0.002"},
          {"expected_rms_w2.f32", "rms", "seismic.rms_amplitude", "window", "2"}}},
        {"sine_30hz", {4, 4, 256},
         {{"expected_envelope.f32", "envelope", "seismic.envelope", nullptr, nullptr},
          {"expected_phase.f32", "phase", "seismic.instantaneous_phase", nullptr, nullptr},
          {"expected_freq.f32", "freq", "seismic.instantaneous_frequency",
           "sample_interval", "0.00390625"},
          {"expected_rms_w10.f32", "rms", "seismic.rms_amplitude", "window", "10"}}},
        {"nan_inf", {8, 8, 16},
         {{"expected_envelope.f32", "envelope", "seismic.envelope", nullptr, nullptr},
          {"expected_phase.f32", "phase", "seismic.instantaneous_phase", nullptr, nullptr},
          {"expected_freq.f32", "freq", "seismic.instantaneous_frequency",
           "sample_interval", "0.002"},
          {"expected_rms_w2.f32", "rms", "seismic.rms_amplitude", "window", "2"}}},
        {"tiny_sgy_real", {8, 8, 32},
         {{"expected_envelope.f32", "envelope", "seismic.envelope", nullptr, nullptr},
          {"expected_phase.f32", "phase", "seismic.instantaneous_phase", nullptr, nullptr},
          {"expected_freq.f32", "freq", "seismic.instantaneous_frequency",
           "sample_interval", "0.002"},
          {"expected_rms_w21.f32", "rms", "seismic.rms_amplitude", "window", "21"},
          {"expected_rms_w0.f32", "rms", "seismic.rms_amplitude", "window", "0"},
          {"expected_rms_w100.f32", "rms", "seismic.rms_amplitude", "window", "100"}}},
    };
    return table;
}

struct CompareReport {
    std::size_t n{0};
    std::size_t nan_expected{0};
    std::size_t nan_actual{0};
    std::size_t mask_mismatch{0};
    std::size_t uncertain{0};   // amplitude-uncertain samples (phase/freq)
    double max_abs{0.0};
    double max_rel{0.0}; // over |expected| > 1e-6 (phase: circular max_abs)
    double max_abs_uncertain{0.0}; // reported, never asserted
};

// Per-element dual criterion |a-e| <= max(max_abs, max_rel*|e|); phase uses
// the circular difference wrapped to [-pi, pi]. `uncertain` marks samples
// where the oracle analytic amplitude is ~0 (per-trace floor 1e-6 * max
// envelope): there the phase is pure rounding noise in ANY implementation
// (proved on the impulse fixture, whose analytic signal has exact zeros —
// oracle float32 gives ~1e-9 noise angles, a float64 path ~1e-17), so those
// samples — and for frequency their +/-1 gradient neighbours, where unwrap
// chain offsets of 2*pi surface — are excluded from the assertion and
// REPORTED separately, never silently dropped.
bool compare_expected(const std::vector<float>& actual, const std::vector<float>& expected,
                      const std::string& kind, double max_abs_tol, double max_rel_tol,
                      const std::vector<bool>& uncertain, CompareReport& report) {
    if (actual.size() != expected.size()) {
        std::fprintf(stderr, "size mismatch: actual=%zu expected=%zu\n", actual.size(),
                     expected.size());
        return false;
    }
    report = CompareReport{};
    report.n = expected.size();
    bool ok = true;
    for (std::size_t i = 0; i < expected.size(); ++i) {
        const float e = expected[i];
        const float a = actual[i];
        const bool e_nan = std::isnan(e);
        const bool a_nan = std::isnan(a);
        if (e_nan) {
            ++report.nan_expected;
        }
        if (a_nan) {
            ++report.nan_actual;
        }
        const bool e_inf = std::isinf(e);
        const bool a_inf = std::isinf(a);
        if (e_nan || a_nan || e_inf || a_inf) {
            // NaN positions must match elementwise; Inf likewise (sign too).
            const bool match = e_nan == a_nan && e_inf == a_inf &&
                               (!e_inf || (e > 0) == (a > 0));
            if (!match) {
                ++report.mask_mismatch;
                ok = false;
            }
            continue;
        }
        double diff = std::fabs(static_cast<double>(a) - static_cast<double>(e));
        if (kind == "phase") {
            diff = std::fabs(std::remainder(static_cast<double>(a) - static_cast<double>(e),
                                            kTwoPi));
        }
        if (uncertain[i]) {
            ++report.uncertain;
            if (diff > report.max_abs_uncertain) {
                report.max_abs_uncertain = diff;
            }
            continue; // reported, not asserted
        }
        if (diff > report.max_abs) {
            report.max_abs = diff;
        }
        if (std::fabs(e) > 1e-6) {
            const double rel = diff / std::fabs(e);
            if (rel > report.max_rel) {
                report.max_rel = rel;
            }
        }
        const double allowed =
            std::max(max_abs_tol, max_rel_tol * std::fabs(static_cast<double>(e)));
        if (!(diff <= allowed)) {
            ok = false;
        }
    }
    return ok;
}

struct RunOutput {
    std::vector<float> values; // copy of the produced volume payload
    pwb::science::AlgorithmResultV1 result;
};

RunOutput run_attribute(const AlgorithmRegistry& registry, const std::string& algorithm_id,
                        const std::vector<float>& input,
                        const std::array<std::int64_t, 3>& shape,
                        const std::map<std::string, std::string>& params) {
    IAlgorithm* algorithm = registry.find(algorithm_id);
    PWB_CHECK_MSG(algorithm != nullptr, ("algorithm not registered: " + algorithm_id).c_str());
    AlgorithmRequestV1 request;
    request.algorithm_id = algorithm_id;
    request.algorithm_version = algorithm->descriptor().version;
    request.params_json = params;
    auto holder = std::make_shared<std::vector<float>>(input);
    VolumeView view;
    view.data = holder->data();
    view.shape = shape;
    view.strides = {0, 0, 0}; // packed C-order
    view.lifetime = holder;
    request.input_volumes.push_back(view);
    Result<pwb::science::AlgorithmResultV1> result = algorithm->run(request, nullptr, {});
    if (!result.has_value()) {
        if (result.is_error()) {
            std::string message = "algorithm error: " + result.error().diagnostics[0].code;
            PWB_FAIL(message.c_str());
        }
        PWB_FAIL("algorithm cancelled unexpectedly");
    }
    RunOutput out;
    out.result = std::move(result.value());
    PWB_CHECK(out.result.outputs.size() == 1);
    const VolumeView& produced = out.result.outputs[0].volume;
    out.values.assign(produced.data, produced.data + static_cast<std::size_t>(produced.size()));
    return out;
}

const AlgorithmRegistry& shared_registry() {
    static AlgorithmRegistry registry;
    static const bool registered = [] {
        const auto report =
            pwb::seismic_attributes::register_seismic_attributes(registry, "test-build");
        // S line: the registration covers all ten production kernels.
        return report.registered_ids.size() == 10 && report.rejection.empty();
    }();
    PWB_CHECK(registered);
    return registry;
}

std::string tolerance_line(const char* kind, const CompareReport& report, bool ok) {
    char buffer[640];
    std::snprintf(buffer, sizeof(buffer),
                  "%-10s n=%-7zu nan(exp/act)=%zu/%zu mask_mismatch=%zu "
                  "unc=%zu(max %.2e) max_abs=%.3e max_rel=%.3e -> %s",
                  kind, report.n, report.nan_expected, report.nan_actual,
                  report.mask_mismatch, report.uncertain, report.max_abs_uncertain,
                  report.max_abs, report.max_rel, ok ? "PASS" : "FAIL");
    return buffer;
}

} // namespace

TEST(fixtures_parity) {
    const AlgorithmRegistry& registry = shared_registry();
    const std::filesystem::path root = fixture_io::fixture_root();
    std::size_t total_checks = 0;
    std::size_t failed_checks = 0;
    for (const Case& scenario : cases()) {
        const std::vector<float> input =
            fixture_io::read_f32(root / scenario.name / "input.f32");
        PWB_CHECK_MSG(!input.empty(),
                      (std::string("missing input fixture: ") + scenario.name).c_str());
        // Amplitude reference for the phase/frequency uncertainty mask: the
        // oracle envelope, per trace floor 1e-6 * max(envelope of the trace).
        const std::vector<float> envelope =
            fixture_io::read_f32(root / scenario.name / "expected_envelope.f32");
        PWB_CHECK(envelope.size() == input.size());
        const std::size_t trace_len = static_cast<std::size_t>(scenario.shape[2]);
        std::vector<bool> phase_uncertain(input.size(), false);
        for (std::size_t i = 0; i < input.size(); i += trace_len) {
            float trace_max = 0.0f;
            for (std::size_t t = 0; t < trace_len; ++t) {
                trace_max = std::max(trace_max, envelope[i + t]);
            }
            const float floor_amp = 1e-6f * trace_max;
            for (std::size_t t = 0; t < trace_len; ++t) {
                phase_uncertain[i + t] = envelope[i + t] <= floor_amp;
            }
        }
        std::vector<bool> freq_uncertain(input.size(), false);
        for (std::size_t i = 0; i < input.size(); ++i) {
            if (phase_uncertain[i]) {
                freq_uncertain[i] = true;
                if (i % trace_len != 0) {
                    freq_uncertain[i - 1] = true;
                }
                if (i % trace_len != trace_len - 1) {
                    freq_uncertain[i + 1] = true;
                }
            }
        }
        const std::vector<bool> no_uncertain(input.size(), false);
        for (const ExpectedFile& check : scenario.expected) {
            const std::vector<float> expected =
                fixture_io::read_f32(root / scenario.name / check.file);
            PWB_CHECK_MSG(!expected.empty(),
                          (std::string("missing expected fixture: ") + scenario.name +
                           "/" + check.file)
                              .c_str());
            std::map<std::string, std::string> params;
            if (check.param_name != nullptr) {
                params[check.param_name] = check.param_value;
            }
            const RunOutput run = run_attribute(registry, check.algorithm_id, input,
                                                scenario.shape, params);
            CompareReport report;
            bool ok = false;
            if (check.kind == std::string("phase")) {
                ok = compare_expected(run.values, expected, "phase", 1e-4, 0.0,
                                      phase_uncertain, report);
            } else if (check.kind == std::string("freq")) {
                ok = compare_expected(run.values, expected, "freq", 5e-3, 1e-2,
                                      freq_uncertain, report);
            } else if (check.kind == std::string("rms")) {
                ok = compare_expected(run.values, expected, "rms", 1e-6, 1e-5,
                                      no_uncertain, report);
            } else {
                ok = compare_expected(run.values, expected, "envelope", 1e-5, 1e-4,
                                      no_uncertain, report);
            }
            std::printf("%-15s %s\n", scenario.name,
                        tolerance_line(check.kind, report, ok).c_str());
            ++total_checks;
            if (!ok) {
                ++failed_checks;
            }
        }
    }
    std::printf("parity checks: %zu total, %zu failed\n", total_checks, failed_checks);
    PWB_CHECK(failed_checks == 0);
}

TEST(invariants_analytic) {
    const AlgorithmRegistry& registry = shared_registry();
    const std::filesystem::path root = fixture_io::fixture_root();

    // Integer-cycle cosine: envelope == amplitude, frequency == 30 Hz.
    {
        const std::vector<float> input =
            fixture_io::read_f32(root / "sine_30hz" / "input.f32");
        const RunOutput env =
            run_attribute(registry, "seismic.envelope", input, {4, 4, 256}, {});
        const RunOutput freq = run_attribute(
            registry, "seismic.instantaneous_frequency", input, {4, 4, 256},
            {{"sample_interval", "0.00390625"}});
        double env_dev = 0.0;
        double freq_dev = 0.0;
        for (float v : env.values) {
            env_dev = std::max(env_dev, std::fabs(v - 0.8));
        }
        for (float v : freq.values) {
            freq_dev = std::max(freq_dev, std::fabs(v - 30.0));
        }
        std::printf("sine invariant: max|env-0.8|=%.3e max|freq-30Hz|=%.3e\n", env_dev,
                    freq_dev);
        PWB_CHECK(env_dev < 1e-5);
        PWB_CHECK(freq_dev < 1e-3);
    }

    // Constants: envelope == |c|, phase == 0 / pi, frequency exactly 0,
    // rms == |c|.
    for (const char* name : {"constant_pos", "constant_neg"}) {
        const std::vector<float> input = fixture_io::read_f32(root / name / "input.f32");
        const double c = name[9] == 'p' ? 2.5 : -2.5;
        const RunOutput env =
            run_attribute(registry, "seismic.envelope", input, {5, 5, 8}, {});
        const RunOutput phase =
            run_attribute(registry, "seismic.instantaneous_phase", input, {5, 5, 8},
                          {});
        const RunOutput freq = run_attribute(
            registry, "seismic.instantaneous_frequency", input, {5, 5, 8},
            {{"sample_interval", "0.002"}});
        const RunOutput rms = run_attribute(registry, "seismic.rms_amplitude",
                                            input, {5, 5, 8}, {{"window", "21"}});
        for (std::size_t i = 0; i < env.values.size(); ++i) {
            PWB_CHECK(std::fabs(env.values[i] - std::fabs(c)) < 1e-6);
            // Circular compare: FFT rounding may flip the sign of a ~0
            // imaginary part, giving -pi instead of +pi.
            const double phase_dev =
                std::fabs(std::remainder(phase.values[i] - (c > 0 ? 0.0 : kTwoPi / 2), kTwoPi));
            PWB_CHECK(phase_dev < 1e-6);
            PWB_CHECK(freq.values[i] == 0.0f); // double path: exact zero
            PWB_CHECK(std::fabs(rms.values[i] - std::fabs(c)) < 1e-6);
        }
    }

    // Zeros stay zero everywhere.
    {
        const std::vector<float> input = fixture_io::read_f32(root / "zeros" / "input.f32");
        for (const auto& [id, params] :
             std::vector<std::pair<std::string, std::map<std::string, std::string>>>{
                 {"seismic.envelope", {}},
                 {"seismic.instantaneous_phase", {}},
                 {"seismic.instantaneous_frequency", {{"sample_interval", "1.0"}}},
                 {"seismic.rms_amplitude", {{"window", "21"}}}}) {
            const RunOutput run = run_attribute(registry, id, input, {5, 5, 8}, params);
            for (float v : run.values) {
                PWB_CHECK(v == 0.0f);
            }
        }
    }

    // RMS half-window 0 degenerates to |x| bit-exactly (x^2 is exact in
    // float64 for float32 inputs).
    for (const char* name : {"synth_mixed", "tiny_sgy_real"}) {
        const std::array<std::int64_t, 3> shape =
            name[0] == 's' ? std::array<std::int64_t, 3>{24, 20, 64}
                           : std::array<std::int64_t, 3>{8, 8, 32};
        const std::vector<float> input = fixture_io::read_f32(root / name / "input.f32");
        const RunOutput rms = run_attribute(registry, "seismic.rms_amplitude",
                                            input, shape, {{"window", "0"}});
        for (std::size_t i = 0; i < input.size(); ++i) {
            PWB_CHECK(rms.values[i] == std::fabs(input[i]));
        }
    }
}

TEST(strided_volume_views) {
    const AlgorithmRegistry& registry = shared_registry();
    const std::filesystem::path root = fixture_io::fixture_root();
    const std::vector<float> input =
        fixture_io::read_f32(root / "synth_mixed" / "input.f32");
    const std::vector<float> expected =
        fixture_io::read_f32(root / "synth_mixed" / "expected_envelope.f32");
    PWB_CHECK(!input.empty() && !expected.empty());
    const std::int64_t n_il = 24, n_xl = 20, n_t = 64;

    // Crossline-major (permuted) storage: element (il, xl, t) lives at
    // (xl*n_il + il)*n_t + t.
    auto permuted = std::make_shared<std::vector<float>>(input.size());
    for (std::int64_t il = 0; il < n_il; ++il) {
        for (std::int64_t xl = 0; xl < n_xl; ++xl) {
            for (std::int64_t t = 0; t < n_t; ++t) {
                (*permuted)[static_cast<std::size_t>((xl * n_il + il) * n_t + t)] =
                    input[static_cast<std::size_t>((il * n_xl + xl) * n_t + t)];
            }
        }
    }
    IAlgorithm* algorithm = registry.find("seismic.envelope");
    PWB_CHECK(algorithm != nullptr);
    AlgorithmRequestV1 request;
    request.algorithm_id = "seismic.envelope";
    request.algorithm_version = algorithm->descriptor().version;
    VolumeView view;
    view.data = permuted->data();
    view.shape = {n_il, n_xl, n_t};
    view.strides = {n_t, n_il * n_t, 1}; // il stride 64, xl stride 24*64
    view.lifetime = permuted;
    request.input_volumes.push_back(view);
    Result<pwb::science::AlgorithmResultV1> result = algorithm->run(request, nullptr, {});
    PWB_CHECK(result.has_value());
    const VolumeView& produced = result.value().outputs[0].volume;
    PWB_CHECK(static_cast<std::size_t>(produced.size()) == expected.size());

    CompareReport report;
    const bool ok =
        compare_expected({produced.data, produced.data + expected.size()}, expected,
                         "envelope", 1e-5, 1e-4,
                         std::vector<bool>(expected.size(), false), report);
    std::printf("strided xl-major envelope: %s\n",
                tolerance_line("envelope", report, ok).c_str());
    PWB_CHECK(ok);

    // Explicit packed strides equal the {0,0,0} convention bit-for-bit.
    auto packed = std::make_shared<std::vector<float>>(input);
    AlgorithmRequestV1 packed_request;
    packed_request.algorithm_id = "seismic.envelope";
    packed_request.algorithm_version = algorithm->descriptor().version;
    VolumeView packed_view;
    packed_view.data = packed->data();
    packed_view.shape = {n_il, n_xl, n_t};
    packed_view.strides = {n_xl * n_t, n_t, 1};
    packed_view.lifetime = packed;
    packed_request.input_volumes.push_back(packed_view);
    Result<pwb::science::AlgorithmResultV1> packed_result =
        algorithm->run(packed_request, nullptr, {});
    PWB_CHECK(packed_result.has_value());
    const VolumeView& packed_out = packed_result.value().outputs[0].volume;
    PWB_CHECK(packed_out.is_packed());
    PWB_CHECK(std::memcmp(packed_out.data, produced.data,
                          expected.size() * sizeof(float)) == 0);
}

int main() {
    for (const auto& test : pwb_test::registry()) {
        std::printf("== %s ==\n", test.name.c_str());
        test.body();
    }
    std::printf("all attribute kernel tests passed (%zu tests)\n",
                pwb_test::registry().size());
    return 0;
}
