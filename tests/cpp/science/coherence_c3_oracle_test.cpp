// science.algorithms.coherence_c3_oracle — numeric comparison against the
// frozen Python oracle fixtures (geoviz_seismic.attributes.
// compute_coherence_c3 @ geo-viz-engine 08851951) plus exception/cancel/
// approximation coverage. Fixture regeneration: see
// tests/cpp/science/oracle/generate_coherence_fixture.py.

#include "fixture_io.hpp"
#include "pwb_test.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <stop_token>

#include <pwb/science/algorithms/coherence_c3.hpp>

using namespace pwb::science;

namespace {

struct CaseResult {
    bool loaded{false};
    double max_abs_diff{0.0};
    double mean_abs_diff{0.0};
    std::size_t elements{0};
    std::size_t out_of_range{0};
    std::string name;
};

CaseResult run_case(const std::string& case_name) {
    CaseResult result;
    result.name = case_name;
    const std::filesystem::path dir = fixture_io::fixture_root() / "coherence_c3" / case_name;
    fixture_io::Manifest manifest;
    if (!fixture_io::parse_manifest(fixture_io::read_text(dir / "manifest.json"), manifest)) {
        PWB_FAIL("cannot parse manifest for case " + case_name);
        return result;
    }
    const std::vector<float> input = fixture_io::read_f32(dir / "input.f32");
    const std::vector<float> expected = fixture_io::read_f32(dir / "expected.f32");
    const std::vector<double>& shape = manifest.arrays["shape"];
    if (input.empty() || expected.size() != input.size() || shape.size() != 3) {
        PWB_FAIL("fixture payload mismatch for case " + case_name);
        return result;
    }
    const std::int64_t n_il = static_cast<std::int64_t>(shape[0]);
    const std::int64_t n_xl = static_cast<std::int64_t>(shape[1]);
    const std::int64_t n_t = static_cast<std::int64_t>(shape[2]);
    if (static_cast<std::size_t>(n_il * n_xl * n_t) != input.size()) {
        PWB_FAIL("fixture shape mismatch for case " + case_name);
        return result;
    }

    const auto algorithm = algorithms::make_coherence_c3("oracle-test-build");
    const AlgorithmDescriptor& descriptor = algorithm->descriptor();

    AlgorithmRequestV1 request;
    request.request_id = "oracle-" + case_name;
    request.algorithm_id = descriptor.algorithm_id;
    request.algorithm_version = descriptor.version;
    request.params_json = {
        {"win_il", std::to_string(manifest.number("win_il", 5))},
        {"win_xl", std::to_string(manifest.number("win_xl", 5))},
        {"win_t", std::to_string(manifest.number("win_t", 5))},
        {"power_iterations", "30"},
    };
    auto storage = std::make_shared<const std::vector<float>>(input);
    request.input_volumes.push_back(VolumeView{
        storage->data(), {n_il, n_xl, n_t}, {0, 0, 0}, storage});

    const auto outcome = algorithm->run(request, nullptr, {});
    if (!outcome.has_value()) {
        PWB_FAIL("oracle case " + case_name + " failed to run");
        return result;
    }
    const VolumeView& output = outcome.value().outputs[0].volume;
    result.elements = expected.size();
    double abs_sum = 0.0;
    for (std::size_t i = 0; i < expected.size(); ++i) {
        const double diff = std::fabs(static_cast<double>(output.data[i]) -
                                      static_cast<double>(expected[i]));
        result.max_abs_diff = std::max(result.max_abs_diff, diff);
        abs_sum += diff;
        if (output.data[i] < 0.0f || output.data[i] > 1.0f) {
            ++result.out_of_range;
        }
    }
    result.mean_abs_diff = abs_sum / static_cast<double>(expected.size());
    result.loaded = true;
    return result;
}

} // namespace

TEST(oracle_all_frozen_cases_within_tolerance) {
    const char* cases[] = {
        "synth_default",     "synth_asym_window", "synth_small_dims",
        "synth_constant",    "synth_nan_region",  "tiny_sgy_real_w3",
        "tiny_sgy_real_w1x1x5",
    };
    std::size_t compared = 0;
    for (const char* case_name : cases) {
        const CaseResult result = run_case(case_name);
        PWB_CHECK_MSG(result.loaded, (std::string("case did not load: ") + case_name).c_str());
        const double tolerance = 2e-3; // frozen in docs 00-baseline §5
        if (result.max_abs_diff > tolerance) {
            char message[256];
            std::snprintf(message, sizeof(message),
                          "case %s max_abs_diff=%.3e exceeds %.1e", result.name.c_str(),
                          result.max_abs_diff, tolerance);
            PWB_FAIL(message);
        }
        PWB_CHECK(result.out_of_range == 0);
        compared += result.elements;
    }
    std::printf("oracle comparison: %zu cases, %zu elements, all within 2e-3\n",
                sizeof(cases) / sizeof(cases[0]), compared);
}

TEST(zero_energy_volume_is_exactly_one_and_constant_matches_oracle) {
    // All-zero volume: total_energy == 0 takes the exact-1.0 branch (no
    // arithmetic drift possible).
    const auto algorithm = algorithms::make_coherence_c3("oracle-test-build");
    const AlgorithmDescriptor& descriptor = algorithm->descriptor();
    auto zeros = std::make_shared<const std::vector<float>>(8 * 8 * 16, 0.0f);
    AlgorithmRequestV1 request;
    request.algorithm_id = descriptor.algorithm_id;
    request.algorithm_version = descriptor.version;
    request.input_volumes.push_back(VolumeView{
        zeros->data(), {8, 8, 16}, {0, 0, 0}, zeros});
    const auto outcome = algorithm->run(request, nullptr, {});
    PWB_CHECK(outcome.has_value());
    for (std::size_t i = 0; i < 8 * 8 * 16; ++i) {
        PWB_CHECK_MSG(outcome.value().outputs[0].volume.data[i] == 1.0f,
                      "zero-energy coherence must be exactly 1.0");
    }

    // Constant (nonzero) volume: the oracle itself lands at 0.99999976 after
    // float32 power-iteration drift, so this case is tolerance-compared in
    // oracle_all_frozen_cases_within_tolerance like the others; here we
    // additionally pin the invariants.
    const CaseResult result = run_case("synth_constant");
    PWB_CHECK(result.loaded);
    PWB_CHECK(result.out_of_range == 0);
    PWB_CHECK(result.max_abs_diff <= 2e-3);
}

TEST(exception_inputs_rejected_with_stable_codes) {
    const auto algorithm = algorithms::make_coherence_c3("oracle-test-build");
    const AlgorithmDescriptor& descriptor = algorithm->descriptor();
    auto storage = std::make_shared<const std::vector<float>>(8 * 8 * 16, 0.25f);

    const auto make_request = [&](const char* win_il, const char* win_xl, const char* win_t) {
        AlgorithmRequestV1 request;
        request.algorithm_id = descriptor.algorithm_id;
        request.algorithm_version = descriptor.version;
        request.params_json = {{"win_il", win_il},
                               {"win_xl", win_xl},
                               {"win_t", win_t},
                               {"power_iterations", "30"}};
        request.input_volumes.push_back(VolumeView{
            storage->data(), {8, 8, 16}, {0, 0, 0}, storage});
        return request;
    };

    // win_il = 0 (below minimum 1)
    auto outcome = algorithm->run(make_request("0", "3", "3"), nullptr, {});
    PWB_CHECK(outcome.is_error());
    PWB_CHECK(outcome.error().diagnostics.front().code == "param.win_il.out_of_range");

    // win_xl = -3
    outcome = algorithm->run(make_request("3", "-3", "3"), nullptr, {});
    PWB_CHECK(outcome.is_error());
    PWB_CHECK(outcome.error().diagnostics.front().code == "param.win_xl.out_of_range");

    // win_t not an integer
    outcome = algorithm->run(make_request("3", "3", "abc"), nullptr, {});
    PWB_CHECK(outcome.is_error());
    PWB_CHECK(outcome.error().diagnostics.front().code == "param.win_t.invalid_json");

    // version mismatch
    AlgorithmRequestV1 wrong_version = make_request("3", "3", "3");
    wrong_version.algorithm_version = "0.0.1";
    outcome = algorithm->run(wrong_version, nullptr, {});
    PWB_CHECK(outcome.is_error());
    PWB_CHECK(outcome.error().diagnostics.front().code == "request.algorithm_version.mismatch");
}

TEST(cancellation_returns_cancelled_without_success) {
    const auto algorithm = algorithms::make_coherence_c3("oracle-test-build");
    const AlgorithmDescriptor& descriptor = algorithm->descriptor();
    std::vector<float> pattern(24 * 20 * 40);
    for (std::int64_t i = 0; i < 24; ++i) {
        for (std::int64_t j = 0; j < 20; ++j) {
            for (std::int64_t k = 0; k < 40; ++k) {
                pattern[(i * 20 + j) * 40 + k] =
                    static_cast<float>(std::sin(0.3 * i) + 0.2 * std::cos(0.5 * j) +
                                       0.1 * std::sin(0.7 * k));
            }
        }
    }
    auto storage = std::make_shared<const std::vector<float>>(std::move(pattern));

    AlgorithmRequestV1 request;
    request.algorithm_id = descriptor.algorithm_id;
    request.algorithm_version = descriptor.version;
    request.input_volumes.push_back(VolumeView{
        storage->data(), {24, 20, 40}, {0, 0, 0}, storage});

    { // stop already requested: cancelled at the first inline boundary
        std::stop_source source;
        source.request_stop();
        const auto outcome = algorithm->run(request, nullptr, source.get_token());
        PWB_CHECK(outcome.is_cancelled());
    }
    { // stop requested from the progress callback after the first inline
        std::stop_source source;
        int reports = 0;
        science::ProgressSink sink = [&source, &reports](const ProgressReport& report) {
            ++reports;
            if (report.fraction >= 0.0 && reports >= 1) {
                source.request_stop(); // mid-run cancel at the next boundary
            }
        };
        const auto outcome = algorithm->run(request, std::move(sink), source.get_token());
        PWB_CHECK(outcome.is_cancelled());
        PWB_CHECK(reports >= 1);
    }
}

TEST(result_is_deterministic_and_provenance_complete) {
    const CaseResult first = run_case("synth_default");
    const CaseResult second = run_case("synth_default");
    PWB_CHECK(first.loaded && second.loaded);
    PWB_CHECK(first.max_abs_diff == second.max_abs_diff); // bit-identical reruns

    const auto algorithm = algorithms::make_coherence_c3("build-identity-x");
    const AlgorithmDescriptor& descriptor = algorithm->descriptor();
    auto storage = std::make_shared<const std::vector<float>>(
        [] {
            std::vector<float> data(10 * 10 * 12);
            for (std::size_t i = 0; i < data.size(); ++i) {
                data[i] = std::sin(0.1f * static_cast<float>(i));
            }
            return data;
        }());
    AlgorithmRequestV1 request;
    request.request_id = "prov-1";
    request.algorithm_id = descriptor.algorithm_id;
    request.algorithm_version = descriptor.version;
    request.params_json = {{"win_il", "2"}, {"win_xl", "2"}, {"win_t", "2"},
                           {"power_iterations", "30"}};
    request.input_refs.push_back(VersionRef{"asset-1", "version-1", "store://vol"});
    request.input_volumes.push_back(VolumeView{
        storage->data(), {10, 10, 12}, {0, 0, 0}, storage});
    const auto outcome = algorithm->run(request, nullptr, {});
    PWB_CHECK(outcome.has_value());
    const AlgorithmResultV1& result = outcome.value();
    PWB_CHECK(result.request_id == "prov-1");
    PWB_CHECK(result.provenance.algorithm_id == "seismic.coherence_c3");
    PWB_CHECK(result.provenance.algorithm_version == "1.0.0");
    PWB_CHECK(result.provenance.build_identity == "build-identity-x");
    PWB_CHECK(result.provenance.approximate);
    PWB_CHECK(result.provenance.input_refs.size() == 1);
    PWB_CHECK(result.provenance.input_refs[0].version_id == "version-1");
    PWB_CHECK(result.provenance.params_json.at("win_il") == "2");
    PWB_CHECK(!result.provenance.started_utc.empty());
    PWB_CHECK(!result.provenance.finished_utc.empty());

    // Progress reaches 1.0 on the success path and stays monotonic.
    double last = -1.0;
    double final_fraction = -1.0;
    science::ProgressSink sink = [&last, &final_fraction](const ProgressReport& report) {
        if (report.fraction < last) {
            PWB_FAIL("progress fraction regressed");
        }
        last = report.fraction;
        final_fraction = report.fraction;
    };
    const auto rerun = algorithm->run(request, std::move(sink), {});
    PWB_CHECK(rerun.has_value());
    PWB_CHECK(final_fraction == 1.0);
}

#include "pwb_test_main.inc"
