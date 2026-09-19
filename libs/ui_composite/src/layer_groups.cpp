#include <pwb/ui_composite/layer_groups.hpp>

#include <pwb/ui_composite/roles.hpp>

#include <algorithm>
#include <cctype>
#include <map>

namespace pwb::ui_composite {
namespace {

const std::set<MappingStage>& all_stages() {
    static const std::set<MappingStage> stages = {
        MappingStage::FaciesCalibration,
        MappingStage::ConstraintFactor,
        MappingStage::IntegratedCompilation,
    };
    return stages;
}

constexpr MappingStage P1 = MappingStage::FaciesCalibration;
constexpr MappingStage P2 = MappingStage::ConstraintFactor;
constexpr MappingStage P3 = MappingStage::IntegratedCompilation;

std::string lower(const std::string& text) {
    std::string out = text;
    std::transform(out.begin(), out.end(), out.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return out;
}

std::string strip(const std::string& text) {
    const auto first = text.find_first_not_of(" \t\n\r");
    const auto last = text.find_last_not_of(" \t\n\r");
    return first == std::string::npos
               ? std::string{}
               : text.substr(first, last - first + 1);
}

bool starts_with(const std::string& text, const std::string& prefix) {
    return text.size() >= prefix.size() &&
           text.compare(0, prefix.size(), prefix) == 0;
}

const std::set<std::string>& factor_roles() {
    static const std::set<std::string> roles = {
        std::string(layer_role::kFactorInput),
        std::string(layer_role::kFactorGrid),
        std::string(layer_role::kFactorContour),
        std::string(layer_role::kFactorClassification),
        std::string(layer_role::kFactorUncertainty),
        std::string(layer_role::kFactorQc),
    };
    return roles;
}

const std::set<std::string>& stage_aux_roles() {
    static const std::set<std::string> roles = {
        std::string(layer_role::kQcWarning),
        std::string(layer_role::kQcConflict),
        std::string(layer_role::kAnalysisAid),
    };
    return roles;
}

// 角色 → home group（图层在联合树中的唯一归属）。QC/辅助类角色按「创
// 建阶段的 aux/qc 组」路由，需带 stage 提示。
const std::map<std::string, std::string>& role_home_group() {
    static const std::map<std::string, std::string> map = {
        {std::string(layer_role::kBaseReference),
         std::string(kBaseReferenceGroupId)},
        {std::string(layer_role::kInitialFaciesSource),
         "phase1.initial_facies"},
        {std::string(layer_role::kInitialFaciesDraft),
         "phase1.interpretation"},
        {std::string(layer_role::kWellFaciesPrediction),
         "phase1.well_predictions"},
        {std::string(layer_role::kWellFaciesConfidence),
         "phase1.well_predictions"},
        {std::string(layer_role::kSeismicFaciesPrediction),
         "phase1.seismic_predictions"},
        {std::string(layer_role::kSeismicFaciesConfidence),
         "phase1.seismic_predictions"},
        {std::string(layer_role::kInterpretationAnnotation),
         "phase1.interpretation"},
        {std::string(layer_role::kPendingReviewArea),
         "phase1.interpretation"},
        {std::string(layer_role::kProvenanceDirection),
         "phase2.constraints"},
        {std::string(layer_role::kProvenanceLine), "phase2.constraints"},
        {std::string(layer_role::kDistributionLine), "phase2.constraints"},
        {std::string(layer_role::kPaleoShoreline), "phase2.constraints"},
        {std::string(layer_role::kFaciesBoundary), "phase2.constraints"},
        {std::string(layer_role::kFaultConstraint), "phase2.constraints"},
        {std::string(layer_role::kInterpolationBoundary),
         "phase2.constraints"},
        {std::string(layer_role::kMaskBoundary), "phase2.constraints"},
        {std::string(layer_role::kAnalysisAid), "phase2.analysis"},
        {std::string(layer_role::kIntegratedFacies), "phase3.integrated"},
        {std::string(layer_role::kIntegratedBoundary), "phase3.integrated"},
        {std::string(layer_role::kMapAnnotation), "phase3.cartography"},
        {std::string(layer_role::kMapSymbol), "phase3.geology"},
        {std::string(layer_role::kMapReference), "phase3.geology"},
        {std::string(layer_role::kQcWarning), "phase3.qc"},
        {std::string(layer_role::kQcConflict), "phase3.qc"},
        {std::string(layer_role::kUserGeneral),
         std::string(kLegacyGroupId)},
        {std::string(layer_role::kLegacyUnclassified),
         std::string(kLegacyGroupId)},
    };
    return map;
}

// QC/辅助角色在不同创建阶段的去处。
const std::map<MappingStage, std::string>& stage_aux_group() {
    static const std::map<MappingStage, std::string> map = {
        {P1, "phase1.aux"},
        {P2, "phase2.analysis"},
        {P3, "phase3.qc"},
    };
    return map;
}

// UserVectorLayer.template → ConstraintKind（模板键是 machine-readable
// 元数据——用于旧工程约束线的保守归类）。
const std::map<std::string, std::string>& template_constraint_kinds() {
    static const std::map<std::string, std::string> map = {
        {"provenance", std::string(constraint_kind::kProvenanceLine)},
        {"物源线", std::string(constraint_kind::kProvenanceLine)},
        {"物源", std::string(constraint_kind::kProvenanceLine)},
        {"distribution", std::string(constraint_kind::kDistributionLine)},
        {"展布线", std::string(constraint_kind::kDistributionLine)},
        {"shoreline", std::string(constraint_kind::kPaleoShoreline)},
        {"古岸线", std::string(constraint_kind::kPaleoShoreline)},
        {"岸线", std::string(constraint_kind::kPaleoShoreline)},
        {"facies_boundary", std::string(constraint_kind::kFaciesBoundary)},
        {"相带边界", std::string(constraint_kind::kFaciesBoundary)},
        {"fault", std::string(constraint_kind::kFault)},
        {"断层", std::string(constraint_kind::kFault)},
        {"断层线", std::string(constraint_kind::kFault)},
        {"boundary", std::string(constraint_kind::kInterpolationBoundary)},
        {"成图范围", std::string(constraint_kind::kInterpolationBoundary)},
        {"mask", std::string(constraint_kind::kMask)},
        {"排除区", std::string(constraint_kind::kExclusionArea)},
    };
    return map;
}

// 模板键 → 专业归属角色（classify 第 4 步；新建层按模板直接进工作流
// 组——断层→地质约束、物源/展布/方向/打断→各约束线、测井点→地质表
// 达、相带三级→人工解释与修编、成图范围→地质表达）。
const std::map<std::string, std::string>& template_role_home() {
    static const std::map<std::string, std::string> map = {
        {"fault", std::string(layer_role::kFaultConstraint)},
        {"source", std::string(layer_role::kProvenanceLine)},
        {"spreading", std::string(layer_role::kDistributionLine)},
        {"direction", std::string(layer_role::kProvenanceDirection)},
        {"break", std::string(layer_role::kInterpolationBoundary)},
        {"well_point", std::string(layer_role::kMapSymbol)},
        {"facies_sub", std::string(layer_role::kInitialFaciesDraft)},
        {"facies_micro", std::string(layer_role::kInitialFaciesDraft)},
        {"extent", std::string(layer_role::kMapReference)},
    };
    return map;
}

}  // namespace

const std::vector<GroupTemplate>& system_group_templates() {
    static const std::vector<GroupTemplate> templates = [] {
        std::vector<GroupTemplate> out;
        auto push = [&out](std::string id, std::string title, int order,
                           std::set<MappingStage> stages,
                           std::set<MappingStage> locked = {},
                           std::string description = "") {
            out.push_back(GroupTemplate{
                .group_id = std::move(id),
                .title = std::move(title),
                .order = order,
                .stages = std::move(stages),
                .locked_stages = std::move(locked),
                .kind = "system",
                .parent_id = "",
                .description = std::move(description),
            });
        };

        const std::set<MappingStage>& all = all_stages();
        // 联合树排序（order 小者在上=渲染在上）：编图要素/QC 最上，综
        // 合解释次之，解释与约束居中，预测/相图靠下，基础参考垫底。
        push("phase3.cartography", "编图要素", 10, {P3}, {},
             "标题/图例/比例尺/指北针/注记/数据来源等成图组件");
        push("phase3.qc", "QA / QC", 20, {P3}, {},
             "冲突区域/低置信度/空洞/拓扑错误/过期输入/待审核");
        push("phase3.integrated", "综合解释", 30, {P3}, {},
             "综合沉积相/相带边界/沉积体系/物源体系/专家修编（可编辑）");
        push("phase3.geology", "地质表达", 40, {P3}, {},
             "井/断层/物源方向/相带符号/地质符号/专题标注");
        push("phase1.interpretation", "人工解释与修编", 50, all,
             {P2, P3},
             "沉积相解释面/相带边界/解释注记；在②③阶段作为上阶段证据锁定");
        push("phase2.constraints", "地质约束", 60, {P2, P3}, {P3},
             "物源方向/物源线/展布线/古岸线/相带控制线/断层/插值边界/Mask");
        push(kFactorRootGroupId, "单因素图", 70, {P2, P3}, {P3},
             "各单因素任务的 nested factor 组（输入/栅格/等值线/分级/QC）");
        push("phase1.well_predictions", "测井预测相", 80, {P1}, {},
             "测井预测相/预测概率/低置信度/QC（模型结果，不可编辑）");
        push("phase1.seismic_predictions", "地震预测相", 90, {P1}, {},
             "地震预测相/预测概率/低置信度/QC（模型结果，不可编辑）");
        push("phase2.analysis", "分析辅助", 100, {P2}, {},
             "插值残差/不确定性/异常点/数据覆盖范围");
        push("phase1.initial_facies", "初始沉积相", 110, {P1, P2}, {},
             "原始初始相图（RAW，锁定）与当前相图底图");
        push("phase1.aux", "辅助图层", 120, {P1}, {}, "Phase 1 杂项辅助");
        push(kBaseReferenceGroupId, "基础与参考", 900, all, {},
             "工区边界/井位/地震工区/参考地理数据（全阶段共享）");
        push(kLegacyGroupId, "未分类（旧工程）", 950, all, {},
             "旧工程无法保守归类图层的兜底组；不猜测科学语义");
        return out;
    }();
    return templates;
}

const GroupTemplate* system_group_template(const std::string& group_id) {
    for (const GroupTemplate& tpl : system_group_templates()) {
        if (tpl.group_id == group_id) {
            return &tpl;
        }
    }
    return nullptr;
}

std::vector<const GroupTemplate*> system_group_templates_for_stage(
    MappingStage stage) {
    std::vector<const GroupTemplate*> out;
    for (const GroupTemplate& tpl : system_group_templates()) {
        if (tpl.stage_visible(stage)) {
            out.push_back(&tpl);
        }
    }
    return out;
}

std::string factor_group_id(const std::string& factor_task_id) {
    std::string sanitized = strip(factor_task_id);
    std::replace(sanitized.begin(), sanitized.end(), ' ', '_');
    return sanitized.empty() ? std::string{} : "factor." + sanitized;
}

std::string factor_group_title(const std::string& factor_name,
                               const std::string& factor_type) {
    const std::string& pick =
        !factor_name.empty() ? factor_name
                             : (!factor_type.empty() ? factor_type
                                                     : std::string("单因素"));
    return strip(pick);
}

bool is_factor_group(const std::string& group_id) {
    return starts_with(group_id, "factor.");
}

std::optional<std::string> factor_task_of_group(const std::string& group_id) {
    if (!is_factor_group(group_id)) {
        return std::nullopt;
    }
    return group_id.substr(7);
}

std::string epoch_group_id(const std::string& epoch_key) {
    std::string sanitized = strip(epoch_key);
    std::replace(sanitized.begin(), sanitized.end(), ' ', '_');
    return sanitized.empty() ? std::string{}
                             : std::string(kEpochGroupPrefix) + sanitized;
}

bool is_epoch_group(const std::string& group_id) {
    return starts_with(group_id, kEpochGroupPrefix);
}

std::optional<std::string> epoch_key_of_group(const std::string& group_id) {
    if (!is_epoch_group(group_id)) {
        return std::nullopt;
    }
    std::string key = group_id.substr(6);
    std::replace(key.begin(), key.end(), '_', ' ');
    return key;
}

const std::vector<std::string>& factor_child_order() {
    static const std::vector<std::string> order = {
        std::string(layer_role::kFactorInput),
        std::string(layer_role::kFactorGrid),
        std::string(layer_role::kFactorContour),
        std::string(layer_role::kFactorClassification),
        std::string(layer_role::kFactorUncertainty),
        std::string(layer_role::kFactorQc),
    };
    return order;
}

std::string home_group_for_role(const std::string& role_value,
                                std::optional<MappingStage> stage,
                                const std::string& factor_task_id) {
    auto resolved = layer_role_from_value(role_value);
    if (!resolved.has_value()) {
        return kLegacyGroupId;
    }
    if (factor_roles().count(*resolved)) {
        const std::string group = factor_group_id(factor_task_id);
        return group.empty() ? std::string(kFactorRootGroupId) : group;
    }
    if (stage_aux_roles().count(*resolved) && stage.has_value()) {
        auto it = stage_aux_group().find(*stage);
        if (it != stage_aux_group().end()) {
            return it->second;
        }
    }
    auto it = role_home_group().find(*resolved);
    return it == role_home_group().end() ? std::string(kLegacyGroupId)
                                         : it->second;
}

std::set<MappingStage> stages_for_role(const std::string& role_value) {
    auto resolved = layer_role_from_value(role_value);
    if (!resolved.has_value()) {
        return all_stages();
    }
    if (factor_roles().count(*resolved)) {
        return {P2, P3};
    }
    auto it = role_home_group().find(*resolved);
    const std::string home =
        it == role_home_group().end() ? std::string(kLegacyGroupId)
                                      : it->second;
    const GroupTemplate* tpl = system_group_template(home);
    return tpl != nullptr ? tpl->stages : all_stages();
}

bool movable_into_system_group(const std::string& role_value,
                               const std::string& group_id) {
    auto resolved = layer_role_from_value(role_value);
    if (!resolved.has_value()) {
        return true;
    }
    const GroupTemplate* tpl = system_group_template(group_id);
    if (tpl == nullptr || tpl->kind != "system") {
        return true;  // 用户组/未知组：自由组织
    }
    if (group_id == kBaseReferenceGroupId || group_id == kLegacyGroupId) {
        return true;
    }
    if (is_factor_group(group_id)) {
        return factor_roles().count(*resolved) != 0;
    }
    return home_group_for_role(*resolved) == group_id;
}

LayerClassification classify_layer_for_migration(
    const std::string& layer_id,
    const std::map<std::string, std::string>& metadata,
    const std::string& template_key,
    const std::string& /*geometry_type*/) {
    // 1. 显式角色两键都认：V5 工程持久化写 "layer_role"，V9 起快照层携
    //    带 "role"——只认前者会让带角色的快照层被误判进 LEGACY 兜底组。
    auto meta_get = [&metadata](const char* key) -> std::string {
        auto it = metadata.find(key);
        return it != metadata.end() ? it->second : std::string{};
    };
    if (auto explicit_role = layer_role_from_value(
            !meta_get("layer_role").empty() ? meta_get("layer_role")
                                            : meta_get("role"))) {
        return LayerClassification{
            .role = *explicit_role,
            .home_group_id = home_group_for_role(*explicit_role),
            .constraint_kind = "",
        };
    }
    // 2. 已知基础工区图层 id 前缀。
    if (starts_with(layer_id, kBaseLayerIdPrefix)) {
        return LayerClassification{
            .role = std::string(layer_role::kBaseReference),
            .home_group_id = std::string(kBaseReferenceGroupId),
            .constraint_kind = "",
        };
    }
    // 3. 参考图层（metadata.reference）→ 基础参考。
    if (meta_get("reference") == "true") {
        return LayerClassification{
            .role = std::string(layer_role::kBaseReference),
            .home_group_id = std::string(kBaseReferenceGroupId),
            .constraint_kind = "",
        };
    }
    // 4. 模板键（metadata.template 或 .template 属性——两处都读）。
    const std::string tpl =
        lower(strip(!meta_get("template").empty() ? meta_get("template")
                                                  : template_key));
    if (!tpl.empty()) {
        if (auto kind = template_constraint_kinds().count(tpl)
                            ? std::optional<std::string>(
                                  template_constraint_kinds().at(tpl))
                            : std::nullopt) {
            return LayerClassification{
                .role = *constraint_kind_layer_role(*kind),
                .home_group_id = "phase2.constraints",
                .constraint_kind = *kind,
            };
        }
        if (auto it = template_role_home().find(tpl);
            it != template_role_home().end()) {
            return LayerClassification{
                .role = it->second,
                .home_group_id = home_group_for_role(it->second),
                .constraint_kind = "",
            };
        }
        if (tpl == "facies" || tpl == "相图" || tpl == "沉积相" ||
            tpl == "facies_polygon") {
            return LayerClassification{
                .role = std::string(layer_role::kInitialFaciesDraft),
                .home_group_id = "phase1.interpretation",
                .constraint_kind = "",
            };
        }
    }
    // 5. 全部未命中 → LEGACY（进兜底组，不猜名字）。
    return LayerClassification{
        .role = std::string(layer_role::kLegacyUnclassified),
        .home_group_id = std::string(kLegacyGroupId),
        .constraint_kind = "",
    };
}

std::map<std::string, bool> default_group_visibility(MappingStage stage) {
    std::map<std::string, bool> visibility;
    for (const GroupTemplate& tpl : system_group_templates()) {
        visibility.emplace(tpl.group_id, tpl.stage_visible(stage));
    }
    return visibility;
}

}  // namespace pwb::ui_composite
