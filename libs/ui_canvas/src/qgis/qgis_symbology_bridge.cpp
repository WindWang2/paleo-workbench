// UI-15 — native QGIS symbology dialog host (map_symbology_bridge.py
// parity).

#include <pwb/ui_canvas/qgis/qgis_symbology_bridge.hpp>

#include <pwb/ui_canvas/qgis/qgis_snapshot_backend.hpp>
#include <pwb/ui_canvas/qgis/snapshot_codec.hpp>

#include "gui_service.hpp"

namespace pwb::ui_canvas::qgis {

namespace {

// Map the Qt-free request onto the native GuiDialogRequest. The Python
// request dict carried labeling_xml/seed_values keys the native struct
// never read (parse_dialog_request ignores them) — they are documented
// on SymbologyRequest and intentionally dropped here.
pwb::qgis_render::GuiDialogRequest to_native_request(
    const SymbologyRequest& request) {
    pwb::qgis_render::GuiDialogRequest native;
    native.title = request.title;
    native.geometry_type = request.geometry_type;
    native.crs = request.crs;
    native.field_names = request.field_names;
    native.renderer_xml = request.renderer_xml;
    native.fill = request.fill;
    native.stroke = request.stroke;
    native.stroke_width = request.stroke_width;
    native.marker_size = request.marker_size;
    return native;
}

}  // namespace

bool qgis_symbology_available() { return qgis_backend_probe().first; }

std::optional<Json> open_renderer_properties(
    const std::string& title, const Json& features, const std::string& crs,
    const std::vector<std::string>& fields, const Json& style) {
    Json style_obj = style.is_object() ? style : Json::object();
    // #937-2 empty-mirror guard (normalize_dialog_style parity).
    style_obj = normalize_dialog_style(style_obj, fields);
    const auto payload =
        pwb::cartography::QgisStylePayload::from_dict(
            style_obj.value("qgis_style", Json()));
    const std::string geometry_type =
        geometry_type_for_features(features);
    std::optional<std::string> migrated;
    if (!payload.has_value()) {
        // Legacy layer without a payload yet: migrate the flat
        // VectorStyle vocabulary into real QGIS objects so the editor
        // opens on an equivalent renderer (lazy legacy_to_qgis_renderer
        // migration).
        const std::string xml =
            legacy_style_to_renderer_xml(style_obj, geometry_type);
        if (!xml.empty()) {
            migrated = xml;
        }
    }
    const SymbologyRequest request = build_renderer_request(
        title, features, crs, fields, style_obj, payload, migrated);
    pwb::qgis_render::GuiDialogResult result;
    try {
        result = pwb::qgis_render::run_renderer_properties_dialog(
            to_native_request(request));
    } catch (const std::exception& exc) {
        throw SymbologyBridgeError(
            std::string("QGIS renderer dialog failed: ") + exc.what());
    }
    if (!result.ok) {
        return std::nullopt;
    }
    // The native GuiDialogResult carries no labeling_xml — apply_dialog_result
    // falls back to the existing payload's labeling (#929 carry-through).
    return apply_dialog_result(payload, result.renderer_xml,
                               /*dialog_labeling_xml=*/"", result.opacity);
}

std::optional<Json> open_symbol_selector(
    const std::string& title, int symbol_index, const Json& features,
    const std::string& crs, const std::vector<std::string>& fields,
    const Json& style) {
    const Json style_obj = style.is_object() ? style : Json::object();
    const auto payload =
        pwb::cartography::QgisStylePayload::from_dict(
            style_obj.value("qgis_style", Json()));
    if (!payload.has_value()) {
        throw SymbologyBridgeError(
            "symbol-level editing requires an existing QGIS style "
            "payload");
    }
    pwb::qgis_render::GuiDialogRequest native;
    native.title = title;
    native.geometry_type = geometry_type_for_features(features);
    native.crs = crs;
    native.field_names = fields;
    native.renderer_xml = payload->renderer_xml;
    pwb::qgis_render::GuiDialogResult result;
    try {
        result = pwb::qgis_render::run_symbol_selector_dialog(
            native, symbol_index);
    } catch (const std::exception& exc) {
        throw SymbologyBridgeError(
            std::string("QGIS symbol dialog failed: ") + exc.what());
    }
    if (!result.ok) {
        return std::nullopt;
    }
    return apply_symbol_result(*payload, result.renderer_xml,
                               /*dialog_labeling_xml=*/"");
}

bool open_style_manager(const std::string& style_db_path) {
    try {
        return pwb::qgis_render::run_style_manager_dialog(style_db_path);
    } catch (const std::exception& exc) {
        throw SymbologyBridgeError(
            std::string("QGIS style manager failed: ") + exc.what());
    }
}

Json symbology_renderer_info(const std::string& renderer_xml) {
    return renderer_info(renderer_xml);
}

}  // namespace pwb::ui_canvas::qgis
