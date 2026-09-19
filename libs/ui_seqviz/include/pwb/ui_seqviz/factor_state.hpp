#pragma once

// UI-10 — factor pages cores.
//
// Ports:
//   * factor_task_panel.py — status badge token (state-language bridge:
//     complete→done, pending→queued), row sub-label, horizon label, the
//     Counter.most_common method seeding rule (a user-picked method is
//     never stomped by refreshes), and the prepared-count summary;
//   * factor_preview_grid.py — completed-only filtering, the header line
//     (horizon + method + grid) and per-card view state (title / range /
//     R² honest fallback / duplicate-well warning);
//   * create_factor_map_dialog.py — combo vocabularies, params dict
//     assembly, the owned worker body (cooperative cancel before/after the
//     engine call, str(exc) failure text) and the success/failure messages.
//     The geological mapping service stays an injected seam.

#include <any>
#include <functional>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/job_runtime/job_contract.hpp>
#include <pwb/ui_seqviz/state_language.hpp>

namespace pwb::ui_seqviz {

// ---------------------------------------------------------------------------
// Factor task records (host-collected slices)
// ---------------------------------------------------------------------------

// FactorMapTask — the fields the factor panels read.
struct FactorTaskRecord {
    std::string id;
    std::string name;
    std::string status;  // pending | running | complete | failed | cancelled
    std::string target_horizon;
    std::string factor_type;
    std::string method;
    domain::Json parameters = domain::Json::object();
    domain::Json quality_metrics = domain::Json::object();
};

// ---------------------------------------------------------------------------
// factor_task_panel.py
// ---------------------------------------------------------------------------

// _task_badge: status → state-language token via the task map override
// ({"complete": "done", "pending": "queued"}.get(status, status)).
StateToken factor_task_badge_token(const std::string& status);

// Row sub label: f"{method} · {parameters['grid'] or '50m'}".
std::string factor_task_sub_label(const FactorTaskRecord& task);

// "层位: <first target_horizon>" / "层位: —".
std::string factor_panel_horizon_text(
    const std::vector<FactorTaskRecord>& tasks);

// Counter(methods).most_common(1) — most common non-empty method, ties
// broken by first-seen order (dict insertion order parity). nullopt when
// no task carries a method.
std::optional<std::string> factor_common_method(
    const std::vector<FactorTaskRecord>& tasks);

// "已制备 N / M 个单因素图".
std::string factor_prepared_summary(
    const std::vector<FactorTaskRecord>& tasks);

// selected_method / _emit_generate fallback: current text or "IDW".
std::string factor_selected_method(const std::string& combo_text);

// ---------------------------------------------------------------------------
// factor_preview_grid.py
// ---------------------------------------------------------------------------

// Completed tasks only (status == "complete").
std::vector<FactorTaskRecord> factor_completed_tasks(
    const std::vector<FactorTaskRecord>& tasks);

// Header text: default "单因素图集" when no completed task; otherwise
// "<horizon> 单因素图集（<method>插值 · 网格 <grid> m）" with method "—"
// fallback and quality_metrics["grid"] or "50×50".
std::string factor_preview_header(
    const std::vector<FactorTaskRecord>& completed);

// Per-card view state (FactorPreviewCard).
struct FactorCardView {
    std::string title;           // factor_type or name
    std::string range_text;      // quality_metrics["range"] str or "—"
    std::string rsquared_text;   // "R² <v>" | "R² 本轮未计算"
    bool rsquared_visible = false;
    std::string dup_text;        // "<n> 口同坐标井已去重（保留先录入值）"
    bool dup_visible = false;
};

FactorCardView factor_card_view(const FactorTaskRecord& task);

// Empty-state label text when no completed tasks exist.
inline constexpr const char* kFactorPreviewEmptyText =
    "暂无已生成的单因素图";

// ---------------------------------------------------------------------------
// create_factor_map_dialog.py
// ---------------------------------------------------------------------------

// Factor combo items (verbatim order).
const std::vector<std::string>& factor_map_factor_items();
// Default horizon candidates appended after the stratigraphy target.
const std::vector<std::string>& factor_map_default_horizons();
// Method combo items: (display label, method data value).
const std::vector<std::pair<std::string, std::string>>&
factor_map_method_items();
// Color ramp combo items (verbatim order).
const std::vector<std::string>& factor_map_ramp_items();

// Horizon combo items: [stratigraphy.target_horizon?] + defaults, deduped
// preserving first occurrence (dict.fromkeys parity).
std::vector<std::string> factor_map_horizon_items(
    const std::string& stratigraphy_target);

// The params dict _on_create_clicked assembles.
struct FactorMapParams {
    std::string factor_name;
    std::string target_horizon;
    std::string method = "kriging";
    int grid_n = 50;
    std::string color_ramp;
    bool include_grid = true;
    bool include_contours = true;
    bool include_wells = true;
    bool include_polygons = false;
};

// The service seam — GeologicalMappingService.create_factor_map. The
// returned pair is (map_document, task); both are host-typed payloads.
struct FactorMapOutcome {
    std::any map_document;
    std::any task;
    std::string map_title;
    long long layer_count = 0;
};

using FactorMapServiceFn =
    std::function<FactorMapOutcome(const FactorMapParams& params)>;

// Worker body parity (_FactorMapWorker.run): cooperative cancel BEFORE and
// AFTER the service call (silent — no finished/failed signals); other
// exceptions → runtime_error carrying str(exc). The JobContext token is the
// isInterruptionRequested surface.
FactorMapOutcome run_factor_map_job(const FactorMapParams& params,
                                    const FactorMapServiceFn& service,
                                    job::JobContext& ctx);

// Success message: f"成功生成地质图件：{title}\n包含 {n} 个 GIS 图层。"
std::string factor_map_success_text(const std::string& title,
                                    long long layer_count);
// Failure message: f"地质编图失败：{msg}".
std::string factor_map_failure_text(const std::string& message);

// JobSpec builder — kind "compute.factor_map". on_done receives
// FactorMapOutcome; on_fail the plain str(exc) text (Python's failed(str)
// — no "Class: " prefix).
job::JobSpec make_factor_map_job_spec(
    FactorMapParams params, FactorMapServiceFn service,
    std::function<void(const FactorMapOutcome&)> on_done = {},
    std::function<void(const std::string&)> on_fail = {},
    std::function<void()> on_cancel = {});

}  // namespace pwb::ui_seqviz
