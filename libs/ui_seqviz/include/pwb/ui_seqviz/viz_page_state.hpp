#pragma once

// UI-10 — Qt-free page state for the visualization slice:
//   * viz/adapter.py resolve() — the FULL ref→payload dispatch (well_log
//     reuses the UI-04 ui_workers port; seismic/map/cross_well/
//     engine_preview/prediction are ported here behind injected seams);
//   * viz/facies_hierarchy_service.py — level detection over Json features;
//   * composite_visualization_panel load_payload — host routing, focus tab,
//     status text (engine hosts stay injected in the Qt shell);
//   * visualization_summary_panel — asset entries + counts + signatures;
//   * visualization_trace_panel — update_state/update_ref/export caps;
//   * visualization_page — combo entries, ref signatures, refs_match.
//
// Nothing in this header touches Qt or a rendering engine.

#include <any>
#include <array>
#include <functional>
#include <map>
#include <memory>
#include <optional>
#include <set>
#include <string>
#include <tuple>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/ui_data_core/asset_view.hpp>
#include <pwb/ui_seqviz/geoviz_provider.hpp>
#include <pwb/ui_workers/viz_resolve.hpp>
#include <pwb/ui_workers/worker_common.hpp>

namespace pwb::ui_seqviz {

using ui_data_core::ResourceItem;
using ui_workers::VizRefSlice;

// ---------------------------------------------------------------------------
// viz/models.py VizPayload — the page-level payload (superset of the worker's
// VizPayloadSlice: adds the map/seismic/prepared carriers the hosts read).
// ---------------------------------------------------------------------------

struct UiVizPayload {
    std::string kind;  // well_log|seismic|map|cross_well|engine_preview|
                       // prediction|message
    std::string label;
    std::string message;
    std::string warning;
    std::any well_log;             // engine WellLogData handle (type-erased)
    std::vector<std::any> well_logs;
    std::vector<std::string> well_names;
    std::any seismic_volume;       // engine volume handle (type-erased)
    std::string seismic_path;
    // GeoJSON feature/well lists — [] default; truthiness == non-empty.
    domain::Json map_features = domain::Json::array();
    domain::Json map_wells = domain::Json::array();
    std::string period_name;
    std::any prepared;             // PreparedPreview payload handle
    std::any class_map;
    std::any prob_map;
};

// VizPayloadSlice → UiVizPayload (worker result lifting).
UiVizPayload payload_from_slice(const ui_workers::VizPayloadSlice& slice);

// ---------------------------------------------------------------------------
// Project-side slices (ProjectDocument attribute reads frozen as slices)
// ---------------------------------------------------------------------------

// paleomap_documents entry — the fields the page reads.
struct MapDocSlice {
    std::string id;
    std::string name;
    // load_map_payload_from_document consumes the whole document — the seam
    // receives the raw object reference the host bound (type-erased).
    std::any raw;
};

// prediction_tasks entry.
struct PredictionTaskSlice {
    std::string id;
    std::string name;
    domain::Json input_refs = domain::Json::object();
    std::any raw;  // prediction helper seams consume the raw task
};

struct VizPageProjectSlice {
    std::vector<ResourceItem> resources;
    std::vector<MapDocSlice> map_documents;
    std::vector<PredictionTaskSlice> prediction_tasks;
    std::string project_root;     // meta.project_root ("" when absent)
    std::string comparison_crs;   // coordinate.project_crs
    // The host's live project handle — the page forwards it to host seams
    // (well-log set_project / engine bindings); never dereferenced here.
    std::any raw;
};

// ResourceItem → the worker's ResourceSlice (the adapter conversion,
// shared by page-level consumers like the well-log load worker input).
ui_workers::ResourceSlice resource_slice(const ResourceItem& resource);
std::vector<ui_workers::ResourceSlice> resource_slices(
    const std::vector<ResourceItem>& resources);
// VizAdapter._absolute_path — project_root join when relative.
std::string absolute_ref_path(const std::string& path,
                              const VizPageProjectSlice& project);
// Path.is_file() probe (auto-open + geojson existence checks).
bool ref_path_is_file(const std::string& path);

// ---------------------------------------------------------------------------
// VizAdapter — the non-well_log halves (well_log stays in ui_workers)
// ---------------------------------------------------------------------------

// ref_from_map_document / ref_from_prediction (adapter.py verbatim).
VizRefSlice ref_from_map_document(const MapDocSlice& doc);
VizRefSlice ref_from_prediction(const PredictionTaskSlice& task);

// _find_map_document: id match then name(label) match.
const MapDocSlice* find_map_document(
    const VizRefSlice& ref, const std::vector<MapDocSlice>& docs);
// _find_prediction: id match only.
const PredictionTaskSlice* find_prediction(
    const VizRefSlice& ref, const std::vector<PredictionTaskSlice>& tasks);

// engine_preview_resource — normalized snapshot for async preview workers:
// absolute path + formation_tops→well_stratification type remap.
std::optional<ResourceItem> engine_preview_resource(
    const VizRefSlice& ref, const VizPageProjectSlice& project);

// payload_from_engine_preview_result — worker result → page payload
// (result.engine_preview → prepared; absent → message payload).
UiVizPayload payload_from_engine_preview_result(
    const VizRefSlice& ref, const ui_data_core::PreviewResult& result);

// ---------------------------------------------------------------------------
// resolve() seams — everything Python resolves through project/engine
// bindings stays injected; missing seams surface honest failures.
// ---------------------------------------------------------------------------

struct VizPageResolveSeams {
    // load_well_log_from_path — the same contract the UI-04 worker uses.
    ui_workers::WellLogLoadFn load_fn;

    // load_map_payload_from_document(doc.raw) → (features, wells, period).
    // Missing seam in the doc branch → KernelUnavailable ("解析失败").
    using MapDocLoadFn = std::function<std::tuple<domain::Json, domain::Json,
                                                  std::string>(
        const std::any& doc_raw)>;
    MapDocLoadFn map_doc_load_fn;

    // The ref.path geojson branch: facies-group members + file loads folded
    // into one call (facies_group_members / load_facies_group_payload /
    // load_map_payload_from_geojson_path). Receives the matched resource
    // (or nullptr), the absolute clicked path, and the project slice;
    // returns (features, wells, period, warning). Missing seam →
    // KernelUnavailable. File existence is checked BEFORE this seam runs
    // (the "相图文件不存在或不可读" branch stays in the core).
    using GeoJsonLoadFn = std::function<std::tuple<domain::Json, domain::Json,
                                                   std::string, std::string>(
        const ResourceItem* resource, const std::string& abs_path,
        const VizPageProjectSlice& project)>;
    GeoJsonLoadFn geojson_load_fn;

    // prediction_helpers.well_log_data_from_prediction /
    // seismic_prediction_helpers.seismic_volume_from_prediction — missing
    // seam ⇒ that handle is absent (helper-returned-None parity), never a
    // fabricated object.
    std::function<std::any(const std::any& task_raw)>
        well_log_from_prediction_fn;
    std::function<std::any(const std::any& task_raw)>
        seismic_volume_from_prediction_fn;

    // GeoVizEngine.default() seam for _resolve_engine_preview — nullptr ⇒
    // the "geo-viz-engine 不可用" message branch.
    std::shared_ptr<GeoVizEngineApi> engine;
};

// VizAdapter.resolve — full kind dispatch. WellLogLoadCancelled propagates
// (honest cancellation); other exceptions become "解析失败: <class>".
UiVizPayload resolve_page_payload(
    const VizRefSlice& ref, const VizPageProjectSlice& project,
    const VizPageResolveSeams& seams,
    const std::function<bool()>& is_cancelled = {});

// VizAdapter.from_prediction — soft-fail body wrapped per Python.
UiVizPayload payload_from_prediction(
    const PredictionTaskSlice& task, const VizPageProjectSlice& project,
    const VizPageResolveSeams& seams);

// ---------------------------------------------------------------------------
// visualization_summary_panel — asset entries + counts
// ---------------------------------------------------------------------------

struct VizAssetEntry {
    std::string key;   // res:/map:/pred:/cross_well stable key
    VizRefSlice ref;
    std::string text;  // "<kind-label> · <name>"
};

std::vector<VizAssetEntry> summary_asset_entries(
    const std::vector<ResourceItem>& resources,
    const std::vector<MapDocSlice>& map_documents,
    const std::vector<PredictionTaskSlice>& prediction_tasks);

struct VizSummaryCounts {
    std::string prediction_text;  // "{n} 个"
    std::string map_text;         // "{n} 幅"
    std::string resource_text;    // "{n} 项"
};
VizSummaryCounts summary_counts(std::size_t resources,
                                std::size_t prediction_tasks,
                                std::size_t map_documents);

// ---------------------------------------------------------------------------
// visualization_page — combo entries + signatures + refs_match
// ---------------------------------------------------------------------------

struct VizComboEntry {
    std::string label;  // "<icon><label>" — ▤/◉/✦ prefixes verbatim
    VizRefSlice ref;
};

// resources → (icon, ref) entries then map docs → (◉, ref) entries.
std::vector<VizComboEntry> asset_combo_entries(
    const std::vector<ResourceItem>& resources,
    const std::vector<MapDocSlice>& map_documents);

// (kind, id, label, path) per entry — _asset_combo_signature parity.
using VizRefSignature =
    std::vector<std::tuple<std::string, std::string, std::string, std::string>>;
VizRefSignature combo_signature(const std::vector<VizComboEntry>& entries);

// _refs_match — same logical ref (kind+id+path), tolerating instances.
bool refs_match(const VizRefSlice* a, const VizRefSlice* b);
bool refs_match(const std::optional<VizRefSlice>& a, const VizRefSlice& b);

// ---------------------------------------------------------------------------
// visualization_trace_panel — update_state / update_ref / export caps
// ---------------------------------------------------------------------------

struct VizTraceView {
    // update_state values (global actives).
    std::string task_text = "未选择预测任务";
    std::string map_text = "未选择古地理图";
    // update_ref values.
    std::string source_text = "—";
    std::string label_text = "—";
    std::string kind_text = "—";
    std::string path_text = "—";
};

// update_state: active_prediction_task = last task; active_map_document =
// prefer_id hit else last doc (mapping_helpers parity — "active" is the
// most recent entry unless a preferred id survives the refresh).
VizTraceView trace_state_view(
    const std::vector<PredictionTaskSlice>& prediction_tasks,
    const std::vector<MapDocSlice>& map_documents);
VizTraceView trace_state_view_prefer(
    const std::vector<PredictionTaskSlice>& prediction_tasks,
    const std::vector<MapDocSlice>& map_documents,
    const std::string& prefer_map_id);

// update_ref(ref, payload) — mutates the view in place (the prediction/map
// kind overrides land on task_text/map_text exactly like the Qt panel).
void trace_apply_ref(VizTraceView& view, const VizRefSlice* ref,
                     const UiVizPayload* payload);

struct ExportCaps {
    bool png = false, svg = false, pdf = false;
    std::string png_tip = "当前无可导出视图";
    std::string svg_tip =
        "当前 Tab 不支持 SVG，请切换测井/连井/古地理或改用 PNG";
    std::string pdf_tip =
        "当前 Tab 不支持 PDF，请切换测井/连井/古地理或改用 PNG";
};
ExportCaps export_capability_state(const std::set<std::string>& formats);

// ---------------------------------------------------------------------------
// composite_visualization_panel.load_payload — host routing core
// ---------------------------------------------------------------------------

enum class VizHostKind {
    WellLog,
    WellSection,
    Seismic,
    CrossWell,
    PaleoMap,
    WellTie,
    EnginePreview,
};

// tab_title per host (Python class attrs verbatim — the C++ hosts report
// their own titles; this table feeds the status text + focus lookup).
std::string host_tab_title(VizHostKind kind);

// Ordered list of hosts load_payload would call apply() on for this
// payload (Python's ordered if-chain verbatim).
std::vector<VizHostKind> hosts_to_apply(const UiVizPayload& payload);

// The tab load_payload focuses (kind_tab map; nullopt → no focus change).
std::optional<VizHostKind> focus_tab_for(const UiVizPayload& payload);

// keep_well_session — _clear_all(preserve_well=...) parity.
bool keep_well_session(const UiVizPayload& payload);

// The "已加载/未能加载" status text — applied titles are the host titles
// whose apply() returned true (dedup, first-seen order).
std::string workspace_status_text(const std::string& label,
                                  const std::string& warning,
                                  const std::vector<std::string>& applied);

// _SectionCursorBand geometry — (x, 0, 6, h) or nullopt (empty/unknown
// name hides the band).
struct SectionCursorRect {
    int x = 0, y = 0, w = 6, h = 1;
};
std::optional<SectionCursorRect> section_cursor_geometry(
    const std::string& well_name,
    const std::vector<std::string>& last_well_names, int widget_width,
    int widget_height);

// ---------------------------------------------------------------------------
// facies_hierarchy_service — level detection over Json feature lists
// ---------------------------------------------------------------------------

inline constexpr const char* kAutoLevel = "auto";
inline constexpr std::array<const char*, 3> kFaciesLevels = {
    "facies", "sub_facies", "micro_facies"};

// LEVEL_DISPLAY verbatim.
std::string facies_level_display(const std::string& level);

// _feature_level — properties.level / properties.facies_level normalized.
std::optional<std::string> feature_facies_level(const domain::Json& feature);
std::vector<std::string> hierarchy_levels_present(
    const domain::Json& features);
bool is_hierarchical_feature_set(const domain::Json& features);
// level_choices — [(AUTO_LEVEL, "自动（按比例尺切换）"), ...present levels].
std::vector<std::pair<std::string, std::string>> facies_level_choices(
    const domain::Json& features);

// ---------------------------------------------------------------------------
// misc Python-semantic helpers shared by the shells
// ---------------------------------------------------------------------------

// Path.is_file() on the absolute-resolved path (the auto-probe branch).
bool payload_has_map_geometry(const UiVizPayload& payload);

// The 连井剖面 virtual entry — (ref, text) or nullopt (<2 LAS wells).
std::optional<VizRefSlice> cross_well_virtual_ref(
    const std::vector<ResourceItem>& resources);

}  // namespace pwb::ui_seqviz
