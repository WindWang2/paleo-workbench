// Registration contract: explicit registration through the public header,
// duplicate rejection, descriptor/request validation, and coexistence with
// the existing C3 algorithm. This file is also the "production consumer"
// evidence: it links only Pwb::SeismicAttributes + Pwb::Science public
// headers and calls no test doubles.

#include "pwb_test.hpp"

#include <cmath>
#include <map>
#include <memory>
#include <string>
#include <vector>

#include <pwb/science/algorithms/coherence_c3.hpp>
#include <pwb/science/registry.hpp>
#include <pwb/science/types.hpp>
#include <pwb/seismic_attributes/attributes.hpp>

namespace {

using pwb::science::AlgorithmRegistry;
using pwb::science::AlgorithmRequestV1;
using pwb::science::Result;
using pwb::science::VolumeView;

std::shared_ptr<std::vector<float>> make_input(std::array<std::int64_t, 3> shape,
                                               std::vector<float>&& values) {
    PWB_CHECK(static_cast<std::size_t>(shape[0] * shape[1] * shape[2]) == values.size());
    return std::make_shared<std::vector<float>>(std::move(values));
}

AlgorithmRequestV1 make_request(const std::string& id, const std::string& version,
                                std::shared_ptr<std::vector<float>> holder,
                                std::array<std::int64_t, 3> shape,
                                std::map<std::string, std::string> params = {}) {
    AlgorithmRequestV1 request;
    request.algorithm_id = id;
    request.algorithm_version = version;
    request.params_json = std::move(params);
    VolumeView view;
    view.data = holder->data();
    view.shape = shape;
    view.strides = {0, 0, 0};
    view.lifetime = std::move(holder);
    request.input_volumes.push_back(view);
    return request;
}

bool has_error_code(const Result<pwb::science::AlgorithmResultV1>& result,
                    const std::string& code) {
    return result.is_error() && !result.error().diagnostics.empty() &&
           result.error().diagnostics[0].code == code;
}

} // namespace

TEST(register_ten_explicit) {
    AlgorithmRegistry registry;
    const auto report =
        pwb::seismic_attributes::register_seismic_attributes(registry, "build-abc123");
    PWB_CHECK(report.registered_ids.size() == 10);
    PWB_CHECK(report.rejection.empty());
    const std::vector<std::string> expected = {
        "seismic.envelope",
        "seismic.instantaneous_phase",
        "seismic.instantaneous_frequency",
        "seismic.rms_amplitude",
        "seismic.sweetness",
        "seismic.relative_impedance",
        "seismic.dip_il",
        "seismic.dip_xl",
        "seismic.dip_azimuth",
        "seismic.curvature_mean",
    };
    PWB_CHECK(report.registered_ids == expected);
    for (const std::string& id : expected) {
        PWB_CHECK(registry.find(id) != nullptr);
    }
    PWB_CHECK(registry.find("seismic.envelope")->descriptor().version == "1.0.0");
}

TEST(duplicate_registration_rejected) {
    AlgorithmRegistry registry;
    const auto first =
        pwb::seismic_attributes::register_seismic_attributes(registry, "build-1");
    PWB_CHECK(first.registered_ids.size() == 10);
    // Second registration: envelope is a duplicate -> explicit rejection,
    // later entries are not registered.
    const auto second =
        pwb::seismic_attributes::register_seismic_attributes(registry, "build-2");
    PWB_CHECK(second.registered_ids.empty());
    PWB_CHECK(!second.rejection.empty());
    PWB_CHECK(second.rejection.find("duplicate") != std::string::npos);
    // Registry state unchanged: still exactly the ten from the first call.
    std::size_t attribute_count = 0;
    for (const std::string& id : registry.algorithm_ids()) {
        if (id.rfind("seismic.", 0) == 0) {
            ++attribute_count;
        }
    }
    PWB_CHECK(attribute_count == 10);
}

TEST(descriptors_match_contract) {
    AlgorithmRegistry registry;
    const auto report =
        pwb::seismic_attributes::register_seismic_attributes(registry, "build-desc");
    PWB_CHECK(report.registered_ids.size() == 10);
    struct Expected {
        const char* id;
        const char* output;
        const char* unit;
        std::size_t params;
    };
    const Expected table[] = {
        {"seismic.envelope", "envelope", "", 0},
        {"seismic.instantaneous_phase", "instantaneous_phase", "rad", 0},
        {"seismic.instantaneous_frequency", "instantaneous_frequency", "Hz", 1},
        {"seismic.rms_amplitude", "rms_amplitude", "", 1},
        {"seismic.sweetness", "sweetness", "", 1},
        {"seismic.relative_impedance", "relative_impedance", "", 0},
        {"seismic.dip_il", "dip_il", "rad", 3},
        {"seismic.dip_xl", "dip_xl", "rad", 3},
        {"seismic.dip_azimuth", "dip_azimuth", "rad", 3},
        {"seismic.curvature_mean", "curvature_mean", "", 3},
    };
    for (const Expected& row : table) {
        const auto& descriptor = registry.find(row.id)->descriptor();
        PWB_CHECK(descriptor.family == "seismic_attribute");
        PWB_CHECK(descriptor.supports_cancel);
        PWB_CHECK(descriptor.deterministic);
        PWB_CHECK(!descriptor.approximate);
        PWB_CHECK(descriptor.build_identity == "build-desc");
        PWB_CHECK(descriptor.inputs.size() == 1);
        PWB_CHECK(descriptor.inputs[0].name == "volume");
        PWB_CHECK(descriptor.outputs.size() == 1);
        PWB_CHECK(descriptor.outputs[0].name == row.output);
        PWB_CHECK(descriptor.outputs[0].unit == row.unit);
        PWB_CHECK(descriptor.parameters.size() == row.params);
    }
    const auto& freq =
        registry.find("seismic.instantaneous_frequency")->descriptor();
    PWB_CHECK(freq.parameters[0].name == "sample_interval");
    PWB_CHECK(freq.parameters[0].type == pwb::science::ParamSpec::Type::number);
    PWB_CHECK(freq.parameters[0].default_json == "1.0");
    const auto& rms = registry.find("seismic.rms_amplitude")->descriptor();
    PWB_CHECK(rms.parameters[0].name == "window");
    PWB_CHECK(rms.parameters[0].default_json == "21");
    PWB_CHECK(rms.parameters[0].minimum == 0);
    PWB_CHECK(rms.parameters[0].maximum == 1048576);
}

TEST(request_validation_rejections) {
    AlgorithmRegistry registry;
    const auto report =
        pwb::seismic_attributes::register_seismic_attributes(registry, "build-req");
    PWB_CHECK(report.registered_ids.size() == 10);
    auto input = make_input({2, 2, 4}, {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16});

    // Missing volume.
    {
        AlgorithmRequestV1 request;
        request.algorithm_id = "seismic.envelope";
        request.algorithm_version = "1.0.0";
        const auto result =
            registry.find("seismic.envelope")->run(request, nullptr, {});
        PWB_CHECK(has_error_code(result, "request.input_volumes.count"));
    }
    // Version mismatch.
    {
        auto request = make_request("seismic.envelope", "2.0.0", input, {2, 2, 4});
        const auto result =
            registry.find("seismic.envelope")->run(request, nullptr, {});
        PWB_CHECK(has_error_code(result, "request.algorithm_version.mismatch"));
    }
    // sample_interval == 0: registry bounds pass (min 0 inclusive), the
    // algorithm rejects with the frozen diagnostic.
    {
        auto request = make_request("seismic.instantaneous_frequency", "1.0.0",
                                    input, {2, 2, 4}, {{"sample_interval", "0"}});
        const auto result = registry.find("seismic.instantaneous_frequency")
                                ->run(request, nullptr, {});
        PWB_CHECK(has_error_code(result, "param.sample_interval.not_positive"));
    }
    // Negative sample_interval is rejected by registry bounds.
    {
        auto request = make_request("seismic.instantaneous_frequency", "1.0.0",
                                    input, {2, 2, 4}, {{"sample_interval", "-0.5"}});
        const auto result = registry.find("seismic.instantaneous_frequency")
                                ->run(request, nullptr, {});
        PWB_CHECK(has_error_code(result, "param.sample_interval.out_of_range"));
    }
    // window below 0 / above the explicit support maximum.
    {
        auto request = make_request("seismic.rms_amplitude", "1.0.0", input,
                                    {2, 2, 4}, {{"window", "-5"}});
        const auto result =
            registry.find("seismic.rms_amplitude")->run(request, nullptr, {});
        PWB_CHECK(has_error_code(result, "param.window.out_of_range"));
    }
    {
        auto request = make_request("seismic.rms_amplitude", "1.0.0", input,
                                    {2, 2, 4}, {{"window", "1048577"}});
        const auto result =
            registry.find("seismic.rms_amplitude")->run(request, nullptr, {});
        PWB_CHECK(has_error_code(result, "param.window.out_of_range"));
    }
    {
        auto request = make_request("seismic.rms_amplitude", "1.0.0", input,
                                    {2, 2, 4}, {{"window", "abc"}});
        const auto result =
            registry.find("seismic.rms_amplitude")->run(request, nullptr, {});
        PWB_CHECK(has_error_code(result, "param.window.invalid_json"));
    }
    // Frequency on a length-1 sample axis: explicit rejection (oracle raises
    // ValueError on np.gradient).
    {
        auto nt1 = make_input({2, 2, 1}, {1.5f, -2.0f, 0.25f, -8.0f});
        auto request = make_request("seismic.instantaneous_frequency", "1.0.0",
                                    std::move(nt1), {2, 2, 1}, {{"sample_interval", "0.002"}});
        const auto result = registry.find("seismic.instantaneous_frequency")
                                ->run(request, nullptr, {});
        PWB_CHECK(has_error_code(result, "input.sample_count.too_small"));
    }
    // Zero dimension in shape.
    {
        auto zero = make_input({0, 2, 4}, {});
        auto request = make_request("seismic.envelope", "1.0.0", std::move(zero),
                                    {0, 2, 4});
        const auto result =
            registry.find("seismic.envelope")->run(request, nullptr, {});
        PWB_CHECK(has_error_code(result, "request.input_volumes.invalid"));
    }
}

TEST(coherence_c3_coexistence) {
    // Register C3 first, then the four attributes: no id collision, C3 still
    // runs and reports its own id/provenance.
    AlgorithmRegistry registry;
    PWB_CHECK(registry.register_algorithm(pwb::science::algorithms::make_coherence_c3(
                  "build-c3")) == "");
    const auto report =
        pwb::seismic_attributes::register_seismic_attributes(registry, "build-e");
    PWB_CHECK(report.registered_ids.size() == 10);
    PWB_CHECK(report.rejection.empty());

    // Small C3 sanity run (2x2x8) — the attribute registrations must not
    // disturb it.
    std::vector<float> values(2 * 2 * 8);
    for (std::size_t i = 0; i < values.size(); ++i) {
        values[i] = std::sin(0.3f * static_cast<float>(i));
    }
    auto holder = make_input({2, 2, 8}, std::move(values));
    auto request = make_request("seismic.coherence_c3", "1.0.0", holder, {2, 2, 8},
                                {{"win_il", "1"}, {"win_xl", "1"}, {"win_t", "2"},
                                 {"power_iterations", "10"}});
    const auto result = registry.find("seismic.coherence_c3")->run(request, nullptr, {});
    PWB_CHECK(result.has_value());
    PWB_CHECK(result.value().outputs.size() == 1);
    PWB_CHECK(result.value().outputs[0].name == "coherence");
    PWB_CHECK(result.value().provenance.algorithm_id == "seismic.coherence_c3");
    PWB_CHECK(result.value().provenance.build_identity == "build-c3");
    for (float v : std::vector<float>(
             result.value().outputs[0].volume.data,
             result.value().outputs[0].volume.data +
                 static_cast<std::size_t>(result.value().outputs[0].volume.size()))) {
        PWB_CHECK(std::isfinite(v) && v >= 0.0f && v <= 1.0f);
    }
}

int main() {
    for (const auto& test : pwb_test::registry()) {
        std::printf("== %s ==\n", test.name.c_str());
        test.body();
    }
    std::printf("all registration tests passed (%zu tests)\n", pwb_test::registry().size());
    return 0;
}
