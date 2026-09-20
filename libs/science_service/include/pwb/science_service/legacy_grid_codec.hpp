#pragma once

// Public exposure of the CONV-28 shared legacy grid-dict decoders (single
// implementation, definitions in fusion_service.cpp). The science_service
// payload seam's hosts (e.g. closure_science's CatalogPayloadSource) decode
// catalogued legacy grid documents through this one codec — never a
// parallel parser.

#include <pwb/domain/json.hpp>
#include <pwb/factor_fusion/factor_grid.hpp>
#include <pwb/mapping/interpolator.hpp>

#include <string>

namespace pwb::science_service {

// Legacy fusion grid dict -> validated factor_fusion::FactorGrid. Throws
// std::invalid_argument on shape/validation failures (frozen messages).
[[nodiscard]] pwb::factor_fusion::FactorGrid legacy_dict_to_fusion_grid(
    const Json& legacy, const std::string& factor_name);

// Same decode widened into the mapping-kernel grid vocabulary.
[[nodiscard]] pwb::mapping::FactorGrid legacy_dict_to_mapping_grid(
    const Json& legacy, const std::string& factor_name);

}  // namespace pwb::science_service
