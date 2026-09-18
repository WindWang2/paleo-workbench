#pragma once

// pwb::science_service — factor fusion service (CONV-28): typed envelope over
// the frozen factor_fusion kernel (CONV-24).
//
// Inputs are the interchange forms the workflow line already persists:
//   * model dict — FusionModel.to_dict() shape (evidence weights /
//     normalizations, rules, class names; NO grids)
//   * grids — factor name -> mapping-kernel legacy grid dict
//     (pwb::mapping::to_legacy_dict shape, CONV-18 codec) OR parsed
//     mapping::FactorGrid payloads from IPayloadSource.
// The service converts legacy dicts to factor_fusion::FactorGrid carriers,
// runs fuse (weighted_evidence / rule_based) and wraps the FusionResult
// (likelihood / confidence / variance / qc / provenance) in one envelope.
// register_output (catalog write) stays a host seam — the publisher receives
// the envelope instead.

#include <pwb/factor_fusion/fusion.hpp>
#include <pwb/mapping/interpolator.hpp>
#include <pwb/science/outcome.hpp>

#include <map>
#include <optional>
#include <string>

#include "envelope.hpp"
#include "limits.hpp"

namespace pwb::science_service {

struct FactorFusionRequest {
    // FusionModel.to_dict() shape (without runtime grids).
    pwb::domain::Json model_dict = pwb::domain::Json::object();
    // factor name -> legacy grid dict (mapping::to_legacy_dict shape).
    pwb::domain::Json grids = pwb::domain::Json::object();
    // Optional already-parsed grids (win over `grids` entries by name).
    std::map<std::string, pwb::mapping::FactorGrid> parsed_grids;
};

struct FactorFusionResult {
    ScienceEnvelope envelope;
    pwb::factor_fusion::FusionResult fusion;
};

class FactorFusionService {
public:
    explicit FactorFusionService(
        std::string build_identity = "local",
        ResourceLimits limits = ResourceLimits::defaults());

    [[nodiscard]] science::Result<FactorFusionResult> run(
        const FactorFusionRequest& request,
        science::ProgressSink progress = nullptr,
        std::stop_token stop = {});

private:
    std::string build_identity_;
    ResourceLimits limits_;
};

// Legacy grid dict (mapping::to_legacy_dict shape) -> factor_fusion carrier
// with float32 normalization semantics. Shared with the payload-source path.
// Throws std::invalid_argument with a stable message on a foreign shape.
[[nodiscard]] pwb::factor_fusion::FactorGrid legacy_dict_to_fusion_grid(
    const pwb::domain::Json& legacy, const std::string& factor_name);

}  // namespace pwb::science_service
