#pragma once

// pwb::science_service — IAlgorithm adapters + registry assembly (CONV-28).
//
// Each typed service (factor / well / fusion / geomodel) is exposed as a
// pwb::science IAlgorithm so it runs on the frozen TaskRuntime with any
// IResultPublisherV1 — the exact seam the Workflow line registers node
// adapters against:
//
//   auto source  = std::make_shared<InMemoryPayloadSource>();   // DTO host
//   auto registry = std::make_unique<science::AlgorithmRegistry>();
//   register_science_services(*registry, source, "sha-abc123");
//   pwb::workflow::TaskRuntime runtime;
//   auto handle = runtime.submit(
//       registry->find("mapping.factor_interpolate")->shared_from_this()...
//
// Request mapping (params_json): every adapter reads its typed request from
// the request's params_json map (JSON-encoded scalar values) plus structured
// inputs resolved from input_refs through IPayloadSource. node_request()
// builds that request from a plain workflow node params object — the one
// function a workflow node adapter needs.

#include <pwb/science/algorithm.hpp>
#include <pwb/science/registry.hpp>

#include <memory>
#include <string>
#include <vector>

#include "envelope.hpp"
#include "factor_service.hpp"
#include "facies_service.hpp"
#include "fusion_service.hpp"
#include "geomodel_service.hpp"
#include "limits.hpp"
#include "payload.hpp"
#include "well_service.hpp"

namespace pwb::science_service {

// --- adapter factories (one IAlgorithm per service) ------------------------

[[nodiscard]] std::shared_ptr<science::IAlgorithm>
make_factor_interpolation_adapter(std::shared_ptr<IPayloadSource> source,
                                  std::string build_identity = "local",
                                  ResourceLimits limits = ResourceLimits::defaults());
[[nodiscard]] std::shared_ptr<science::IAlgorithm>
make_factor_layer_products_adapter(
    std::string build_identity = "local",
    ResourceLimits limits = ResourceLimits::defaults());
[[nodiscard]] std::shared_ptr<science::IAlgorithm>
make_facies_surface_adapter(std::string build_identity = "local",
                            ResourceLimits limits = ResourceLimits::defaults());
[[nodiscard]] std::shared_ptr<science::IAlgorithm>
make_curve_operation_adapter(std::string build_identity = "local",
                             ResourceLimits limits = ResourceLimits::defaults());
[[nodiscard]] std::shared_ptr<science::IAlgorithm>
make_log_match_adapter(std::string build_identity = "local",
                       ResourceLimits limits = ResourceLimits::defaults());
[[nodiscard]] std::shared_ptr<science::IAlgorithm>
make_factor_fusion_adapter(std::string build_identity = "local",
                           ResourceLimits limits = ResourceLimits::defaults());
[[nodiscard]] std::shared_ptr<science::IAlgorithm>
make_geomodel_build_adapter(std::string build_identity = "local",
                            ResourceLimits limits = ResourceLimits::defaults());
[[nodiscard]] std::shared_ptr<science::IAlgorithm>
make_geomodel_section_adapter(std::string build_identity = "local",
                              ResourceLimits limits = ResourceLimits::defaults());
[[nodiscard]] std::shared_ptr<science::IAlgorithm>
make_geomodel_export_adapter(std::string build_identity = "local",
                             ResourceLimits limits = ResourceLimits::defaults());

// Register every adapter above. Returns the algorithm ids accepted (a
// duplicate id from a pre-populated registry is skipped, not an error).
[[nodiscard]] std::vector<std::string> register_science_services(
    science::AlgorithmRegistry& registry,
    std::shared_ptr<IPayloadSource> source,
    const std::string& build_identity = "local",
    const ResourceLimits& limits = ResourceLimits::defaults());

// --- workflow node adapter helper ------------------------------------------

// Map a workflow node params OBJECT (Json object of scalars/arrays) into an
// AlgorithmRequestV1: every value is copied into params_json by its JSON
// text (objects/arrays included — adapters parse them with the same Json).
// input_refs ride along verbatim (resolved through IPayloadSource at run).
[[nodiscard]] science::AlgorithmRequestV1 node_request(
    const std::string& algorithm_id, const pwb::domain::Json& node_params,
    std::vector<science::VersionRef> input_refs = {},
    std::string request_id = "");

}  // namespace pwb::science_service
