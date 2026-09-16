// science.contracts — descriptor/registry/request-validation contract tests.

#include "pwb_test.hpp"

#include <pwb/science/algorithms/coherence_c3.hpp>
#include <pwb/science/registry.hpp>

using namespace pwb::science;

TEST(descriptor_shape_validation_rejects_bad_ids_and_versions) {
    AlgorithmDescriptor bad;
    bad.algorithm_id = "no_dot";
    bad.version = "1.0.0";
    bad.display_name = "x";
    PWB_CHECK(!validate_descriptor(bad).empty());

    bad.algorithm_id = "seismic.ok";
    bad.version = "v1";
    PWB_CHECK(!validate_descriptor(bad).empty());

    bad.version = "1.0.0";
    PWB_CHECK(validate_descriptor(bad).empty());

    bad.inputs.push_back(PortSpec{"volume", PortKind::volume_f32, "", true});
    bad.inputs.push_back(PortSpec{"volume", PortKind::volume_f32, "", true});
    PWB_CHECK(!validate_descriptor(bad).empty()); // duplicate port name
}

TEST(registry_rejects_duplicates_and_finds_algorithms) {
    AlgorithmRegistry registry;
    PWB_CHECK(registry
                  .register_algorithm(algorithms::make_coherence_c3("test-build"))
                  .empty());
    PWB_CHECK(!registry.register_algorithm(algorithms::make_coherence_c3("test-build"))
                   .empty()); // duplicate id
    PWB_CHECK(registry.find("seismic.coherence_c3") != nullptr);
    PWB_CHECK(registry.find("seismic.missing") == nullptr);
    PWB_CHECK(registry.algorithm_ids().size() == 1);
}

namespace {

AlgorithmRequestV1 base_request(const AlgorithmDescriptor& descriptor,
                                std::vector<float> storage) {
    static std::vector<float> keep_alive;
    keep_alive = std::move(storage);
    AlgorithmRequestV1 request;
    request.request_id = "req-1";
    request.algorithm_id = descriptor.algorithm_id;
    request.algorithm_version = descriptor.version;
    request.params_json = {{"win_il", "3"}, {"win_xl", "3"}, {"win_t", "3"},
                           {"power_iterations", "30"}};
    request.input_volumes.push_back(VolumeView{
        keep_alive.data(), {4, 4, 8}, {32, 8, 1}, nullptr});
    return request;
}

} // namespace

TEST(request_validation_catches_mismatches_and_bad_params) {
    const auto algorithm = algorithms::make_coherence_c3("test-build");
    const AlgorithmDescriptor& descriptor = algorithm->descriptor();

    { // version mismatch
        AlgorithmRequestV1 request = base_request(descriptor, std::vector<float>(128, 0.5f));
        request.algorithm_version = "9.9.9";
        const std::vector<Diagnostic> problems = validate_request(descriptor, request);
        PWB_CHECK(problems.size() == 1);
        PWB_CHECK(problems[0].code == "request.algorithm_version.mismatch");
    }
    { // window parameter below minimum
        AlgorithmRequestV1 request = base_request(descriptor, std::vector<float>(128, 0.5f));
        request.params_json["win_il"] = "0";
        const std::vector<Diagnostic> problems = validate_request(descriptor, request);
        PWB_CHECK(!problems.empty());
        PWB_CHECK(problems[0].code == "param.win_il.out_of_range");
    }
    { // non-integer parameter
        AlgorithmRequestV1 request = base_request(descriptor, std::vector<float>(128, 0.5f));
        request.params_json["win_t"] = "2.5";
        const std::vector<Diagnostic> problems = validate_request(descriptor, request);
        PWB_CHECK(!problems.empty());
        PWB_CHECK(problems[0].code == "param.win_t.wrong_type");
    }
    { // missing volume input
        AlgorithmRequestV1 request = base_request(descriptor, std::vector<float>(128, 0.5f));
        request.input_volumes.clear();
        const std::vector<Diagnostic> problems = validate_request(descriptor, request);
        PWB_CHECK(!problems.empty());
        PWB_CHECK(problems[0].code == "request.input_volumes.count");
    }
    { // zero-sized dimension
        AlgorithmRequestV1 request = base_request(descriptor, std::vector<float>(128, 0.5f));
        request.input_volumes[0].shape = {4, 0, 8};
        const std::vector<Diagnostic> problems = validate_request(descriptor, request);
        PWB_CHECK(!problems.empty());
        PWB_CHECK(problems[0].code == "request.input_volumes.invalid");
    }
    { // valid request passes
        AlgorithmRequestV1 request = base_request(descriptor, std::vector<float>(128, 0.5f));
        PWB_CHECK(validate_request(descriptor, request).empty());
    }
}

TEST(coherence_descriptor_is_frozen_and_marked_approximate) {
    const auto algorithm = algorithms::make_coherence_c3("sha-test");
    const AlgorithmDescriptor& descriptor = algorithm->descriptor();
    PWB_CHECK(descriptor.algorithm_id == "seismic.coherence_c3");
    PWB_CHECK(descriptor.version == "1.0.0");
    PWB_CHECK(descriptor.family == "seismic_attribute");
    PWB_CHECK(descriptor.supports_cancel);
    PWB_CHECK(descriptor.deterministic);
    PWB_CHECK(descriptor.approximate); // power iteration is an approximation
    PWB_CHECK(descriptor.inputs.size() == 1);
    PWB_CHECK(descriptor.inputs[0].kind == PortKind::volume_f32);
    PWB_CHECK(descriptor.parameters.size() == 4);
    // Same object => same immutable descriptor.
    PWB_CHECK(&algorithm->descriptor() == &algorithm->descriptor());
}

TEST(typed_param_lookup_falls_back_to_defaults) {
    const auto algorithm = algorithms::make_coherence_c3("sha-test");
    const AlgorithmDescriptor& descriptor = algorithm->descriptor();
    AlgorithmRequestV1 request;
    request.algorithm_id = descriptor.algorithm_id;
    request.algorithm_version = descriptor.version;
    request.params_json = {}; // everything falls back to defaults
    const ParamSpec* win_il = nullptr;
    for (const ParamSpec& spec : descriptor.parameters) {
        if (spec.name == "win_il") {
            win_il = &spec;
        }
    }
    PWB_CHECK(win_il != nullptr);
    const auto value = request_param_integer(request, *win_il);
    PWB_CHECK(value.has_value());
    PWB_CHECK(value.value() == 5); // frozen default
}

#include "pwb_test_main.inc"
