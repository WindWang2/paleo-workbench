#pragma once

// Paleo QGIS Processing convergence — algorithm identity vocabulary.
//
// The single authority for algorithm existence, metadata and parameter
// schemas is QgsProcessingRegistry (provider id below). GUI, Agent, batch
// and E2E entrances address algorithms by these ids only; they never call
// the Qt-free science kernels directly.

#include <QString>

namespace pwb::qgis_processing {

inline constexpr auto kProviderId = "paleo";

// Full processing id: "paleo:<name>".
[[nodiscard]] inline QString paleo_id(const QString& name) {
    return QString::fromLatin1(kProviderId) + QLatin1Char(':') + name;
}

// Group ids (QgsProcessingAlgorithm::groupId) — one per domain family.
inline constexpr auto kGroupInterpolation = "interpolation";
inline constexpr auto kGroupMapping = "mapping";
inline constexpr auto kGroupFactor = "factor";
inline constexpr auto kGroupSeismic = "seismic";
inline constexpr auto kGroupWell = "well";
inline constexpr auto kGroupCartography = "cartography";
inline constexpr auto kGroupProject = "project";
inline constexpr auto kGroupQuality = "quality";
inline constexpr auto kGroupConversion = "conversion";
inline constexpr auto kGroupAnalysis = "analysis";
inline constexpr auto kGroupConstraint = "constraint";

// Algorithm names (the part after "paleo:").
inline constexpr auto kAlgInterpolationIdw = "interpolation_idw";
inline constexpr auto kAlgInterpolationKriging = "interpolation_kriging";
inline constexpr auto kAlgInterpolationConstrained = "interpolation_constrained";
inline constexpr auto kAlgInterpolationScipy = "interpolation_scipy";
inline constexpr auto kAlgInterpolationDirectional = "interpolation_directional";
inline constexpr auto kAlgGridContours = "grid_contours";
inline constexpr auto kAlgContourLayerProduct = "contour_layer_product";
inline constexpr auto kAlgGridStatistics = "grid_statistics";
inline constexpr auto kAlgExtractFactors = "extract_factors";
inline constexpr auto kAlgClipToRing = "clip_to_ring";
inline constexpr auto kAlgRepairRing = "repair_ring";
inline constexpr auto kAlgFactorFusion = "factor_fusion";
inline constexpr auto kAlgFaciesClassGrid = "facies_class_grid";
inline constexpr auto kAlgRepresentativeFacies = "representative_facies";
inline constexpr auto kAlgWellCurveOperation = "well_curve_operation";
inline constexpr auto kAlgWellLogMatch = "well_log_match";
inline constexpr auto kAlgWellHeadScatter = "well_head_scatter";
inline constexpr auto kAlgScalarClassification = "scalar_classification";
inline constexpr auto kAlgProjectValidateSources = "project_validate_sources";
inline constexpr auto kAlgBatchConvert = "batch_convert";

// Seismic attribute algorithms are generated from the IAlgorithm descriptor
// table (seismic.<name> -> paleo:seismic_<name>) — see algorithms/seismic.cpp.

// Maps a science-registry algorithm id onto the Processing id. Two accepted
// shapes: the domain-qualified kernel id ("seismic.envelope") or the bare
// name plus its domain ("envelope", "seismic"). Returns "paleo:seismic_<n>"
// for the seismic family (the only dynamically generated one); an empty
// string for any other domain (no paleo mapping exists — the caller fails
// closed on empty).
[[nodiscard]] inline QString to_paleo_algorithm_id(
    const QString& domain_name, const QString& domain = {}) {
    QString scoped = domain_name;
    if (!domain.isEmpty()) {
        scoped = domain + QLatin1Char('.') + domain_name;
    }
    const QString prefix =
        QString::fromLatin1(kGroupSeismic) + QLatin1Char('.');
    if (!scoped.startsWith(prefix)) return QString();
    return paleo_id(QString::fromLatin1(kGroupSeismic) + QLatin1Char('_')
                    + scoped.mid(prefix.size()));
}

}  // namespace pwb::qgis_processing
