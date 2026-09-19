#pragma once

// Port of paleo_workbench/mapping/map_render_backend.py snapshot types
// (MapLayerSnapshot / MapRenderSnapshot) + the presentation adapters of
// ui/workstation/tool_surface.py + the evaluate_stage_commands seam of
// ui/workstation/mapping_stage_panel.py (UI-13).
//
// Snapshots are renderer-neutral immutable-by-convention inputs:
// project/editing code produces them; render adapters consume them —
// neither side is an authority for map data. The tool-surface adapter
// holds NO gating rules (Goal V8 M1): it only flattens presentation
// facts into tool_policy::ToolContextSnapshot — the canonical evaluator
// in Pwb::ToolPolicy stays the single enabled/visible/reason authority.
//
// Qt-free.

#include <map>
#include <optional>
#include <set>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/tool_policy/tool_availability.hpp>
#include <pwb/tool_policy/tool_context.hpp>
#include <pwb/ui_composite/geometry.hpp>

namespace pwb::ui_composite {

using pwb::domain::Json;

// ---------------------------------------------------------------------------
// map_render_backend.py snapshots
// ---------------------------------------------------------------------------

// One immutable host-owned render layer. ``features`` carry
// GeoJSON-compatible records ({"id","geometry","properties"}). The
// narrow, explicit form lets render mirrors rebuild only when either
// revision changes while leaving viewport requests free of data
// conversion.
struct MapLayerSnapshot {
    std::string id;
    std::string name;
    std::string layer_type = "vector";
    MapExtent extent{0.0, 0.0, 1.0, 1.0};
    std::string crs;
    int64_t data_revision = 0;
    int64_t style_revision = 0;
    std::vector<Json> features;
    Json style = Json::object();
    bool visible = true;
    double opacity = 1.0;
    // Renderer-only payload token (e.g. an existing native grid layer
    // handle). Never serialized into project state or treated as
    // scientific data — an opaque string keeps the core Qt-free.
    std::string renderer_payload;
    // Catalog provenance: the DataVersion id this layer was produced
    // from, when known.
    std::string source_version_id;
    std::map<std::string, std::string> metadata;
    // Optional 1:N scale-denominator visibility window (min, max);
    // nullopt = renders at every scale.
    std::optional<std::pair<double, double>> scale_range;
};

// Immutable composition input from LayerRegistry/project state.
struct MapRenderSnapshot {
    std::string project_crs;
    std::vector<MapLayerSnapshot> layers;
};

// ---------------------------------------------------------------------------
// tool_surface.py presentation snapshots (adapters only — no rules)
// ---------------------------------------------------------------------------

// QGIS 运行期画布后端三态（native | degraded | unavailable | unknown）。
// None 不允许——未知必须显式 mode="unknown"（fail-closed）。
struct QgisCapabilitySnapshot {
    std::string mode = "unknown";
    std::string reason;

    bool native_ready() const { return mode == "native"; }
};

// 活动图层的呈现相关事实（结论型字段来自域权威）。
struct LayerCapabilitySnapshot {
    std::optional<std::string> layer_id;
    std::optional<std::string> name;
    std::optional<std::string> role;
    std::optional<std::string> role_label;
    std::optional<std::string> kind;
    std::optional<std::string> maturity;
    std::optional<bool> editable;
    std::optional<std::string> block_reason;
    bool frozen = false;
    bool missing = false;
    bool degraded = false;

    // 扁平图层事实（canonical ToolContext 输入）。
    tool_policy::ToolContextSnapshot layer_facts() const;
};

// 图层级菜单呈现事实（V10 M5：树右键菜单消费 canonical evaluator）。
// raw_protected 是菜单**编排**事实（RAW 图层显示「复制为草稿」工作流
// 入口），不是新的门禁。
struct LayerMenuFacts {
    std::optional<tool_policy::ToolAvailability> toggle_editing;
    std::optional<tool_policy::ToolAvailability> repair_geometry;
    bool raw_protected = false;
};

// ---------------------------------------------------------------------------
// UIContextSnapshot adapter (palette / status-bar single evaluation)
// ---------------------------------------------------------------------------

// Duck-typed UIContextSnapshot field bag (V6 palette context). Optional
// members mirror Python getattr-absent → conservative fallbacks; the
// execution-side re-gate uses the controller's full context instead.
struct UiContextSnapshot {
    bool project_open = false;
    std::optional<std::string> mapping_stage;
    std::optional<bool> qgis_bridge_available;
    std::optional<std::string> capability_mode;
    std::optional<bool> native_canvas_available;
    std::vector<std::string> native_capability_flags;
    std::optional<std::string> capability_reason;
    std::optional<bool> write_granted;

    std::optional<std::string> active_layer_id;
    std::optional<std::string> active_layer_kind;
    std::optional<std::string> active_layer_role;
    std::optional<std::string> active_layer_maturity;
    std::optional<bool> active_layer_editable;
    std::optional<bool> active_layer_writable;
    std::optional<std::string> active_layer_block_reason;
    bool active_layer_frozen = false;
    bool active_layer_missing = false;
    bool active_layer_degraded = false;
    bool active_layer_is_raster = false;

    std::optional<bool> editing_active;
    std::optional<bool> editing_dirty;
    std::optional<int> selection_count;
    std::optional<bool> can_undo;
    std::optional<bool> can_redo;
    std::optional<std::string> blocking_task;
    std::optional<bool> split_ready;
    std::optional<bool> merge_ready;
    std::optional<bool> reshape_ready;
    std::optional<int> queryable_layer_count;
};

// UIContextSnapshot → canonical ToolContextSnapshot（palette 用）。缺省
// 输入按保守值处理——palette applicability 只需要「为什么不可用」级
// 精度；执行侧由完整上下文 re-gate 二次判定。
tool_policy::ToolContextSnapshot tool_context_from_ui_snapshot(
    const UiContextSnapshot& snap);

// ---------------------------------------------------------------------------
// mapping_stage_panel.py evaluate_stage_commands (V11 §7)
// ---------------------------------------------------------------------------

// 阶段面板动作可用性：{action_id: (enabled, reason|"")}。与命令面板同
// 一判定规则：阶段动作词表 stage_context_actions → STAGE_ACTION_TOOLS
// 映射动作吃 canonical evaluator 判词；工程未开是更根本的 blocker；
// 阶段白名单判词 = stage_whitelist_reason。保守原则：无工具映射的动
// 作一律放行；未知阶段 → 空表（fail-closed）。
std::map<std::string, std::pair<bool, std::string>>
evaluate_stage_commands(const std::string& stage_value,
                        const UiContextSnapshot& snapshot);

}  // namespace pwb::ui_composite
