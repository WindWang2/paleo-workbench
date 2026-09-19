#pragma once

// Port of paleo_workbench/mapping_workspace/layer_roles.py semantics
// (UI-13): role labels, ROLE_EDITABLE / ROLE_RAW_PROTECTED /
// FACIES_FAMILY_ROLES, ConstraintKind vocabulary + layer-role /
// interpolation-role mappings, tolerant parsers.
//
// Roles are plain strings on the wire (domain contract): the value
// vocabulary itself lives in pwb::tool_policy::layer_role — the SAME
// strings, so a single vocabulary exists across libs. This header adds
// the composite-workspace semantics that the tool evaluator does not own.
//
// Qt-free.

#include <optional>
#include <set>
#include <string>
#include <vector>

namespace pwb::ui_composite {

// Re-export the canonical value vocabulary (same wire strings).
namespace layer_role {
inline constexpr std::string_view kBaseReference = "base_reference";
inline constexpr std::string_view kInitialFaciesSource =
    "initial_facies_source";
inline constexpr std::string_view kInitialFaciesDraft =
    "initial_facies_draft";
inline constexpr std::string_view kWellFaciesPrediction =
    "well_facies_prediction";
inline constexpr std::string_view kWellFaciesConfidence =
    "well_facies_confidence";
inline constexpr std::string_view kSeismicFaciesPrediction =
    "seismic_facies_prediction";
inline constexpr std::string_view kSeismicFaciesConfidence =
    "seismic_facies_confidence";
inline constexpr std::string_view kInterpretationAnnotation =
    "interpretation_annotation";
inline constexpr std::string_view kPendingReviewArea =
    "pending_review_area";
inline constexpr std::string_view kProvenanceDirection =
    "provenance_direction";
inline constexpr std::string_view kProvenanceLine = "provenance_line";
inline constexpr std::string_view kDistributionLine = "distribution_line";
inline constexpr std::string_view kPaleoShoreline = "paleo_shoreline";
inline constexpr std::string_view kFaciesBoundary = "facies_boundary";
inline constexpr std::string_view kFaultConstraint = "fault_constraint";
inline constexpr std::string_view kInterpolationBoundary =
    "interpolation_boundary";
inline constexpr std::string_view kMaskBoundary = "mask_boundary";
inline constexpr std::string_view kFactorInput = "factor_input";
inline constexpr std::string_view kFactorGrid = "factor_grid";
inline constexpr std::string_view kFactorContour = "factor_contour";
inline constexpr std::string_view kFactorClassification =
    "factor_classification";
inline constexpr std::string_view kFactorUncertainty = "factor_uncertainty";
inline constexpr std::string_view kFactorQc = "factor_qc";
inline constexpr std::string_view kAnalysisAid = "analysis_aid";
inline constexpr std::string_view kIntegratedFacies = "integrated_facies";
inline constexpr std::string_view kIntegratedBoundary =
    "integrated_boundary";
inline constexpr std::string_view kMapAnnotation = "map_annotation";
inline constexpr std::string_view kMapSymbol = "map_symbol";
inline constexpr std::string_view kMapReference = "map_reference";
inline constexpr std::string_view kQcWarning = "qc_warning";
inline constexpr std::string_view kQcConflict = "qc_conflict";
inline constexpr std::string_view kUserGeneral = "user_general";
inline constexpr std::string_view kLegacyUnclassified =
    "legacy_unclassified";
}  // namespace layer_role

// ConstraintKind value vocabulary (typed geological constraint, V5 §22).
namespace constraint_kind {
inline constexpr std::string_view kSourceDirection = "source_direction";
inline constexpr std::string_view kProvenanceLine = "provenance_line";
inline constexpr std::string_view kDistributionLine = "distribution_line";
inline constexpr std::string_view kPaleoShoreline = "paleo_shoreline";
inline constexpr std::string_view kFaciesBoundary = "facies_boundary";
inline constexpr std::string_view kFault = "fault";
inline constexpr std::string_view kInterpolationBoundary =
    "interpolation_boundary";
inline constexpr std::string_view kMask = "mask";
inline constexpr std::string_view kExclusionArea = "exclusion_area";
inline constexpr std::string_view kTrendLine = "trend_line";
}  // namespace constraint_kind

// ROLE_LABELS parity: known role value → Chinese display label; unknown
// values return the value itself (Python dict.get(role, role.value)).
std::string role_label(const std::string& role_value);

// CONSTRAINT_KIND_LABELS parity: throws std::out_of_range for unknown
// kinds (Python dict[key] KeyError parity).
std::string constraint_kind_label(const std::string& kind_value);

// Membership predicates (frozenset parity — known values only).
bool role_is_editable(const std::string& role_value);
bool role_is_raw_protected(const std::string& role_value);
bool role_is_prediction(const std::string& role_value);
bool is_facies_family_role(const std::string& role_value);

const std::set<std::string>& role_editable_set();
const std::set<std::string>& role_raw_protected_set();
const std::set<std::string>& facies_family_roles();

// Tolerant parsers: strip + lowercase; unknown/empty → nullopt (caller
// decides the LEGACY_UNCLASSIFIED fallback).
std::optional<std::string> layer_role_from_value(const std::string& value);
std::optional<std::string> constraint_kind_from_value(
    const std::string& value);

// ConstraintKind.geometry_kind parity — "polygon" for MASK/EXCLUSION_AREA,
// else "line"; unknown → "line".
std::string constraint_kind_geometry_kind(const std::string& kind_value);

// CONSTRAINT_KIND_ROLE parity — kind → its home LayerRole value;
// unknown → nullopt.
std::optional<std::string> constraint_kind_layer_role(
    const std::string& kind_value);

// CONSTRAINT_INTERPOLATION_ROLE parity — kind → ConstraintLine.role
// interpolation-engine semantics ("direction"|"boundary"|"break");
// unknown → nullopt.
std::optional<std::string> constraint_interpolation_role(
    const std::string& kind_value);

// Every known LayerRole value (registry iteration order = declaration).
const std::vector<std::string>& all_layer_roles();

}  // namespace pwb::ui_composite
