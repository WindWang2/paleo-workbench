#include <pwb/ui_composite/capture_spec.hpp>

#include <pwb/ui_composite/roles.hpp>

#include <map>

namespace pwb::ui_composite {
namespace {

using constraint_kind::kDistributionLine;
using constraint_kind::kFaciesBoundary;
using constraint_kind::kFault;
using constraint_kind::kInterpolationBoundary;
using constraint_kind::kMask;
using constraint_kind::kPaleoShoreline;
using constraint_kind::kProvenanceLine;
using constraint_kind::kSourceDirection;

// 角色驱动的地质捕获目标词表。template_key 对齐 GEO_TEMPLATES 键词汇；
// 未列出的可编辑角色回落 kind 默认样式（template_key=""），仍获得捕捉
// 推荐与拓扑提示。
const std::map<std::string, GeologicalCaptureSpec>& capture_specs() {
    static const std::map<std::string, GeologicalCaptureSpec> specs = [] {
        std::map<std::string, GeologicalCaptureSpec> map;
        auto add = [&map](const std::string& role, std::string geometry,
                          std::string template_key, bool topological,
                          std::optional<std::string> kind = std::nullopt) {
            map.emplace(role,
                        GeologicalCaptureSpec{
                            .role = role,
                            .geometry_kind = std::move(geometry),
                            .template_key = std::move(template_key),
                            .snapping_profile =
                                recommended_profile_for_role(role),
                            .recommend_topological_editing = topological,
                            .constraint_kind = std::move(kind),
                        });
        };

        add(std::string(layer_role::kProvenanceDirection), "line",
            "direction", false, std::string(kSourceDirection));
        add(std::string(layer_role::kProvenanceLine), "line", "source",
            false, std::string(kProvenanceLine));
        add(std::string(layer_role::kDistributionLine), "line",
            "spreading", false, std::string(kDistributionLine));
        add(std::string(layer_role::kPaleoShoreline), "line", "", false,
            std::string(kPaleoShoreline));
        add(std::string(layer_role::kFaciesBoundary), "line", "", true,
            std::string(kFaciesBoundary));
        add(std::string(layer_role::kFaultConstraint), "line", "fault",
            false, std::string(kFault));
        add(std::string(layer_role::kInterpolationBoundary), "polygon",
            "extent", true, std::string(kInterpolationBoundary));
        add(std::string(layer_role::kMaskBoundary), "polygon", "", true,
            std::string(kMask));
        add(std::string(layer_role::kInitialFaciesDraft), "polygon",
            "facies", true);
        add(std::string(layer_role::kIntegratedFacies), "polygon",
            "facies", true);
        add(std::string(layer_role::kUserGeneral), "line", "", false);
        // V10 补齐：可编辑角色先前无捕获语义。INTEGRATED_BOUNDARY 是 P3
        // active_editing_roles 成员；INTERPRETATION_ANNOTATION 是
        // ROLE_EDITABLE 成员。
        add(std::string(layer_role::kIntegratedBoundary), "line", "",
            true, std::string(kFaciesBoundary));
        add(std::string(layer_role::kInterpretationAnnotation), "line",
            "", false);
        return map;
    }();
    return specs;
}

}  // namespace

std::string GeologicalCaptureSpec::role_label() const {
    return pwb::ui_composite::role_label(role);
}

const GeologicalCaptureSpec* capture_spec_for_role(
    const std::string& role_value) {
    auto parsed = layer_role_from_value(role_value);
    if (!parsed.has_value()) {
        return nullptr;
    }
    auto it = capture_specs().find(*parsed);
    return it == capture_specs().end() ? nullptr : &it->second;
}

}  // namespace pwb::ui_composite
