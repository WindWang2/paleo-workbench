#include <pwb/platform_services/diagnostics_report.hpp>

#include <QLocale>
#include <QStandardPaths>
#include <QtGlobal>

#include <qgsapplication.h>
#include <qgscoordinatereferencesystem.h>
#include <qgscoordinatetransform.h>
#include <qgsexception.h>
#include <qgsproject.h>
#include <qgsproviderregistry.h>
#include <qgsprojutils.h>

#include <cmath>
#include <cstdio>

#include <pwb/platform_services/theme_tokens.hpp>
#include <pwb/platform_services/qt_session_policy.hpp>
#include <pwb/qgis/qgis_runtime.hpp>

namespace pwb::platform_services {
namespace {

// CRS probes mirror health.py: identity + projected systems must resolve,
// validate and round-trip their authority code.
std::vector<std::pair<std::string, bool>> run_crs_probes() {
    std::vector<std::pair<std::string, bool>> probes;
    const struct {
        const char* authid;
        const char* wkt_hint;
    } cases[] = {
        {"EPSG:4326", "WGS 84"},
        {"EPSG:3857", "Pseudo-Mercator"},
        {"EPSG:4490", "CGCS2000"},
    };
    for (const auto& probe : cases) {
        QgsCoordinateReferenceSystem crs(probe.authid);
        bool ok = crs.isValid() && crs.authid() == probe.authid;
        probes.emplace_back(probe.authid, ok);
    }
    return probes;
}

}  // namespace

nlohmann::ordered_json RuntimeProbe::to_json() const {
    auto probes = nlohmann::ordered_json::array();
    for (const auto& [authid, ok] : crs_probes) {
        probes.push_back(nlohmann::ordered_json{authid, ok});
    }
    auto provider_list = nlohmann::ordered_json::array();
    for (const auto& provider : providers) {
        provider_list.push_back(provider);
    }
    auto svg_list = nlohmann::ordered_json::array();
    for (const auto& path : svg_paths) {
        svg_list.push_back(path);
    }
    auto degraded = nlohmann::ordered_json::array();
    for (const auto& reason : degraded_reasons) {
        degraded.push_back(reason);
    }
    auto native = nlohmann::ordered_json::array();
    for (const auto& feature : native_features) {
        native.push_back(feature);
    }
    return nlohmann::ordered_json{
        {"qgis_available", qgis_available},
        {"qgis_version", qgis_version},
        {"prefix_path", prefix_path},
        {"proj_available", proj_available},
        {"proj_version", proj_version},
        {"proj_db_path", proj_db_path},
        {"provider_count", provider_count},
        {"providers", provider_list},
        {"crs_probes", probes},
        {"transform_available", transform_available},
        {"svg_paths", svg_list},
        {"degraded_reasons", degraded},
        {"native_features", native},
    };
}

RuntimeProbe probe_qgis_runtime() {
    RuntimeProbe probe;
    probe.native_features.emplace_back("cpp-platform");
    probe.native_features.emplace_back("qgis-native");

    if (!pwb::qgis::QgisRuntime::initialized()) {
        probe.degraded_reasons.emplace_back(
            "qgis runtime not initialized (QgisRuntime::acquire not called)");
        return probe;
    }
    probe.qgis_available = true;
    probe.qgis_version = pwb::qgis::QgisRuntime::qgis_version();
    probe.prefix_path = pwb::qgis::QgisRuntime::prefix_path();

    // Providers: the real registry, not a hardcoded list.
    const QStringList provider_list =
        QgsProviderRegistry::instance()->providerList();
    for (const QString& provider : provider_list) {
        probe.providers.push_back(provider.toStdString());
    }
    probe.provider_count = static_cast<int>(probe.providers.size());
    if (probe.provider_count == 0) {
        probe.degraded_reasons.emplace_back("no data providers registered");
    }

    probe.crs_probes = run_crs_probes();
    for (const auto& [authid, ok] : probe.crs_probes) {
        if (!ok) {
            probe.degraded_reasons.emplace_back("CRS probe failed: " + authid);
        }
    }

    // Transform check: EPSG:4326 -> EPSG:3857 on a real coordinate.
    QgsCoordinateReferenceSystem wgs84(QStringLiteral("EPSG:4326"));
    QgsCoordinateReferenceSystem web_mercator(QStringLiteral("EPSG:3857"));
    if (wgs84.isValid() && web_mercator.isValid()) {
        const QgsCoordinateTransform transform(
            wgs84, web_mercator, QgsProject::instance());
        try {
            const QgsPointXY out =
                transform.transform(QgsPointXY(114.0, 22.5));
            // (114E, 22.5N) -> x = R*lambda ~= 12690422,
            // y = R*ln(tan(45deg + phi/2)) ~= 2571663.
            probe.transform_available =
                std::abs(out.x() - 12690422.0) < 3000.0
                && std::abs(out.y() - 2571663.0) < 3000.0;
        } catch (const QgsCsException&) {
            probe.transform_available = false;
        }
    }
    if (!probe.transform_available) {
        probe.degraded_reasons.emplace_back(
            "EPSG:4326 -> EPSG:3857 transform probe failed");
    }

    // PROJ availability via the real version query (major.minor).
    probe.proj_available = wgs84.isValid();
    if (probe.proj_available) {
        probe.proj_version = std::to_string(QgsProjUtils::projVersionMajor())
                             + "."
                             + std::to_string(
                                 QgsProjUtils::projVersionMinor());
    }
    for (const QString& path : QgsApplication::svgPaths()) {
        probe.svg_paths.push_back(path.toStdString());
    }
    return probe;
}

std::string version_line() {
    return "paleo-workbench " + app_version() + " (native " + qVersion()
           + ")";
}

std::string environment_report_text() {
    std::string text;
    text.reserve(2048);
    text += "=== Paleo Workbench Platform Diagnostics ===\n";
    text += "Identity:    " + version_line() + "\n";
    text += "Build type:  "
          + std::string(
#ifdef NDEBUG
                "Release"
#else
                "Debug"
#endif
          ) + "\n";
    text += "Qt:          " + std::string(qVersion()) + "\n";

    const RuntimeProbe probe = probe_qgis_runtime();
    text += "QGIS:        "
          + std::string(probe.qgis_available ? probe.qgis_version
                                             : "unavailable") + "\n";
    if (probe.qgis_available) {
        text += "Prefix:      " + probe.prefix_path + "\n";
    }
    text += "Providers:   "
          + std::to_string(probe.provider_count) + " registered\n";
    for (const auto& [authid, ok] : probe.crs_probes) {
        text += "  CRS " + authid + ": " + (ok ? "ok" : "FAILED") + "\n";
    }
    text += "Transform 4326->3857: "
          + std::string(probe.transform_available ? "ok" : "FAILED") + "\n";

    text += "Paths:\n";
    text += "  AppData:   "
          + QStandardPaths::writableLocation(
                QStandardPaths::AppLocalDataLocation)
                 .toStdString() + "\n";
    text += "  Settings:  "
          + QStandardPaths::writableLocation(
                QStandardPaths::AppConfigLocation)
                 .toStdString() + "\n";

    text += "Environment:\n";
    text += "  Platform:  " + effective_qt_platform_hint() + "\n";
    text += "  Locale:    "
          + QLocale::system().name().toStdString() + "\n";
    if (!probe.degraded_reasons.empty()) {
        text += "Degraded:\n";
        for (const auto& reason : probe.degraded_reasons) {
            text += "  - " + reason + "\n";
        }
    }
    return text;
}

}  // namespace pwb::platform_services
