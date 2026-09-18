#pragma once

// ResourceLocator — native resolution of bundled resources (icons,
// templates, help) without Python package resources. Resolution order:
//   1. PALEO_RESOURCES_DIR environment override (dev/deploy escape hatch);
//   2. the compile-time source tree (PWB_SOURCE_DIR /resources, dev runs);
//   3. install-relative <app_dir>/../share/paleo-workbench/resources;
//   4. QStandardPaths AppLocalDataLocation /resources (user-deployed).
//
// All lookups return an empty QString when a resource does not exist —
// honest miss, never a fabricated path.

#include <QString>
#include <QStringList>

namespace pwb::platform_services {

// The first existing candidate root (empty when none of them exists).
QString resources_root();

// resources_root() + "/" + relative_path, empty when the file is absent.
QString resource_file(const QString& relative_path);

// Convenience for the icon vocabulary ("layers.svg", ...).
QString icon_file(const QString& icon_name);

// Install/dev layout diagnostics: every candidate root probed (existing or
// not, in resolution order) for the diagnostics report.
QStringList resource_roots_probed();

}  // namespace pwb::platform_services
