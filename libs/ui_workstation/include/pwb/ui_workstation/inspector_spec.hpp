#pragma once

// Port of paleo_workbench/ui/workstation/inspector.py's render layer
// (UI-12). The Python widget getattr-read live domain objects; the C++
// seam is explicit: a host adapter projects the object's scalar
// attributes into a flat string map (InspectorPayload.fields), and this
// Qt-free core owns the label vocabulary, row order, missing-value
// honesty ("—"), yes/no conversion, history rows, and the style-page
// summary — every line is honest: no invented values.
//
// Pages: 属性 (properties) / 解释 (interpretation) / 样式 (style) /
// 历史 (history).

#include <map>
#include <string>
#include <utility>
#include <vector>

namespace pwb::ui_workstation {

// Python INSPECTOR_PAGE_TITLES, insertion order.
const std::vector<std::string>& inspector_page_titles();

// ---------- payload ---------------------------------------------------

// The payload the inspector renders. `kind` selects the show_* builder
// (well / horizon / interpretation / layer / project / seismic /
// resource / map_component / curve / feature / factor / map_product /
// version / run; unknown kinds fall through to the generic scalar table —
// never dropped). `fields` holds adapter-projected scalar attributes
// keyed by the Python attribute name the core reads (e.g. fields["name"],
// fields["project_x"], fields["editable"]="1"/"0"); a missing key ==
// Python getattr(...) is None == honest "—". `attrs` holds extra object
// attributes for the generic table (_OBJECT_ATTR_ROWS parity).
// `seam_rows` is the injected layer-domain context (V6 §6 context seam —
// empty = seam absent, show nothing).
struct InspectorPayload {
    std::string kind;
    std::map<std::string, std::string> fields;
    // Ordered extra rows for generic/layer rendering: (key, value).
    std::vector<std::pair<std::string, std::string>> attrs;
    // Nested attribute table for "feature" payloads (sorted render, ≤12).
    std::map<std::string, std::string> attributes;
    // factor kind: pre-rendered summary rows (label, value, state) —
    // FactorSummary.to_display_dict()["rows"] parity; takes precedence.
    std::vector<std::tuple<std::string, std::string, std::string>>
        summary_rows;
    // List-valued facts joined by the core ("input_version_ids", …) —
    // rendered as "N 项".
    std::map<std::string, int> list_counts;
    // V6 §6 context seam rows: (label, value) pairs in adapter order.
    std::vector<std::pair<std::string, std::string>> seam_rows;
    // Non-null when the payload wraps a live object — the Qt panel uses
    // it only for the feature "指定相带…" button's emitted payload.
    const void* object = nullptr;
};

// ---------- render document -------------------------------------------

// Form sections are (label, value) rows — the Qt page renders each value
// in a read-only QLineEdit with the "missing" property set when the
// value is empty (Python _readonly parity: empty / "—" → missing).
struct InspectorDocument {
    std::string header;  // "检查器 · …" / "检查器"
    // Properties page + interpretation page form rows, in order.
    std::vector<std::pair<std::string, std::string>> properties_rows;
    std::vector<std::pair<std::string, std::string>> interpretation_rows;
    // Style page: summary text + whether the "在图层属性中编辑样式…"
    // button is visible (and the layer_id it emits).
    std::string style_summary;
    bool style_edit_visible = false;
    std::string style_edit_layer_id;
    // Feature payloads only: the "指定相带…" button row on the
    // interpretation page (emits assign_facies_requested).
    bool feature_assign_button = false;
    // History page rows.
    std::vector<std::string> history_rows;
};

// Dispatch by payload.kind (Python show_payload parity). project_name /
// target_horizon supply the project-context facts the Python builders
// read from self._project (empty = unknown → "—").
InspectorDocument build_inspector_document(
    const InspectorPayload& payload,
    const std::string& target_horizon = "");

// Empty state (Python show_empty): header "检查器", properties show
// "未选择对象", empty history.
InspectorDocument empty_inspector_document();

// ---------- helpers (Python parity, used by builders) ------------------

// _readonly honesty: a value is missing when absent, empty, or "—".
bool inspector_value_missing(const std::string& value);

// _yes_no: "" for absent; "是"/"否" otherwise. The adapter encodes bools
// as "1"/"0"/"true"/"false"; anything else non-empty is truthy.
std::string inspector_yes_no(const std::string& value);

// _compact_text: already-rendered values pass through; >80 chars →
// first 77 + "…".
std::string inspector_compact_text(const std::string& value);

// Format an epoch-ish pair "（耗时 %.1fs）" — empty when unparseable
// (Python try/except parity).
std::string inspector_elapsed_text(const std::string& started,
                                   const std::string& finished);

}  // namespace pwb::ui_workstation
