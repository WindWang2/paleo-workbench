#pragma once

// MapProjectStore — QgsProject file persistence for a MapSession
// (QGIS-native data-management convergence). The session's QgsProject is
// the single persistence authority for GIS state: layer sources, CRS,
// styles, layer tree, visibility and the pwb/* domain join keys (layer
// custom properties ride along in the project XML). The Paleo document
// keeps only the POINTER (mapping_workspace.qgis_project_file) plus the
// domain semantics QGIS does not model (bindings' roles, stage views,
// lineage).
//
// Contract:
//   * save() writes <stem>.qgs through QgsProject::write (QGIS 4.2
//     truncates in place — no atomic write of its own), wrapped in a
//     two-phase .pwb-bak backup/restore so the last good file survives a
//     failed write; the error returns honestly and must abort the
//     caller's project save (no half-success).
//   * load() reads the file into the LIVE session project (canvases'
//     QgsLayerTreeMapCanvasBridge instances follow the rebuilt tree),
//     re-applies the project CRS to every canvas and reports invalid
//     layers as warnings — provider failures are surfaced, never faked.
//   * default_qgs_path() derives the sibling .qgs name from the Paleo
//     project file so the QGIS home equals the Paleo project directory
//     (relative layer paths — e.g. .pwb-working copies — resolve as-is).

#include <string>
#include <vector>

namespace pwb::qgis {

class MapSession;

namespace map_project_store {

// <name>.paleo.json | <name>.paleo  →  <name>.qgs (same directory).
std::string default_qgs_path(const std::string& paleo_project_file);

struct RestoreReport {
    bool ok = false;
    std::string error;                  // fatal: the file could not be read
    std::vector<std::string> warnings;  // honest per-layer provider failures
    int restored_layers = 0;            // valid layers in the restored tree
};

// Writes the session's QgsProject to qgs_path. Returns false + *error on
// failure (closed session included — same refusal contract as MapSession).
bool save(MapSession& session, const std::string& qgs_path, std::string* error);

// Reads qgs_path INTO the session's live QgsProject. A false return leaves
// the session usable but empty-handed (QgsProject::read clears first); the
// caller falls back to the legacy binding-materialization path.
RestoreReport load(MapSession& session, const std::string& qgs_path);

}  // namespace map_project_store
}  // namespace pwb::qgis
