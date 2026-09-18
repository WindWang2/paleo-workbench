#pragma once

// DiagnosticsReport — native replacement for the Python diagnostics CLI
// (main.py --version / --diagnostics) and the runtime-health probe surface
// (qgis_runtime/health.py QgisRuntimeStatus), honestly computed from the
// live process: real provider registry, real CRS round-trips, real
// transform check. Failures degrade the report (degraded_reasons), never
// fake success.

#include <nlohmann/json.hpp>

#include <string>

namespace pwb::platform_services {

// Runtime health probe, field-for-field the native subset of Python's
// QgisRuntimeStatus.as_dict() that has native meaning (bridge/recipe/
// canvas-snapping/topology are Python-shell concepts and stay there).
struct RuntimeProbe {
    bool qgis_available = false;
    std::string qgis_version;
    std::string prefix_path;
    bool proj_available = false;
    std::string proj_version;
    std::string proj_db_path;
    int provider_count = 0;
    std::vector<std::string> providers;
    std::vector<std::pair<std::string, bool>> crs_probes;
    bool transform_available = false;
    std::vector<std::string> svg_paths;
    std::vector<std::string> degraded_reasons;
    std::vector<std::string> native_features;

    nlohmann::ordered_json to_json() const;
};

// Probes the live QGIS runtime (requires QgisRuntime::acquire() first).
RuntimeProbe probe_qgis_runtime();

// Full human-readable diagnostics text: identity/build, Qt, QGIS runtime
// probe, paths, environment (session policy hint, locale). Printed by
// `pwb-platform --diagnostics`.
std::string environment_report_text();

// "paleo-workbench <version> (native <qt-version>)" — mirrors the Python
// --version line shape.
std::string version_line();

}  // namespace pwb::platform_services
