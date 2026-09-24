#pragma once

// Algorithm factory declarations, one per domain group. The provider is the
// ONLY place that assembles the full list.

#include <vector>

#include <qgsprocessingalgorithm.h>

namespace pwb::qgis_processing {

std::vector<QgsProcessingAlgorithm*> make_interpolation_algorithms();
std::vector<QgsProcessingAlgorithm*> make_mapping_algorithms();
std::vector<QgsProcessingAlgorithm*> make_factor_algorithms();
std::vector<QgsProcessingAlgorithm*> make_seismic_algorithms();
std::vector<QgsProcessingAlgorithm*> make_well_algorithms();
std::vector<QgsProcessingAlgorithm*> make_cartography_algorithms();
std::vector<QgsProcessingAlgorithm*> make_project_algorithms();

}  // namespace pwb::qgis_processing
