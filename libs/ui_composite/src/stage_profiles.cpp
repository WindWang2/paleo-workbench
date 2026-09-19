#include <pwb/ui_composite/stage_profiles.hpp>

#include <pwb/ui_composite/layer_groups.hpp>
#include <pwb/ui_composite/roles.hpp>
#include <pwb/ui_composite/stage_vocabulary.hpp>

#include <algorithm>

namespace pwb::ui_composite {
namespace {

const StageProfile& make_profile(MappingStage stage) {
    static const StageProfile profiles[] = {
        StageProfile{
            .stage = MappingStage::FaciesCalibration,
            .label = tool_policy::stage_label(
                MappingStage::FaciesCalibration),
            .description = tool_policy::stage_description(
                MappingStage::FaciesCalibration),
            .group_visibility = default_group_visibility(
                MappingStage::FaciesCalibration),
            .active_editing_roles = {
                std::string(layer_role::kInitialFaciesDraft),
            },
            .tools = StageToolProfile{
                .edit_actions = {"add_polygon", "move_feature", "vertex",
                                 "split", "merge", "delete_selected",
                                 "undo", "redo"},
                .context_actions = stage_context_action_ids(
                    MappingStage::FaciesCalibration),
            },
            .recommended_docks = {
                {"composite_input", true},   // 左：输入与结果
                {"composite_layer", true},   // 右：图层管理
                {"inspector", true},         // 右：Inspector
                {"well", false},             // 底：测井轨道
                {"seismic", false},
                {"composite_linked", false},
            },
            .readiness_checks = {
                "target_horizon",
                "initial_facies_present", "initial_facies_crs",
                "initial_facies_geometry",
                "well_prediction_linked",
                "seismic_prediction_confidence",
                "interpretation_saved",
            },
            .locked_groups = {"phase1.initial_facies"},
        },
        StageProfile{
            .stage = MappingStage::ConstraintFactor,
            .label = tool_policy::stage_label(
                MappingStage::ConstraintFactor),
            .description = tool_policy::stage_description(
                MappingStage::ConstraintFactor),
            .group_visibility = default_group_visibility(
                MappingStage::ConstraintFactor),
            .active_editing_roles = {
                std::string(layer_role::kProvenanceLine),
                std::string(layer_role::kProvenanceDirection),
                std::string(layer_role::kDistributionLine),
                std::string(layer_role::kPaleoShoreline),
                std::string(layer_role::kFaciesBoundary),
                std::string(layer_role::kFaultConstraint),
                std::string(layer_role::kMaskBoundary),
                std::string(layer_role::kInterpolationBoundary),
            },
            .tools = StageToolProfile{
                .edit_actions = {"add_line", "add_polygon",
                                 "move_feature", "vertex", "split",
                                 "merge", "delete_selected", "undo",
                                 "redo"},
                .context_actions = stage_context_action_ids(
                    MappingStage::ConstraintFactor),
            },
            .recommended_docks = {
                {"composite_layer", true},
                {"inspector", true},
                {"composite_input", false},
                {"well", false},
                {"seismic", false},
                {"composite_linked", false},
            },
            .readiness_checks = {
                "target_horizon",
                "phase1_interpretation", "constraints_present",
                "factors_complete", "factor_staleness",
            },
            .locked_groups = {"phase1.interpretation",
                              "phase1.initial_facies"},
        },
        StageProfile{
            .stage = MappingStage::IntegratedCompilation,
            .label = tool_policy::stage_label(
                MappingStage::IntegratedCompilation),
            .description = tool_policy::stage_description(
                MappingStage::IntegratedCompilation),
            .group_visibility = default_group_visibility(
                MappingStage::IntegratedCompilation),
            .active_editing_roles = {
                std::string(layer_role::kIntegratedFacies),
                std::string(layer_role::kIntegratedBoundary),
            },
            .tools = StageToolProfile{
                .edit_actions = {"add_polygon", "add_line",
                                 "move_feature", "vertex", "split",
                                 "merge", "delete_selected", "undo",
                                 "redo"},
                .context_actions = stage_context_action_ids(
                    MappingStage::IntegratedCompilation),
            },
            .recommended_docks = {
                {"composite_layer", true},
                {"inspector", true},
                {"composite_input", true},   // 证据选择
                {"well", false},
                {"seismic", false},
                {"composite_linked", false},
            },
            .readiness_checks = {
                "target_horizon",
                "evidence_available", "evidence_staleness",
                "integrated_draft", "qa_geometry_errors",
            },
            .locked_groups = {"phase1.interpretation",
                              "phase1.initial_facies",
                              "phase2.constraints", "phase2.factors"},
        },
    };
    switch (stage) {
    case MappingStage::FaciesCalibration:
        return profiles[0];
    case MappingStage::ConstraintFactor:
        return profiles[1];
    case MappingStage::IntegratedCompilation:
        return profiles[2];
    }
    return profiles[0];
}

const std::vector<const StageProfile*>& all_profiles() {
    static const std::vector<const StageProfile*> profiles = {
        &make_profile(MappingStage::FaciesCalibration),
        &make_profile(MappingStage::ConstraintFactor),
        &make_profile(MappingStage::IntegratedCompilation),
    };
    return profiles;
}

}  // namespace

bool StageToolProfile::allows_edit_action(
    const std::string& action_id) const {
    if (edit_actions.empty()) {
        return true;
    }
    return std::find(edit_actions.begin(), edit_actions.end(),
                     action_id) != edit_actions.end();
}

const StageProfile& stage_profile(MappingStage stage) {
    return make_profile(stage);
}

const std::vector<const StageProfile*>& stage_profiles() {
    return all_profiles();
}

const std::set<std::string>& governed_edit_actions() {
    static const std::set<std::string> actions = [] {
        std::set<std::string> union_set;
        for (const StageProfile* profile : all_profiles()) {
            union_set.insert(profile->tools.edit_actions.begin(),
                             profile->tools.edit_actions.end());
        }
        return union_set;
    }();
    return actions;
}

std::vector<std::string> profile_group_order() {
    std::vector<const GroupTemplate*> sorted;
    for (const GroupTemplate& tpl : system_group_templates()) {
        sorted.push_back(&tpl);
    }
    std::sort(sorted.begin(), sorted.end(),
              [](const GroupTemplate* a, const GroupTemplate* b) {
                  return a->order < b->order;
              });
    std::vector<std::string> order;
    for (const GroupTemplate* tpl : sorted) {
        order.push_back(tpl->group_id);
    }
    return order;
}

}  // namespace pwb::ui_composite
