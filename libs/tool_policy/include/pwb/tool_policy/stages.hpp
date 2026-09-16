#pragma once

// Port of paleo_workbench/mapping_workspace/stages.py (V8 canonical contract).
// Workflow context, not a page: the same QGIS project/canvas/layer authority
// spans all stages; switching only changes tool sets and edit targets.

#include <array>
#include <optional>
#include <string>
#include <vector>

namespace pwb::tool_policy {

enum class MappingStage {
    FaciesCalibration,
    ConstraintFactor,
    IntegratedCompilation,
};

// Workflow order (switching in both directions is allowed).
inline constexpr std::array<MappingStage, 3> kStageOrder = {
    MappingStage::FaciesCalibration,
    MappingStage::ConstraintFactor,
    MappingStage::IntegratedCompilation,
};

const char* stage_value(MappingStage stage);
const char* stage_label(MappingStage stage);        // "① 智能预测" ...
const char* stage_short_label(MappingStage stage);
const char* stage_description(MappingStage stage);

// Tolerant parse: accepts the enum value, known aliases, or the Chinese
// display label; unknown/empty -> std::nullopt.
std::optional<MappingStage> stage_from_value(const std::string& value);

// Human label for an arbitrary (possibly unknown) stage value; used by
// evaluator reason strings.
std::string stage_display_or_raw(const std::string& value);

}  // namespace pwb::tool_policy
