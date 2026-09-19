#pragma once

// UI-09 — JointAnalysisState persistence (Qt-free).
//
// Ports paleo_workbench/project/models.py::JointAnalysisState
// (PRD #85/#90) field-for-field. Pydantic parity:
//   - to_json emits every field (model_dump semantics, defaults included)
//   - from_json applies field defaults; bounds are enforced by clamping on
//     load rather than rejecting — a saved project must always open
//     (well_width_px [2,10], time_slice_opacity [10,100], time_slices ≤ 8)
//   - optional fields round-trip as JSON null
//   - never stores preview voxels (no bulk arrays here by design)

#include <pwb/domain/json.hpp>
#include <pwb/ui_wellseis/slices.hpp>

namespace pwb::ui_wellseis {

// model_dump() — all keys present; optionals emit null.
domain::Json joint_state_to_json(const JointAnalysisSlice& state);

// model_validate() on already-parsed JSON — defaults for absent keys,
// clamps for out-of-range values, unknown keys ignored.
JointAnalysisSlice joint_state_from_json(const domain::Json& payload);

// Pydantic field bounds (mirrors models.py ge/le/max_length).
inline constexpr int kJointWellWidthMin = 2;
inline constexpr int kJointWellWidthMax = 10;
inline constexpr int kJointOpacityMin = 10;
inline constexpr int kJointOpacityMax = 100;
inline constexpr std::size_t kJointMaxTimeSlices = 8;

}  // namespace pwb::ui_wellseis
