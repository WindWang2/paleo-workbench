#include <pwb/qgis_processing/provider.hpp>

#include <qgsapplication.h>
#include <qgsprocessingregistry.h>

#include <pwb/qgis_processing/algorithm_ids.hpp>
#include <pwb/qgis_processing/algorithms.hpp>

namespace pwb::qgis_processing {

QString PaleoProcessingProvider::id() const {
    return QString::fromLatin1(kProviderId);
}

QString PaleoProcessingProvider::name() const {
    return QStringLiteral("Paleo Workbench");
}

QString PaleoProcessingProvider::longName() const {
    return QStringLiteral("Paleo Workbench geological algorithms");
}

QString PaleoProcessingProvider::helpId() const {
    return QStringLiteral("paleo_workbench");
}

void PaleoProcessingProvider::loadAlgorithms() {
    auto add_all = [this](std::vector<QgsProcessingAlgorithm*> algorithms) {
        for (QgsProcessingAlgorithm* algorithm : algorithms) {
            addAlgorithm(algorithm);
        }
    };
    add_all(make_interpolation_algorithms());
    add_all(make_mapping_algorithms());
    add_all(make_factor_algorithms());
    add_all(make_seismic_algorithms());
    add_all(make_well_algorithms());
    add_all(make_cartography_algorithms());
    add_all(make_project_algorithms());
}

bool install_paleo_provider(QgsProcessingRegistry* registry) {
    if (registry == nullptr) {
        registry = QgsApplication::processingRegistry();
    }
    if (registry == nullptr) {
        throw std::logic_error(
            "install_paleo_provider: QgsApplication is not initialized "
            "(QgisRuntime::acquire must run first)");
    }
    if (registry->providerById(QString::fromLatin1(kProviderId)) != nullptr) {
        return false;
    }
    return registry->addProvider(new PaleoProcessingProvider());
}

bool paleo_provider_installed(QgsProcessingRegistry* registry) {
    if (registry == nullptr) {
        registry = QgsApplication::processingRegistry();
    }
    return registry != nullptr &&
           registry->providerById(QString::fromLatin1(kProviderId)) != nullptr;
}

}  // namespace pwb::qgis_processing
