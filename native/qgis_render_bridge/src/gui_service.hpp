#pragma once

/// Native host for vendored QGIS symbology GUI.
///
/// QGIS professional editing components (QgsSymbolSelectorDialog,
/// QgsRendererPropertiesDialog, QgsStyleManagerDialog) are executed in-process
/// behind a narrow command boundary: Python sends the serialized renderer
/// payload plus layer context, C++ builds a temporary memory mirror layer,
/// runs the real QGIS dialog modally on the Qt GUI thread, and returns the
/// updated serialized payload.  No QWidget ever crosses the Python boundary
/// and all QObject ownership stays inside this module (RAII).

#include <string>
#include <vector>

namespace pwb::qgis_render {

struct GuiDialogRequest {
    std::string title;
    /// Memory-provider geometry name: Point | LineString | Polygon | MultiPolygon ...
    std::string geometry_type;
    std::string crs;
    std::vector<std::string> field_names;
    /// Current authoritative renderer XML payload (may be empty).
    std::string renderer_xml;
    /// Fallback legacy style fields used when renderer_xml is empty.
    std::string fill = "#6c8ebf";
    std::string stroke = "#26364d";
    double stroke_width = 1.0;
    double marker_size = 6.0;
    /// Managed QgsStyle database path; empty creates a throwaway database.
    std::string style_db_path;
};

struct GuiDialogResult {
    bool ok = false;
    std::string renderer_xml;
    double opacity = 1.0;
};

/// Open the full QGIS renderer properties dialog for one layer.
GuiDialogResult run_renderer_properties_dialog(const GuiDialogRequest& request);

/// Open the QGIS symbol selector for one symbol of the renderer.
/// ``symbol_index`` addresses renderer->symbols()[index].
GuiDialogResult run_symbol_selector_dialog(const GuiDialogRequest& request,
                                            int symbol_index);

/// Open the QGIS style manager against a managed style database.
bool run_style_manager_dialog(const std::string& style_db_path);

}  // namespace pwb::qgis_render
