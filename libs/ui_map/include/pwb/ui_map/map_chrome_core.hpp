#pragma once

// UI-05 — Qt-free core for the qgs-map slice (paleo_workbench/ui/pages/
// {mapping_page, map_canvas_panel, map_layer_tree, map_dock_manager,
// map_document_panel, map_chrome_panel, workarea_map_widget}.py).
//
// Everything here is pure: constants + the page-level semantics that do not
// touch Qt — document keys, active-document selection, mode/visibility
// rules, dock-splitter precedence, unified-revision translation, field-name
// harvest, mapping_context projection, overlay/legend composition, extent
// history, zoom math, toolbar-strip grouping, tool-rebind decisions,
// work-area picking/extent vocabulary. Frozen by
// ui_map_tests/fixtures/ui_map_oracle.json (tools/oracle/
// generate_ui_map_fixtures.py replayed against the real Python modules).
//
// Documents travel as pwb::domain::Json records — the same "legacy
// PaleoMapDocument == JSON object" convention mapping_document::document_io
// established (facies_polygons / well_overlays / line_features /
// label_features / reference_layers / map_chrome / layer_state / view_state).

#include <array>
#include <functional>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <utility>
#include <vector>

#include <pwb/domain/json.hpp>

namespace pwb::ui_map {

using Json = pwb::domain::Json;

// ---------------------------------------------------------------------------
// Frozen constants
// ---------------------------------------------------------------------------

// Docked height cap for the bottom workbench (uncapped while floating).
inline constexpr int kBottomDockedMaxHeight = 220;
// Qt's "no maximum size" sentinel (QWIDGETSIZE_MAX).
inline constexpr int kWidgetSizeMax = 16777215;
// Namespaced FloatController keys of the page's floatable panels.
inline const std::array<const char*, 5> kFloatKeys = {
    "mapping:layers", "mapping:reference", "mapping:chrome",
    "mapping:composer", "mapping:bottom"};
// Pseudo-panel key under which the dock splitter sizes are persisted.
inline constexpr const char* kDockSplitterKey = "mapping:dock_splitter";

// Dock rail metrics (map_dock_manager.py).
inline constexpr int kRailWidth = 36;
inline constexpr int kRailButtonSize = 28;
inline constexpr int kRailIconSize = 18;

// Legacy layer-tree vocabulary (map_layer_tree.py).
inline const std::array<const char*, 4> kLayerKeys = {
    "facies", "well", "line", "label"};
const std::map<std::string, std::string>& layer_labels();  // 相带/井/线/注记
// reconcile stable-key namespaces.
inline constexpr const char* kRootKey = "__root__";
inline constexpr const char* kRefGroupKey = "refgroup";

// Chrome element vocabulary (map_chrome_panel.py / workarea overlay).
const std::vector<std::string>& default_chrome_elements();  // 图例/指北针/比例尺/标题栏

// Well picking tolerance (workarea_map_widget._WELL_PICK_RADIUS_PX).
inline constexpr double kWellPickRadiusPx = 16.0;
// Map click drag tolerance (display_canvas _ClickFilter manhattan length).
inline constexpr double kMapClickDragTolerance = 6.0;

// Authoring kind -> evaluator geometry kind (mapping_page
// _AUTHORING_KIND_GEOMETRY).
const std::map<std::string, std::string>& authoring_kind_geometry();

// Tools that capture the active layer/index/session at construction and must
// be rebound on layer switch (mapping_page _LAYER_BOUND_TOOL_ACTIONS).
const std::set<std::string>& layer_bound_tool_actions();
// Kind-forcing tools: deactivate to "pan" when the layer switch moved away
// from their kind (mapping_page _KIND_BOUND_TOOL_ACTIONS).
const std::map<std::string, std::string>& kind_bound_tool_actions();

// Domain semantic colours (decisions D10 exception): factor colormap
// fallback / fault reference style / legend swatch default.
inline constexpr const char* kLegendSwatchFallback = "#6c8ebf";
const std::map<std::string, Json>& fault_ref_style();  // fill/stroke/stroke_width
const std::vector<std::pair<double, std::string>>& factor_ramp_fallback();

// Work-area snapshot vocabulary (mapping/workarea_map_snapshot.py — the
// producer is the mapping domain; the widget consumes its output shape).
inline constexpr const char* kWorkareaBoundaryLayerId = "home_workarea:boundary";
inline constexpr const char* kWorkareaSurveyLayerId = "home_workarea:surveys";
inline constexpr const char* kWorkareaSurveyLabelLayerId =
    "home_workarea:survey_labels";
inline constexpr const char* kWorkareaWellsLayerId = "home_workarea:wells";
inline constexpr const char* kWorkareaWellsFlaggedLayerId =
    "home_workarea:wells_flagged";
// (label, color) pairs — WORKAREA_LEGEND_ITEMS verbatim.
const std::vector<std::pair<std::string, std::string>>&
workarea_legend_items();

// ---------------------------------------------------------------------------
// Document access (viz.prediction_helpers.field_value / mapping_helpers)
// ---------------------------------------------------------------------------

// field_value(source, name, default): dict.get parity — Json object member
// access; non-objects and missing keys yield `fallback`.
Json field_value(const Json& source, const std::string& name,
                 const Json& fallback = Json(nullptr));
std::string field_value_str(const Json& source, const std::string& name,
                            const std::string& fallback = "");

// active_map_document(docs, prefer_id): prefer_id still present -> that doc;
// otherwise the LAST document (most recently added). nullptr on empty.
const Json* active_map_document(const std::vector<Json>& documents,
                                const std::string& prefer_id = "");

// map_layer_tree._document_key: "doc:<id>" when the doc carries an id, else
// the identity fallback "doc@<tag>" (Python id(doc) — unstable by design;
// callers pass a stable identity tag for their object).
std::string document_key(const Json& document, const void* identity = nullptr);
// map_layer_tree._reference_layer_key: "ref:<id>" | "ref@<identity>".
// Python reads getattr(layer,"id") — reference layers there are objects;
// here layers are Json records so the id FIELD is read instead (the same
// intended stable key space; see ledger divergence note).
std::string reference_layer_key(const Json& layer, const void* identity = nullptr);
// map_document_panel._document_key: bare id or "doc@<identity>".
std::string document_list_key(const Json& document, const void* identity = nullptr);

// map_dock_manager.panel_title fallback: last ":"-separated segment, or the
// whole key when no ":" is present (Python str.rpartition parity).
std::string panel_title_fallback(const std::string& key);

// mapping_page._reference_scene_layer_id:
// "<document_id or 'map'>:reference:<reference_id>".
std::string reference_scene_layer_id(const std::string& document_id_or_empty,
                                     const std::string& reference_id);

// ---------------------------------------------------------------------------
// Mode / visibility rules (mapping_page._apply_mode_ui + set_canvas_priority)
// ---------------------------------------------------------------------------

struct ModeUiState {
    // Center stack page: 0 = edit view, 1 = preview host (Python index).
    int center_index = 0;
    // preview_canvas_stack shows the unified canvas (vs the legacy panel).
    bool preview_shows_unified = false;
    // Bottom workbench effective visibility (user preference AND not
    // canvas-priority AND not preview).
    bool bottom_visible = true;
};

ModeUiState resolve_mode_ui(bool preview_mode, bool unified_authoring_mode,
                            bool canvas_priority, bool bottom_user_visible);

// Bottom workbench height cap by float state.
constexpr int bottom_height_cap(bool floating) {
    return floating ? kWidgetSizeMax : kBottomDockedMaxHeight;
}

// ---------------------------------------------------------------------------
// Dock splitter size precedence (mapping_page._saved_dock_splitter_sizes)
// ---------------------------------------------------------------------------

// Best-known docked sizes: the splitter record ("mapping:dock_splitter"),
// then the "mapping:layers" panel record's docked_sizes, then the in-memory
// default — Python's three-level fallback.
std::vector<int> saved_dock_splitter_sizes(
    const std::optional<std::vector<int>>& dock_record,
    const std::optional<std::vector<int>>& layers_record,
    const std::vector<int>& fallback);

// ---------------------------------------------------------------------------
// Unified revision translation (mapping_page._unified_data_revisions)
// ---------------------------------------------------------------------------

// Translates authoring-layer raw revision keys into small effective integers
// so unchanged refreshes skip feature rebuilding. A NEW authoring object
// forces a bump on every kind even when raw keys repeat (feature cache keys
// must never collide) — the owner identity comparison mirrors Python's.
struct UnifiedRevisionState {
    const void* owner = nullptr;                 // authoring document identity
    std::map<std::string, Json> raw;             // kind -> last raw key
    std::map<std::string, long long> effective;  // kind -> counter (starts 1)
};

// raw_revision_fn: kind -> opaque raw key (host binds
// authoring.data_revision_key). Returns nullopt when authoring is absent or
// unified_authoring_mode is off (Python None).
std::optional<std::map<std::string, long long>> unified_data_revisions(
    UnifiedRevisionState& state, const void* authoring,
    bool unified_authoring_mode,
    const std::function<Json(const std::string& kind)>& raw_revision_fn);

// ---------------------------------------------------------------------------
// Attribute-table helpers (mapping_page._sync_attribute_table_from_authoring)
// ---------------------------------------------------------------------------

// (layer.data_revision << 32) + session.revision — the packed cache key.
constexpr long long pack_attribute_revision(long long data_revision,
                                            long long session_revision) {
    return (data_revision << 32) + session_revision;
}

// ---------------------------------------------------------------------------
// Layer field names (mapping_page._layer_field_names)
// ---------------------------------------------------------------------------

// Attribute names available for symbology classification: insertion order,
// deduplicated, "__"-internal keys skipped. The 64-entry cap is evaluated
// BETWEEN features (all keys of one feature are appended first) — Python
// _layer_field_names parity.
std::vector<std::string> layer_field_names(const Json& vector_features);

// ---------------------------------------------------------------------------
// Mapping context / dirty projection
// ---------------------------------------------------------------------------

// mapping_page.mapping_context(): active map name / horizon / dirty /
// preview for the sidebar.
Json mapping_context(const Json* active_document, bool dirty, bool preview);

// is_dirty(): presentation OR authoring OR legacy-scene dirty.
constexpr bool is_dirty(bool presentation_dirty, bool authoring_dirty,
                        bool scene_dirty) {
    return presentation_dirty || authoring_dirty || scene_dirty;
}

// ---------------------------------------------------------------------------
// Unified overlay state (mapping_page._unified_overlay_state + legend)
// ---------------------------------------------------------------------------

// Minimal registry-layer view the legend composition reads; the host
// projects from whatever layer registry it owns (vector/scalar/group).
struct LegendLayerView {
    std::string name;
    bool visible = true;
    bool is_group = false;
    std::string style_fill;    // vector_style["fill"] or ""
    std::string style_stroke;  // vector_style["stroke"] or ""
};

// Legend rows: every visible non-group layer -> {"label", "color"} with
// fill -> stroke -> fallback color precedence.
Json legend_items(const std::vector<LegendLayerView>& layers);

// Decorations payload: chrome["title"] or doc name, chrome["elements"] or
// the default four, legend rows. Python dict shape.
Json overlay_decorations(const Json& chrome, const std::string& document_name,
                         const std::vector<LegendLayerView>& layers);

// Full overlay provider payload: selected features (verbatim Json array),
// tool capture points, snap point, decorations.
Json unified_overlay_state(const Json& selected_features,
                           const Json& capture_points, const Json& snap_point,
                           const Json& chrome, const std::string& document_name,
                           const std::vector<LegendLayerView>& layers);

// snapshot_source_version_ids (display_canvas): unique layer
// source_version_id values in first-seen order (dict.fromkeys parity).
std::vector<std::string> snapshot_source_version_ids(const Json& snapshot);

// ---------------------------------------------------------------------------
// Extent math + history (qgis_stack/display_canvas.py frozen semantics)
// ---------------------------------------------------------------------------

using Extent = std::array<double, 4>;  // (xmin, ymin, xmax, ymax)

// map_units_per_pixel: max(span_x / w, span_y / h); 1.0 on degenerate input
// or failure (Python try/except fallback).
double map_units_per_pixel(const Extent& view_extent, int width_px,
                           int height_px);

// zoom_by: scale the extent around `center` (extent midpoint when absent).
// factor must be positive (Python ValueError -> std::invalid_argument).
Extent zoom_by(const Extent& view_extent, double factor,
               std::optional<std::pair<double, double>> center = std::nullopt);

// Extent undo history: record/coalesce/100-cap; previous/next navigate the
// recorded stack (programmatic extents do not re-record).
class ExtentHistory {
public:
    ExtentHistory();  // seeds [(0,0,1,1)] like the Python canvas

    const Extent& current() const { return entries_[index_]; }
    bool can_previous() const { return index_ > 0; }
    bool can_next() const { return index_ + 1 < entries_.size(); }

    // Record a new extent: truncates the redo tail, skips duplicate tails,
    // coalesces onto the tail when asked, caps at 100 entries (drop oldest).
    void record(const Extent& extent, bool coalesce = false);

    // Navigate; returns the new current extent (caller applies it with
    // record=false) or nullopt when navigation is not possible.
    std::optional<Extent> previous();
    std::optional<Extent> next();

    std::size_t size() const { return entries_.size(); }
    std::size_t index() const { return index_; }
    const std::vector<Extent>& entries() const { return entries_; }

private:
    std::vector<Extent> entries_;
    std::size_t index_ = 0;
};

// ---------------------------------------------------------------------------
// Toolbar strip groups (mapping_page __init__ strip composition)
// ---------------------------------------------------------------------------

// The logical grouping literal (verbatim order). Ids not registered with the
// action controller are filtered per group; empty groups drop; registered
// ids absent from every group append as one leftovers group — the strip can
// never drift from the registry (Python inline contract).
const std::vector<std::vector<std::string>>& toolbar_group_vocabulary();

std::vector<std::vector<std::string>> toolbar_strip_groups(
    const std::vector<std::string>& registered_core_ids);

// ---------------------------------------------------------------------------
// Tool-rebind decision (mapping_page._rebind_tool_after_layer_switch)
// ---------------------------------------------------------------------------

// What to do with the active tool after an authoring layer switch.
enum class ToolRebind {
    kKeep,           // unbound tool (pan/zoom/measure) — nothing to rebind
    kRebind,         // layer-bound tool — re-request the same action
    kDeactivatePan,  // kind-bound tool on the wrong kind — fall back to pan
    kNone,           // no active tool / no authoring
};

ToolRebind rebind_tool_after_layer_switch(
    const std::string& active_tool_action, bool has_authoring,
    const std::string& authoring_active_kind);

// ---------------------------------------------------------------------------
// Kind visibility authority chain (mapping_page._kind_visibility)
// ---------------------------------------------------------------------------

// Python truthiness for a Json value (None/False/0/""/empty -> false).
bool json_truthy(const Json& value);

// _kind_visibility(kind): live registry entry -> persisted
// layer_state["composition"] entry -> legacy tree checkbox.
// `has_registry_and_document` mirrors "registry is not None and document
// is not None"; `registry_layer` is the resolved "<doc>:<kind>" layer
// record (null Json when absent); `wanted_layer_id` is "<doc>:<kind>";
// `tree_visible` is the legacy MapLayerTree checkbox fallback.
bool kind_visibility(bool has_registry_and_document,
                     const Json& registry_layer,
                     const Json& composition_entries,
                     const std::string& wanted_layer_id,
                     bool tree_visible);

// ---------------------------------------------------------------------------
// Work-area map core (workarea_map_widget + workarea_map_snapshot boundary)
// ---------------------------------------------------------------------------

// A well candidate for screen-space picking (x/y in SCREEN pixels — the
// widget projects map coordinates through the canvas transform first).
struct WellPickCandidate {
    std::string well_id;
    double screen_x = 0.0;
    double screen_y = 0.0;
};

// Nearest well within `radius_px` of the click (ties keep the larger id
// ordering — Python <= best_dist keeps the LAST nearest; strictly-less
// comparison preserves first-found on ties: Python uses `<=`, so equal
// distances REPLACE — we mirror that exactly).
std::string pick_well_id(const std::pair<double, double>& click_screen,
                         const std::vector<WellPickCandidate>& candidates,
                         double radius_px = kWellPickRadiusPx);

// Well features eligible for picking: only the wells/wells_flagged layers,
// Point geometries with >=2 coordinates carrying a well_id property.
// Returns map-space candidates — the widget projects them to screen.
struct WellFeature {
    std::string well_id;
    double x = 0.0;
    double y = 0.0;
    Json feature;  // verbatim feature dict (selection highlight payload)
};

std::vector<WellFeature> well_candidates_from_snapshot(const Json& snapshot);

// workarea_map_widget._well_feature: the verbatim feature dict for well_id.
Json well_feature_by_id(const Json& snapshot, const std::string& well_id);

// workarea_map_snapshot.workarea_view_extent: padded union of populated
// layer extents (margin 0.15, degenerate floor abs(v)*1e-3 / 1e-6), nullopt
// without content.
std::optional<Extent> workarea_view_extent(const Json& snapshot,
                                           double margin_ratio = 0.15);

// Overlay state for the work-area widget: elements = 比例尺/指北针
// (+ 标题栏 when titled, + 图例 when legend shown), legend_items from the
// frozen vocabulary, selected feature verbatim when present.
Json workarea_overlay_state(const std::string& title, bool show_legend,
                            const Json& selected_feature);

// Zoom-to-well span (select_well zoom=True): 20% of the current half span,
// floor 1.0 — Python _current_half_span * 0.2 contract.
Extent well_zoom_extent(double x, double y, const Extent& view_extent);

// project.domain_signature(project): the cheap change key covering every
// domain field the work-area map renders. Json array with the same shape;
// Json equality == Python tuple equality for the signature cache.
Json domain_signature(const Json& project);

// ---------------------------------------------------------------------------
// Preview payload normalization (viz.mapping_helpers — the producers the
// canvas panel consumes)
// ---------------------------------------------------------------------------

// _close_ring(ring): [[x,y]...] points kept (>=2 entries), first point
// appended when the ring is open. Non-pair entries dropped.
Json close_ring(const Json& ring);

// _normalize_geojson_geometry: Polygon/MultiPolygon rings closed + >=4
// points each; anything else -> null Json.
Json normalize_geojson_geometry(const Json& geometry);

// facies_to_geojson(raw): Feature dict with merged properties
// (name/facies defaults) + normalized polygon geometry; null on reject.
Json facies_to_geojson(const Json& raw);

// well_to_lnglat(raw): {"name","lng","lat"} from coordinates[0,1] |
// lng/lat | x/lon + y/lat; null on reject.
Json well_to_lnglat(const Json& raw);

// preview_payload_from_document: {"features","wells","period"} — the
// canvas-panel payload triple as one Json record.
Json preview_payload_from_document(const Json& document);

// preview_payload_from_features: same shape from live editor records
// (kind "facies" -> geojson, kind "well" -> lnglat).
Json preview_payload_from_features(const Json& features,
                                   const std::string& period_name = "");

// ---------------------------------------------------------------------------
// Suppressed/removed layer ids (mapping_page layer_state handling)
// ---------------------------------------------------------------------------

// state["removed_layer_ids"] -> ordered unique string set (Python
// {str(v) for v in state.get(...) or ()} — set semantics: dedup + sort for
// deterministic staging).
std::set<std::string> removed_layer_ids(const Json& document);

}  // namespace pwb::ui_map
