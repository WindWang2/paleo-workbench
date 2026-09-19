// UI-15 — Qt-free symbology-bridge semantics (map_symbology_bridge.py
// frozen math). The QGIS target (pwb_ui_canvas_qgis) owns the actual
// dialog invocation; these helpers carry the request shaping + result
// payload rules so they stay testable headless:
//
//   * geometry detection from feature geometry.type
//   * the #937-2 empty-mirror guard (categorized/graduated with no
//     classifiable attribute → force single-symbol legacy migration)
//   * the dialog-request field assembly (legacy VectorStyle defaults)
//   * first-feature seed_values for unstyled categorized requests
//   * the accept-result → QgisStylePayload revision bump / labeling
//     carry-through
#pragma once

#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

#include <pwb/cartography/qgis_adapter.hpp>
#include <pwb/domain/json.hpp>

namespace pwb::ui_canvas {

using Json = pwb::domain::Json;

// A native symbology dialog could not run or returned an invalid payload
// (Python SymbologyBridgeError(RuntimeError)).
class SymbologyBridgeError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

// _geometry_type_for_layer parity: first feature whose geometry.type is a
// known GeoJSON kind wins; default "Polygon".
std::string geometry_type_for_features(const Json& features);

// The #937-2 empty-mirror / unclassified guard, verbatim: a categorized or
// graduated request with no fields AND no classification field would open an
// empty dialog — force single-symbol migration instead. Returns the
// (possibly rewritten) style.
Json normalize_dialog_style(Json style, const std::vector<std::string>& fields);

// The request shipped to the native dialog host — the Qt-free twin of
// GuiDialogRequest plus the labeling/seed extras the Python dict carried.
struct SymbologyRequest {
    std::string title;
    // Memory-provider geometry name: Point | LineString | Polygon | ...
    std::string geometry_type = "Polygon";
    std::string crs;
    std::vector<std::string> field_names;
    std::string renderer_xml;   // authoritative payload or migrated legacy XML
    std::string labeling_xml;   // authoritative labeling payload when present
    std::string fill = "#6c8ebf";
    std::string stroke = "#26364d";
    double stroke_width = 1.0;
    double marker_size = 6.0;
    // #937-2 alternative: seed categories from the first feature's
    // properties when the request still has no renderer XML.
    std::vector<std::string> seed_values;
};

// Assemble the renderer-properties request (open_renderer_properties
// request-dict parity). `payload` is the parsed qgis_style payload when the
// style carried one; `legacy_migrated_xml` is the optional migrated
// renderer_xml produced by the QGIS codec (nullptr/empty when unavailable —
// the caller decides whether migration is even possible).
SymbologyRequest build_renderer_request(
    const std::string& title, const Json& features, const std::string& crs,
    const std::vector<std::string>& fields, const Json& style,
    const std::optional<pwb::cartography::QgisStylePayload>& payload,
    const std::optional<std::string>& legacy_migrated_xml);

// The accepted-dialog result shape: {"qgis_style": payload_dict, "opacity":
// double}. Throws SymbologyBridgeError on an empty renderer; consumes the
// dialog's labeling_xml when present, else carries the existing payload's
// labeling through; revision = payload.revision + 1 (1 for a fresh payload).
Json apply_dialog_result(
    const std::optional<pwb::cartography::QgisStylePayload>& payload,
    const std::string& renderer_xml, const std::string& dialog_labeling_xml,
    double opacity);

// Same shape for the symbol selector: {"qgis_style": payload_dict} — no
// opacity (Python parity). Requires an existing payload (caller enforces).
Json apply_symbol_result(
    const pwb::cartography::QgisStylePayload& payload,
    const std::string& renderer_xml, const std::string& dialog_labeling_xml);

}  // namespace pwb::ui_canvas
