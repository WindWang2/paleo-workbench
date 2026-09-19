#include <pwb/ui_composite/snapping_profiles.hpp>

#include <pwb/ui_composite/roles.hpp>

#include <cmath>
#include <cstdio>
#include <map>
#include <sstream>

namespace pwb::ui_composite {
namespace {

// 角色聚类 → profile（同簇角色捕捉语义一致，逐角色表只会漂移）。
const std::map<std::string, SnappingProfile>& profiles() {
    static const std::map<std::string, SnappingProfile> map = {
        {"boundary",
         {std::string(layer_role::kFaciesBoundary),
          {"vertex", "segment", "intersection"},
          12.0,
          true,
          "相带边界追求无缝拼接：顶点+段+交点捕捉并开启拓扑编辑，"
          "相邻边界共享节点自动传播，避免出现缝/重叠"}},
        {"shoreline",
         {std::string(layer_role::kPaleoShoreline),
          {"vertex", "segment"},
          10.0,
          false,
          "古岸线是连续曲线约束：顶点+段捕捉保证与已有岸线/边界衔接；"
          "拓扑编辑默认关闭（岸线允许与相带边界交叉而非共节点）"}},
        {"fault",
         {std::string(layer_role::kFaultConstraint),
          {"vertex", "endpoint", "segment"},
          8.0,
          false,
          "断层端点位置有独立地质含义：端点+顶点+段捕捉便于精确拾取"
          "断距端头与已有断层交会，拓扑编辑关闭（断层不与边界共节点）"}},
        {"direction",
         {std::string(layer_role::kProvenanceDirection),
          {"endpoint", "vertex"},
          10.0,
          false,
          "物源方向线以箭头端点表达指向：端点捕捉让方向线终点落在"
          "井位/参考点上；段捕捉关闭（方向线中段无需贴合其它要素）"}},
        {"line_constraint",
         {std::string(layer_role::kDistributionLine),
          {"vertex", "segment"},
          10.0,
          false,
          "展布线/物源线沿走向追踪：顶点+段捕捉衔接已有约束线；"
          "拓扑编辑关闭（约束线允许相交表达超覆关系）"}},
        {"polygon_constraint",
         {std::string(layer_role::kInterpolationBoundary),
          {"vertex", "segment"},
          12.0,
          true,
          "插值边界/掩膜必须闭合且不与工区边界留缝：顶点+段捕捉配合"
          "拓扑编辑，闭合性由保存时校验兜底"}},
        {"draft",
         {std::string(layer_role::kInitialFaciesDraft),
          {"vertex", "segment", "intersection"},
          12.0,
          true,
          "解释草稿的相单元需要互相拼接：边界簇 profile 同款——"
          "顶点+段+交点 + 拓扑编辑"}},
        {"general",
         {std::string(layer_role::kUserGeneral),
          {"vertex", "segment", "midpoint"},
          10.0,
          false,
          "通用编辑默认：顶点+段+中点捕捉，拓扑编辑关闭"}},
    };
    return map;
}

// 角色 → 簇键（缺省 general）。
const std::map<std::string, std::string>& role_cluster() {
    static const std::map<std::string, std::string> map = {
        {std::string(layer_role::kFaciesBoundary), "boundary"},
        {std::string(layer_role::kIntegratedBoundary), "boundary"},
        {std::string(layer_role::kInitialFaciesDraft), "draft"},
        {std::string(layer_role::kIntegratedFacies), "draft"},
        {std::string(layer_role::kPaleoShoreline), "shoreline"},
        {std::string(layer_role::kFaultConstraint), "fault"},
        {std::string(layer_role::kProvenanceDirection), "direction"},
        {std::string(layer_role::kProvenanceLine), "line_constraint"},
        {std::string(layer_role::kDistributionLine), "line_constraint"},
        {std::string(layer_role::kInterpolationBoundary),
         "polygon_constraint"},
        {std::string(layer_role::kMaskBoundary), "polygon_constraint"},
        {std::string(layer_role::kUserGeneral), "general"},
        {std::string(layer_role::kLegacyUnclassified), "general"},
        {std::string(layer_role::kInterpretationAnnotation), "general"},
        {std::string(layer_role::kMapAnnotation), "general"},
    };
    return map;
}

}  // namespace

const SnappingProfile* recommended_profile_for_role(
    const std::string& role_value) {
    auto parsed = layer_role_from_value(role_value);
    if (!parsed.has_value()) {
        return nullptr;
    }
    if (role_is_raw_protected(*parsed)) {
        return nullptr;
    }
    auto cluster = role_cluster().find(*parsed);
    const std::string key =
        cluster == role_cluster().end() ? "general" : cluster->second;
    auto it = profiles().find(key);
    return it == profiles().end() ? nullptr : &it->second;
}

std::string profile_summary(const SnappingProfile& profile) {
    std::ostringstream out;
    out << role_label(profile.role) << "推荐：";
    bool first = true;
    for (const std::string& mode : profile.modes) {
        if (!first) {
            out << "、";
        }
        out << mode;
        first = false;
    }
    // Python f"{tolerance_px:g}" — trim trailing zeros for integral values.
    char buf[32];
    if (profile.tolerance_px == std::floor(profile.tolerance_px)) {
        std::snprintf(buf, sizeof(buf), "%.0f", profile.tolerance_px);
    } else {
        std::snprintf(buf, sizeof(buf), "%g", profile.tolerance_px);
    }
    out << "，容差 " << buf << "px，拓扑编辑"
        << (profile.topological ? "开" : "关") << "——"
        << profile.rationale;
    return out.str();
}

}  // namespace pwb::ui_composite
