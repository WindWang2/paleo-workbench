#pragma once

// Port of the paleo_workbench/mapping_workspace/layer_roles.py value
// vocabulary consumed by the tool evaluator (line/polygon capture routing).
// Roles are plain strings on the wire (domain contract), not a closed enum:
// unknown roles stay unknown ("" handling matches the Python contract).

#include <string_view>

namespace pwb::tool_policy::layer_role {

inline constexpr std::string_view kBaseReference = "base_reference";
inline constexpr std::string_view kInitialFaciesSource = "initial_facies_source";
inline constexpr std::string_view kInitialFaciesDraft = "initial_facies_draft";
inline constexpr std::string_view kWellFaciesPrediction = "well_facies_prediction";
inline constexpr std::string_view kWellFaciesConfidence = "well_facies_confidence";
inline constexpr std::string_view kSeismicFaciesPrediction = "seismic_facies_prediction";
inline constexpr std::string_view kSeismicFaciesConfidence = "seismic_facies_confidence";
inline constexpr std::string_view kInterpretationAnnotation = "interpretation_annotation";
inline constexpr std::string_view kPendingReviewArea = "pending_review_area";
inline constexpr std::string_view kProvenanceDirection = "provenance_direction";
inline constexpr std::string_view kProvenanceLine = "provenance_line";
inline constexpr std::string_view kDistributionLine = "distribution_line";
inline constexpr std::string_view kPaleoShoreline = "paleo_shoreline";
inline constexpr std::string_view kFaciesBoundary = "facies_boundary";
inline constexpr std::string_view kFaultConstraint = "fault_constraint";
inline constexpr std::string_view kInterpolationBoundary = "interpolation_boundary";
inline constexpr std::string_view kMaskBoundary = "mask_boundary";
inline constexpr std::string_view kConstraintPoint = "constraint_point";
inline constexpr std::string_view kFactorInput = "factor_input";
inline constexpr std::string_view kFactorGrid = "factor_grid";
inline constexpr std::string_view kFactorContour = "factor_contour";
inline constexpr std::string_view kFactorClassification = "factor_classification";
inline constexpr std::string_view kFactorUncertainty = "factor_uncertainty";
inline constexpr std::string_view kFactorQc = "factor_qc";
inline constexpr std::string_view kAnalysisAid = "analysis_aid";
inline constexpr std::string_view kIntegratedFacies = "integrated_facies";
inline constexpr std::string_view kIntegratedBoundary = "integrated_boundary";
inline constexpr std::string_view kMapAnnotation = "map_annotation";
inline constexpr std::string_view kMapSymbol = "map_symbol";
inline constexpr std::string_view kMapReference = "map_reference";
inline constexpr std::string_view kQcWarning = "qc_warning";

bool is_line_role(std::string_view value);
bool is_polygon_role(std::string_view value);

}  // namespace pwb::tool_policy::layer_role
