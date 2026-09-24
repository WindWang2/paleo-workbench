#pragma once

// The Paleo Processing provider: single registration authority for Paleo
// algorithms inside QgsProcessingRegistry.

#include <qgsprocessingprovider.h>

class QgsProcessingRegistry;

namespace pwb::qgis_processing {

class PaleoProcessingProvider final : public QgsProcessingProvider {
public:
    QString id() const override;
    QString name() const override;
    QString longName() const override;
    QString helpId() const override;

protected:
    void loadAlgorithms() override;
};

// Idempotent installation into a registry (default: the QgsApplication
// singleton's). Returns true when the provider was newly added, false when
// it was already present. Requires QgsApplication init (QgisRuntime).
bool install_paleo_provider(QgsProcessingRegistry* registry = nullptr);

// True when the provider is registered (id lookup, does not install).
bool paleo_provider_installed(QgsProcessingRegistry* registry = nullptr);

}  // namespace pwb::qgis_processing
