#pragma once

// processing_install — agent tool source for the Paleo Processing
// algorithms (CONV-QGIS-PROCESSING phase 4).
//
// The closure_agent library is Qt-free/QGIS-free: it accepts plain
// AlgorithmToolInfo rows and turns them into provider-delegated ActionSpecs
// (processing_algorithm_specs). THIS file is the apps-side conversion and
// install point: it reads the single algorithm authority
// (QgsProcessingRegistry via pwb::qgis_processing::paleo_algorithm_infos())
// and converts every paleo algorithm into the agent vocabulary.
//
// The product does not assemble a closure_agent harness yet (no ActionRegistry
// instance exists to receive the specs). The functions here are the ready
// wiring for that mount: paleo_processing_tool_infos() is also the
// capabilities/diagnostics outlet for "which algorithms can the agent
// address", and register_paleo_agent_actions() drops them into a registry
// the day one is created.

#include <string>
#include <vector>

namespace pwb::closure_agent {
class ActionRegistry;
}

namespace pwb::app {

// One paleo Processing algorithm in the closure_agent vocabulary (pure
// std::strings — no Qt/QGIS types cross this header).
struct ProcessingToolInfo {
    std::string id;       // "paleo:seismic_envelope"
    std::string display;  // "包络"
    std::string group;    // "seismic"
};

// paleo_algorithm_infos() converted; requires QgisRuntime. Sorted by id
// (stable regardless of registry iteration order).
[[nodiscard]] std::vector<ProcessingToolInfo> paleo_processing_tool_infos();

#ifdef PWB_WITH_CLOSURE_AGENT
// Future harness mount: converts paleo_processing_tool_infos() through
// closure_agent::processing_algorithm_specs() and registers every spec
// into `registry` (replacing same-id actions). Returns the number of
// actions registered. Throws closure_agent's registry errors (invalid
// spec, duplicate id) — the caller decides the product policy.
std::size_t register_paleo_agent_actions(
    pwb::closure_agent::ActionRegistry& registry);
#endif

}  // namespace pwb::app
