// qgis_processing.provider — provider registration, algorithm discovery
// and parameter-schema battery. Real QgsApplication + real
// QgsProcessingRegistry; never a fake success.

#include <QSet>
#include <QStringList>

#include <qgsapplication.h>
#include <qgsprocessingalgorithm.h>
#include <qgsprocessingparameters.h>
#include <qgsprocessingregistry.h>

#include <pwb/qgis/qgis_runtime.hpp>
#include <pwb/qgis_processing/algorithm_ids.hpp>
#include <pwb/qgis_processing/provider.hpp>
#include <pwb/qgis_processing/runner.hpp>

#include "test_framework.hpp"

int main(int argc, char** argv) {
    QgsApplication app(argc, argv, true);
    pwb::qgis::QgisRuntime::acquire();

    // --- install / idempotence / probe ----------------------------------
    PWB_CHECK(pwb::qgis_processing::install_paleo_provider());
    PWB_CHECK(!pwb::qgis_processing::install_paleo_provider());
    PWB_CHECK(pwb::qgis_processing::paleo_provider_installed());

    QgsProcessingRegistry* registry = QgsApplication::processingRegistry();
    PWB_CHECK(registry != nullptr);
    PWB_CHECK(registry->providerById(
                  QString::fromLatin1(pwb::qgis_processing::kProviderId))
              != nullptr);

    // --- discovery -------------------------------------------------------
    const QStringList ids = pwb::qgis_processing::paleo_algorithm_ids();
    PWB_CHECK(!ids.isEmpty());
    const QString prefix =
        QString::fromLatin1(pwb::qgis_processing::kProviderId) +
        QLatin1Char(':');
    QSet<QString> seen;
    for (const QString& id : ids) {
        PWB_CHECK_MSG(id.startsWith(prefix),
                      ("id without paleo: prefix: " + id).toStdString());
        PWB_CHECK(!seen.contains(id));
        seen.insert(id);
    }
    PWB_CHECK(seen.size() == ids.size());

    // --- per-id metadata via the registry --------------------------------
    for (const QString& id : ids) {
        const QgsProcessingAlgorithm* algorithm = registry->algorithmById(id);
        PWB_CHECK_MSG(algorithm != nullptr,
                      ("algorithmById miss: " + id).toStdString());
        if (algorithm == nullptr) continue;
        PWB_CHECK_MSG(!algorithm->displayName().isEmpty(),
                      ("empty displayName: " + id).toStdString());
        PWB_CHECK_MSG(!algorithm->groupId().isEmpty(),
                      ("empty groupId: " + id).toStdString());
    }

    // Prototype lookup agrees with the registry instance.
    PWB_CHECK(pwb::qgis_processing::paleo_algorithm_prototype(
                  pwb::qgis_processing::paleo_id(
                      pwb::qgis_processing::kAlgInterpolationIdw)) !=
              nullptr);

    // --- IDW parameter schema ---------------------------------------------
    const QgsProcessingAlgorithm* idw = registry->algorithmById(
        pwb::qgis_processing::paleo_id(
            pwb::qgis_processing::kAlgInterpolationIdw));
    PWB_CHECK(idw != nullptr);
    if (idw != nullptr) {
        const QStringList required = {QStringLiteral("INPUT"),
                                      QStringLiteral("XFIELD"),
                                      QStringLiteral("YFIELD"),
                                      QStringLiteral("VALUEFIELD"),
                                      QStringLiteral("CRS"),
                                      QStringLiteral("OUTPUT")};
        for (const QString& name : required) {
            bool found = false;
            for (const QgsProcessingParameterDefinition* definition :
                 idw->parameterDefinitions()) {
                if (definition->name() == name) {
                    found = true;
                    break;
                }
            }
            PWB_CHECK_MSG(found,
                          ("IDW misses parameter " + name).toStdString());
        }
    }

    // --- unknown ids fail closed -------------------------------------------
    PWB_CHECK(registry->createAlgorithmById(QStringLiteral("paleo:nope")) ==
              nullptr);
    PWB_CHECK(registry->algorithmById(QStringLiteral("paleo:nope")) ==
              nullptr);

    // --- seismic family ------------------------------------------------------
    int seismic_count = 0;
    const QList<pwb::qgis_processing::PaleoAlgorithmInfo> infos =
        pwb::qgis_processing::paleo_algorithm_infos();
    for (const pwb::qgis_processing::PaleoAlgorithmInfo& info : infos) {
        if (info.group_id ==
            QString::fromLatin1(pwb::qgis_processing::kGroupSeismic)) {
            ++seismic_count;
        }
    }
    PWB_CHECK_MSG(seismic_count >= 11,
                  ("seismic algorithm count " +
                   std::to_string(seismic_count) + " < 11")
                      .c_str());
    // The generated family maps onto paleo:seismic_<name> ids.
    PWB_CHECK(pwb::qgis_processing::to_paleo_algorithm_id(
                  QStringLiteral("envelope"), QStringLiteral("seismic")) ==
              QStringLiteral("paleo:seismic_envelope"));

    pwb::qgis::QgisRuntime::release();
    return ::pwb::test::report("qgis_processing.provider");
}
