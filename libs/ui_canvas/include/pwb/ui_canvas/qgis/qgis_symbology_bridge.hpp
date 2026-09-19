// UI-15 — native QGIS symbology dialog host (map_symbology_bridge.py
// port). The professional editors (QgsRendererPropertiesDialog,
// QgsSymbolSelectorDialog, QgsStyleManagerDialog) run inside the vendored
// bridge's gui_service on the Qt GUI thread; these functions collect the
// layer context, invoke the modal dialog, and return the updated
// authoritative qgis_style payload for the caller to apply through the
// normal style/revision path.
//
// Callers must be on the GUI thread. No QWidget crosses this boundary —
// the shell only anchors modality.
#pragma once

#include <optional>
#include <string>
#include <vector>

#include <pwb/ui_canvas/symbology_core.hpp>

namespace pwb::ui_canvas::qgis {

// True when the native symbology dialogs can be opened — the cached
// runtime probe (qgis_symbology_available parity; compiled-in bridge
// means importability is guaranteed, so the probe is the honest check).
bool qgis_symbology_available();

// open_renderer_properties parity: run the native renderer properties
// dialog for one vector layer. Returns {"qgis_style": payload_dict,
// "opacity": double} on accept, std::nullopt on cancel. Throws
// SymbologyBridgeError when the dialog cannot run or returns an invalid
// payload.
std::optional<Json> open_renderer_properties(
    const std::string& title, const Json& features, const std::string& crs,
    const std::vector<std::string>& fields, const Json& style);

// open_symbol_selector parity: edit one symbol slot of the existing
// renderer. Returns {"qgis_style": payload_dict} on accept, nullopt on
// cancel. Requires an existing qgis_style payload — throws
// SymbologyBridgeError otherwise.
std::optional<Json> open_symbol_selector(
    const std::string& title, int symbol_index, const Json& features,
    const std::string& crs, const std::vector<std::string>& fields,
    const Json& style);

// open_style_manager parity: run the native style manager on a managed
// database file. Returns the dialog's accept flag; throws
// SymbologyBridgeError on failure.
bool open_style_manager(const std::string& style_db_path);

// renderer_info parity (bindings.cpp renderer_info): {"type",
// "symbol_count"} for a serialized renderer payload, null Json when it
// does not parse — exposed here for the properties dialog's
// SymbologyHooks::renderer_info seam.
Json symbology_renderer_info(const std::string& renderer_xml);

}  // namespace pwb::ui_canvas::qgis
