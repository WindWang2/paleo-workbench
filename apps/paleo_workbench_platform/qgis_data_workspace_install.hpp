#pragma once

// qgis_data_workspace_install — QGIS-native generic data browser dock
// (data-management convergence composition seam). Generic GIS datasource
// browsing is QGIS's job: this installs a QgsBrowserModel-backed dock
// whose activation admits layers through the provider registry
// (layer_factory). The Paleo data PAGE stays a domain view (wells →
// logs/tops/lineage); nothing here duplicates it — this seam only
// replaces the shell's hand-rolled generic file-dialog browsing.

class QMainWindow;

namespace pwb::app {
class MainWindow;
}

namespace pwb::app::qgis_data_workspace {

// Creates the "QGIS 数据浏览器" dock (left area, tabified with the layer
// tree dock when present) and wires double-click admission. Idempotent:
// a second call is a no-op.
void install_data_browser(pwb::app::MainWindow& window);

}  // namespace pwb::app::qgis_data_workspace
