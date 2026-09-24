// closure_agent.processing_tools — phase-4 helper contracts: the paleo
// algorithm vocabulary converts to valid, provider-delegated ActionSpecs
// (id mapping ':' -> '.', registry accepts them, derived tool schemas name
// the algorithms unambiguously) and the Qt/QGIS-free boundary holds (pure
// AlgorithmToolInfo in, ActionSpec out).
#include "test_util.hpp"

#include <pwb/closure_agent/registry.hpp>

using namespace pwb::closure_agent;

int main() {
    // Id mapping: colon becomes the domain dot; the LLM tool name doubles
    // it back ("paleo__seismic_envelope") per tool_schema()'s contract.
    const std::vector<AlgorithmToolInfo> infos = {
        {"paleo:seismic_envelope", "包络", "seismic"},
        {"paleo:interpolation_idw", "IDW 插值", "interpolation"},
    };
    const std::vector<ActionSpec> specs = processing_algorithm_specs(infos);
    check(specs.size() == 2, "one spec per algorithm");
    check(specs[0].action_id == "paleo.seismic_envelope",
          "colon maps to the domain dot");
    check(specs[0].risk == ActionRisk::Compute, "compute risk");
    check(specs[0].provider_id == std::optional<std::string>("paleo_processing"),
          "provider-delegated execution");
    check(!specs[0].handler, "no direct handler");
    check(specs[0].deterministic, "kernels are deterministic");
    check(specs[0].description.find("paleo:seismic_envelope")
              != std::string::npos,
          "description carries the paleo id");

    // Registry round trip: the specs validate as-is (no throw) and the
    // derived tool schema addresses the algorithm unambiguously.
    ActionRegistry registry;
    for (const ActionSpec& spec : specs) {
        const ActionSpec& installed = registry.register_spec(spec);
        check(installed.domain() == "paleo", "domain is the provider id");
    }
    check(registry.size() == 2, "both algorithms registered");
    const std::vector<Json> tools = registry.tool_schemas("paleo");
    check(tools.size() == 2, "one tool per algorithm in the paleo domain");
    bool found = false;
    for (const Json& tool : tools) {
        if (tool["function"]["name"].get<std::string>()
            == "paleo__seismic_envelope") {
            found = true;
        }
    }
    check(found, "tool name derives from the dotted id");

    // Degenerate id (second dot) must be rejected by validation, not
    // silently mangled — the caller sees the problem at registration.
    const std::vector<AlgorithmToolInfo> bad = {
        {"paleo:seismic:envelope", "bad", "seismic"}};
    const std::vector<ActionSpec> bad_specs = processing_algorithm_specs(bad);
    check(!validate_action_spec(bad_specs[0]).empty(),
          "malformed ids fail validation");

    return test_exit("closure_agent.processing_tools");
}
