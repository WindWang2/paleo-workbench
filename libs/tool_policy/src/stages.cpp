#include <pwb/tool_policy/stages.hpp>

#include <array>
#include <cctype>
#include <string>
#include <unordered_map>

namespace pwb::tool_policy {
namespace {

struct StageInfo {
    MappingStage stage;
    const char* value;
    const char* label;
    const char* short_label;
    const char* description;
};

constexpr std::array<StageInfo, 3> kStages{{
    {MappingStage::FaciesCalibration, "facies_calibration", "① 智能预测",
     "智能预测",
     "先设定编图层位，再叠加该层位的地震相预测与测井相预测；"
     "测井预测支持由井点生成相面（点到面）。"},
    {MappingStage::ConstraintFactor, "constraint_factor", "② 约束与单因素",
     "约束/单因素",
     "以上一阶段成果为背景，编辑物源/展布/岸线/相带边界/断层等线面约束，"
     "并组织各单因素图的输入、插值面、等值线、分类结果与不确定性/QC。"},
    {MappingStage::IntegratedCompilation, "integrated_compilation",
     "③ 综合编图", "综合编图",
     "以校正相图、约束与单因素成果为证据进行多因素综合解释、相带/古地理"
     "面编辑、图件符号与标注、QA/QC 与最终 MapProduct 成图。"},
}};

const StageInfo& info(MappingStage stage) {
    for (const StageInfo& entry : kStages) {
        if (entry.stage == stage) return entry;
    }
    return kStages[0];
}

std::string to_lower(std::string text) {
    for (char& c : text) c = static_cast<char>(std::tolower(
        static_cast<unsigned char>(c)));
    return text;
}

const std::unordered_map<std::string, MappingStage>& aliases() {
    static const std::unordered_map<std::string, MappingStage> table = {
        {"facies", MappingStage::FaciesCalibration},
        {"phase1", MappingStage::FaciesCalibration},
        {"phase 1", MappingStage::FaciesCalibration},
        {"intelligent_prediction", MappingStage::FaciesCalibration},
        {"智能预测", MappingStage::FaciesCalibration},
        {"constraints", MappingStage::ConstraintFactor},
        {"factor", MappingStage::ConstraintFactor},
        {"phase2", MappingStage::ConstraintFactor},
        {"phase 2", MappingStage::ConstraintFactor},
        {"integrated", MappingStage::IntegratedCompilation},
        {"compilation", MappingStage::IntegratedCompilation},
        {"phase3", MappingStage::IntegratedCompilation},
        {"phase 3", MappingStage::IntegratedCompilation},
    };
    return table;
}

}  // namespace

const char* stage_value(MappingStage stage) { return info(stage).value; }
const char* stage_label(MappingStage stage) { return info(stage).label; }
const char* stage_short_label(MappingStage stage) { return info(stage).short_label; }
const char* stage_description(MappingStage stage) { return info(stage).description; }

std::optional<MappingStage> stage_from_value(const std::string& value) {
    if (value.empty()) return std::nullopt;
    for (const StageInfo& entry : kStages) {
        if (value == entry.value) return entry.stage;
    }
    const auto it = aliases().find(to_lower(value));
    if (it != aliases().end()) return it->second;
    return std::nullopt;
}

std::string stage_display_or_raw(const std::string& value) {
    const auto stage = stage_from_value(value);
    if (stage.has_value()) return stage_label(*stage);
    if (value.empty()) return "阶段未知";
    return value;
}

}  // namespace pwb::tool_policy
