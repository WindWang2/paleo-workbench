#pragma once

// UI-10 — Qt-free state core for composition_panel.py.
//
// The session/document/factory are mapping_document's; this core owns the
// panel's *view* decisions:
//   * element list entries (reversed z order, label + lock/visible suffixes,
//     raw-type "（未支持）" carrier)
//   * property-editor state (geometry, locked hint, editable gating)
//   * schema-driven editor descriptors (number/bool/choices/text/list/
//     series-table/str) incl. the [{label,value}] table-vs-JSON decision
//   * _apply_title / _apply_geometry session-call semantics
//   * history-state gating + preview/export text
//
// The element-type label table and chart-series schema descriptions are
// registry data the kernel deliberately does not port — injected maps.

#include <functional>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <utility>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/mapping_document/composition.hpp>
#include <pwb/mapping_document/composition_session.hpp>

namespace pwb::ui_seqviz {

using mapping_document::ComposerElement;
using mapping_document::Composition;
using mapping_document::CompositionEditSession;

// ---------------------------------------------------------------------------
// Element list (_refresh_list)
// ---------------------------------------------------------------------------

struct CompositionElementRow {
    std::string id;
    std::string label;   // "<type-label>[（未支持）][（锁定）][（隐藏）]"
    bool checked = true;  // element.visible
};

// ELEMENT_TYPE_LABELS seam — registry data (host injects; missing key ->
// the raw element_type string, Python dict.get fallback).
using ElementLabelFn = std::function<std::string(const std::string& type)>;

// reversed(document.elements) — deepest z first, exactly like the Qt list.
std::vector<CompositionElementRow> composition_element_rows(
    const Composition& document, const ElementLabelFn& label_fn);

// ---------------------------------------------------------------------------
// Property editor (_refresh_property_editor)
// ---------------------------------------------------------------------------

struct GeometryView {
    double x = 0, y = 0, w = 1, h = 1;
    bool editable = false;
    bool lock_hint_visible = false;
};

GeometryView property_geometry_state(const ComposerElement* element);

// -- schema-driven editor descriptors (_make_editor) -------------------------

enum class SchemaEditorKind {
    Number,      // QDoubleSpinBox (min/max/decimals=2/step=0.1)
    Bool,        // QCheckBox
    Choices,     // QComboBox (+ current-value prepend when not in choices)
    Text,        // QTextEdit (dirty-mark + focus-out commit)
    SeriesTable, // STAT_CHART [{label,value}] two-column table
    Json,        // list-shape → QLineEdit JSON box
    Str,         // single-line text (the fallback for unknown types)
};

struct SchemaEditorDesc {
    std::string name;         // prop["name"]
    std::string label;        // prop["label"] or name
    SchemaEditorKind kind = SchemaEditorKind::Str;
    // number
    double min = -1e9, max = 1e9;
    // choices
    std::vector<std::string> choices;
    // list→Json initial text: json.dumps(value or [], ensure_ascii=False)
    std::string json_text;
    // STAT_CHART series tooltip (CHART_SERIES_SCHEMAS description)
    std::string tooltip;
};

// The table-editor chart types (_TABLE_SERIES_CHART_TYPES verbatim).
extern const std::set<std::string>& table_series_chart_types();

// _series_is_label_value: every entry a dict with keys ⊆ {label,value};
// empty list/tuple is a table-compatible start shape.
bool series_is_label_value(const domain::Json& series);

// One schema row → descriptor. `element` is needed for the STAT_CHART
// series table-vs-JSON decision; `chart_series_schemas` is the injected
// registry table (CHART_SERIES_SCHEMAS).
SchemaEditorDesc schema_editor_desc(
    const domain::Json& prop, const ComposerElement& element,
    const std::map<std::string, std::string>& chart_series_schemas);

// The full dynamic row set for an element (spec.property_schema order).
// `property_schema` is the host registry's schema list for element's type.
std::vector<SchemaEditorDesc> schema_editor_descs(
    const domain::Json& property_schema, const ComposerElement& element,
    const std::map<std::string, std::string>& chart_series_schemas);

// The series table's collect() — (label, raw) rows → [{label, value}] with
// Python float coercion (unparseable → 0.0) and blank-row skip.
domain::Json series_collect(
    const std::vector<std::pair<std::string, std::string>>& rows);

// _on_schema_json_changed: text → parsed Json or nullopt (invalid → warn).
std::optional<domain::Json> schema_json_value(const std::string& text);

// Schema-editor value coercions — Python semantics used by _make_editor:
//   * bool(value)          — Python truthiness (null/0/0.0/""/[]/{} → false)
//   * float(0.0 if null)   — TypeError/ValueError → 0.0 (strings parse)
//   * str(value if not None else "") — bool → "True"/"False", numbers via
//     Python str() formatting, arrays/objects via json.dumps-compatible text
bool schema_bool_value(const domain::Json& value);
double schema_float_value(const domain::Json& value);
std::string schema_text_value(const domain::Json& value);

// ---------------------------------------------------------------------------
// Session-level edits (_apply_title / _apply_geometry)
// ---------------------------------------------------------------------------

// _apply_title: document.title = text (Python writes the attribute
// directly — not through a session command); the first unlocked TITLE
// element gets configure_element({"text": title}) (ComposerError
// swallowed per Python). The document is passed explicitly because the
// C++ session borrows it (no document() accessor).
bool apply_composition_title(CompositionEditSession& session,
                             Composition& document,
                             const std::string& title);

// _apply_geometry — move/scale via the session (never a raw field write).
// field ∈ {x,y,w,h}; locked/missing element → false (no-op).
bool apply_element_geometry(CompositionEditSession& session,
                            Composition& document,
                            const std::string& element_id,
                            const std::string& field, double value);

// ---------------------------------------------------------------------------
// History + preview text
// ---------------------------------------------------------------------------

struct HistoryState {
    bool can_undo = false;
    bool can_redo = false;
};
HistoryState history_state(const CompositionEditSession* session);

// _refresh_preview failure/success surface for the label.
enum class PreviewState { NoSession, RenderFailed, Ok };

// _register_catalog_export side-effect summary (host decides whether to
// call record_export — the seam returns the project pointer or null).
struct CatalogExportPlan {
    bool should_register = false;
    std::string linked_id = "composition";
    std::string format = "json";
};
CatalogExportPlan catalog_export_plan(bool project_available);

}  // namespace pwb::ui_seqviz
