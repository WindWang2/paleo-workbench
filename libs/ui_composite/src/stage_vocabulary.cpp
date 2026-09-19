#include <pwb/ui_composite/stage_vocabulary.hpp>

#include <map>

namespace pwb::ui_composite {
namespace {

const std::map<std::string, std::string>& action_tools() {
    static const std::map<std::string, std::string> map = {
        {"open_factor_workbench", "factor_workbench"},
        {"run_factor", "factor_workbench"},
        {"overlay_factor_results", "factor_overlay"},
        {"run_qa", "qa_run"},
        {"stage_qc", "qa_run"},
        {"assemble_map_product", "map_product_assemble"},
    };
    return map;
}

const std::vector<std::pair<std::string, std::string>>&
empty_actions() {
    static const std::vector<std::pair<std::string, std::string>> empty;
    return empty;
}

}  // namespace

std::string stage_action_tool_id(const std::string& action_id) {
    auto it = action_tools().find(action_id);
    return it == action_tools().end() ? std::string{} : it->second;
}

const std::vector<std::pair<std::string, std::string>>&
stage_context_actions(MappingStage stage) {
    static const std::vector<std::pair<std::string, std::string>>
        facies_calibration = {
            {"add_seismic_prediction_overlay", "叠加地震相预测"},
            {"add_well_prediction_overlay", "叠加测井相预测"},
            {"well_prediction_point_to_surface", "测井点到面"},
            {"run_well_facies_mock", "运行测井相预测（mock）"},
            {"run_seismic_facies_mock", "运行地震相面预测（mock）"},
            {"load_initial_facies", "加载初始相图"},
            {"create_facies_draft", "创建解释草稿"},
            {"stage_save", "保存阶段成果"},
        };
    static const std::vector<std::pair<std::string, std::string>>
        constraint_factor = {
            {"open_factor_workbench", "单因素工作台"},
            {"overlay_factor_results", "叠加单因素结果"},
            {"commit_constraints", "提交约束版本"},
            {"stage_save", "保存阶段成果"},
        };
    static const std::vector<std::pair<std::string, std::string>>
        integrated_compilation = {
            {"select_evidence", "选择证据版本"},
            {"freeze_input_set", "冻结证据版本"},
            {"run_fusion", "运行融合"},
            {"create_integrated_draft", "创建综合草稿"},
            {"run_qa", "运行 QA"},
            {"commit_interpretation", "提交综合解释"},
            {"assemble_map_product", "生成 MapProduct"},
        };
    switch (stage) {
    case MappingStage::FaciesCalibration:
        return facies_calibration;
    case MappingStage::ConstraintFactor:
        return constraint_factor;
    case MappingStage::IntegratedCompilation:
        return integrated_compilation;
    }
    return empty_actions();
}

std::vector<std::pair<std::string, std::string>> stage_context_actions(
    const std::string& stage_value) {
    auto stage = tool_policy::stage_from_value(stage_value);
    if (!stage.has_value()) {
        return {};
    }
    return stage_context_actions(*stage);
}

std::vector<std::string> stage_context_action_ids(MappingStage stage) {
    std::vector<std::string> ids;
    for (const auto& [action_id, label] : stage_context_actions(stage)) {
        ids.push_back(action_id);
    }
    return ids;
}

std::vector<std::string> stage_context_action_ids(
    const std::string& stage_value) {
    auto stage = tool_policy::stage_from_value(stage_value);
    if (!stage.has_value()) {
        return {};
    }
    return stage_context_action_ids(*stage);
}

}  // namespace pwb::ui_composite
