#pragma once

// UI-09 — honest output labeling + small view-text helpers shared by the
// seismic control/context panels and the prediction feedback panel.
//
// Ports (verbatim semantics):
//   seismic_control_panel.py::update_state   -> seismic_output_nature
//   prediction_evidence_panel.py::update_state -> well_log_output_nature /
//                                               prediction_source_label
//   both pages' horizon probe               -> target_horizon_of
//   " × ".join(shape)                        -> volume_shape_text
//
// P2 contract: random/mock output never displays as 真实, heuristic output
// is not a scientific prediction, demo stays explicitly prefixed.

#include <array>
#include <cstdint>
#include <optional>
#include <string>

#include <pwb/domain/json.hpp>

namespace pwb::ui_wellseis {

using domain::Json;

// SeismicControlPanel "输出性质" text:
//   is_mock -> "Mock"
//   !final_scientific_prediction -> "启发式"
//   else -> "科学预测"
//   demo or source=="synthetic/demo" -> "Demo · " prefix
//   + " · " + ("可替换" if is_replaceable else "固定")
std::string seismic_output_nature(const Json& result_summary);

// PredictionEvidencePanel variant (well-log page): the online model types
// report "线上测井预测" instead of the mock/heuristic/scientific ladder;
// the Demo prefix keys on `demo` only (Python parity — the source check is
// seismic-panel specific).
std::string well_log_output_nature(const Json& result_summary);

// Evidence "来源" text: online -> 认证线上推理服务; demo/synthetic ->
// 合成演示数据; bound_las -> 绑定 LAS; else 合成曲线.
std::string prediction_source_label(const Json& result_summary,
                                    bool bound_las);

// model_metadata.target_horizon -> result_summary.target_horizon -> "".
std::string target_horizon_of(const Json& model_metadata,
                              const Json& result_summary);

// "a × b × c" or "—" (None shape).
std::string volume_shape_text(
    const std::optional<std::array<std::int64_t, 3>>& shape);

// The control panel attribute default (Python `label or "振幅"`).
std::string attribute_label_or_default(const std::string& label);

// Evidence facies count: len(result_summary.predicted_regions or []).
std::size_t predicted_region_count(const Json& result_summary);

// remote_summary.classCounts -> "甲 62.5%、乙 37.5%" (top-2 ranked) +
// per-class tooltip lines. Empty counts -> empty text ("—" is the
// panel's job). Numeric-only entries, Python parity.
struct ClassDistribution {
    std::string text;
    std::string tooltip;
};
ClassDistribution class_distribution_of(const Json& result_summary);

// task.evidence_contribution -> "{name}: {weight:.0%}" row texts
// (unnamed entries -> 未命名证据).
std::vector<std::string> evidence_rows(const Json& evidence_contribution);

}  // namespace pwb::ui_wellseis
