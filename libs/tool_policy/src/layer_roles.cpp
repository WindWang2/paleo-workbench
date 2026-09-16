#include <pwb/tool_policy/layer_roles.hpp>

namespace pwb::tool_policy::layer_role {

bool is_line_role(std::string_view value) {
    return value == kProvenanceLine || value == kProvenanceDirection
        || value == kDistributionLine || value == kPaleoShoreline
        || value == kFaciesBoundary || value == kFaultConstraint;
}

bool is_polygon_role(std::string_view value) {
    return value == kInterpolationBoundary || value == kMaskBoundary;
}

}  // namespace pwb::tool_policy::layer_role
