#pragma once

// UI-10 — Qt-free state core for stratigraphy_correlation_page.py.
//
// The page's widget tree, engine views, and canvas stay in the Qt shell;
// this core owns every decision the page makes from data:
//   * backend selection (legacy CrossWell vs WellLogEngine) + engine probe
//   * the keyed-diff well list inputs (id,name signature)
//   * load_section validation + auto-select + stale-completion seq guard
//   * _apply_load_result text assembly (loaded/tops/status)
//   * DTW run guards, band bound, recommendation/done/progress text
//   * tops injection notices (match -> "分层井未在剖面中: ...")
//   * interpretation save/open/restore validation + status text — the
//     correlation lifecycle itself stays an injected seam (C++ has no
//     workflow.correlation_lifecycle port; missing seams refuse honestly).

#include <any>
#include <functional>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <utility>
#include <vector>

#include <pwb/ui_workers/correlation_load.hpp>
#include <pwb/ui_workers/worker_common.hpp>

namespace pwb::ui_seqviz {

// ---------------------------------------------------------------------------
// Backend selection
// ---------------------------------------------------------------------------

enum class CorrelationBackend { Legacy, Engine };

// set_backend: "engine" -> Engine, anything else -> Legacy.
CorrelationBackend normalize_backend(const std::string& name);
// backend_combo index (legacy=0, engine=1).
int backend_combo_index(CorrelationBackend backend);

// _probe_engine outcome: the engine view class is injected (view_factory
// == nullptr models "welllog 绑定未安装").
struct EngineProbeResult {
    bool usable = false;
    std::string error;  // "" | "welllog 绑定未安装" |
                        // "welllog 绑定缺少 submit_multi_well_section"
};
EngineProbeResult probe_engine(
    const std::function<bool()>& has_submit_multi_well_section,
    bool binding_installed);

// ---------------------------------------------------------------------------
// Well list (keyed diff inputs — _sync_well_list signature parity)
// ---------------------------------------------------------------------------

// (resource_id, display_name=name-or-id) per well_log resource, sorted by
// (name or "", id) — list_well_log_resources parity (the worker's sort is
// reused host-side; this helper takes already-sorted input).
struct WellListEntry {
    std::string id;
    std::string name;
};
std::vector<WellListEntry> well_list_entries(
    const std::vector<ui_workers::ResourceSlice>& well_log_resources);

// The signature tuple — unchanged signature == no item work at all.
using WellListSignature = std::vector<std::pair<std::string, std::string>>;
WellListSignature well_list_signature(
    const std::vector<WellListEntry>& entries);

// selected_resource_ids: checked flag per entry -> the checked ids.
std::vector<std::string> selected_resource_ids(
    const std::vector<WellListEntry>& entries,
    const std::vector<bool>& checked);

// _select_bound_wells: bound ids checked; empty bound -> first min(4,n).
std::vector<bool> bound_well_check_states(
    const std::vector<WellListEntry>& entries,
    const std::set<std::string>& bound_ids);

// ---------------------------------------------------------------------------
// update_state / load_section validation
// ---------------------------------------------------------------------------

// update_state texts: "目标层位: X" + section title.
struct CorrelationHeaderView {
    std::string horizon_text;   // "目标层位: —" when none
    std::string section_title;  // "连井地层对比 · X" / "连井地层对比"
};
CorrelationHeaderView correlation_header(
    const std::optional<std::string>& active_target_horizon);

// load_section validation outcome.
enum class LoadSectionPlan {
    NoProject,       // QMessageBox "未绑定工程"
    AlreadyRunning,  // _load_job.is_running -> silent return
    NoResources,     // QMessageBox "工程中没有测井 LAS 资源"
    Load,            // ids non-empty -> start the worker
};
struct LoadSectionDecision {
    LoadSectionPlan plan;
    std::vector<std::string> ids;  // checked ids, else auto first min(4,n)
};
LoadSectionDecision plan_load_section(bool project_bound,
                                      bool load_running,
                                      const std::vector<std::string>& checked_ids,
                                      std::size_t well_list_count);

// ---------------------------------------------------------------------------
// Load completion view state (_on_load_finished / _apply_load_result)
// ---------------------------------------------------------------------------

// Stale-completion guard — _load_seq / _active_load_seq parity.
struct LoadSeqGuard {
    long long seq = 0;
    long long active = 0;
    long long bump() { return ++seq; }
    void arm(long long value) { active = value; }
    // _on_load_finished/_on_load_failed stale check.
    bool stale() const { return active != seq; }
};

// Curve-count seam — the logs are type-erased engine objects; the host
// reports (facies count, lithology count) per log (getattr parity:
// missing attrs -> 0).
using CurveCountFn =
    std::function<std::pair<long long, long long>(const std::any& log)>;

struct CorrelationLoadView {
    // "" when logs empty -> "未能加载任何井曲线" branch (early return).
    std::string empty_status;
    // _apply_load_result texts when logs non-empty.
    std::string loaded_value;   // "已加载: N 口井"
    std::string tops_value;     // "name: 相X/岩性Y · ..." or the no-tops text
    std::string status;         // "已加载 N 口井 (path_msg)[；警告 W 项][；top notices][；Engine: err]"
    std::vector<std::any> logs;
    std::vector<std::string> names;
    std::vector<std::string> loaded_ids;
    std::vector<std::string> warnings;
};

CorrelationLoadView correlation_load_view(
    const ui_workers::CorrelationLoadResult& result,
    const CurveCountFn& count_fn,
    const std::string& path_msg,
    const std::vector<std::string>& top_notices,
    const std::string& engine_error,
    bool backend_is_engine);

// ---------------------------------------------------------------------------
// DTW flow state
// ---------------------------------------------------------------------------

// _run_dtw guards.
enum class DtwRunPlan {
    NoPicks,        // "请先在拾取模式下添加一个参考拾取点"
    NoRefWells,     // "参考拾取点没有关联井"
    CancelRunning,  // second click -> cooperative cancel
    Run,
};

// _on_dtw_recommendation — the dtw_cost >= 999.0 sentinel maps to
// "置信度: 不可用" (never a fake 0.00).
struct DtwConfidence {
    std::string text;     // "置信度: 不可用" | "置信度: X.XX"
    double value = 0.0;
};
DtwConfidence dtw_confidence_from_cost(double dtw_cost, double confidence);
// recommend_fn failure/absent -> the sentinel path.
DtwConfidence dtw_confidence_unavailable();

// _on_dtw_finished status text.
std::string dtw_finished_status(const std::string& formation,
                                std::size_t created,
                                const std::string& conf_text);
// _on_dtw_progress status text.
std::string dtw_progress_status(int done, int total);
// _on_dtw_failed / _on_dtw_cancelled.
std::string dtw_failed_status(const std::string& message);

// _max_loaded_curve_samples — largest curve length across loaded logs via
// the count seam's max-curve-length sibling.
using CurveLengthFn = std::function<long long(const std::any& log)>;
long long max_loaded_curve_samples(const std::vector<std::any>& logs,
                                   const CurveLengthFn& length_fn);

// ---------------------------------------------------------------------------
// Tops injection (_inject_well_tops)
// ---------------------------------------------------------------------------

// match_tops_to_wells + tops_to_intervals are workflow logic the shell
// binds; the core consumes (matched, unmatched) and emits notices +
// the canvas rows to apply.
struct TopsMatchResult {
    // well name -> ordered (top_name, depth) rows for tops_model.add_top +
    // set_formation_data(tops_to_intervals(tops)) — the interval conversion
    // stays host-side (engine model types).
    std::map<std::string, std::vector<std::pair<std::string, double>>> matched;
    std::vector<std::string> unmatched;
};
std::vector<std::string> tops_injection_notices(
    const TopsMatchResult& match);

// ---------------------------------------------------------------------------
// Interpretation version save/open/restore — validation + status text
// ---------------------------------------------------------------------------

// _refresh_interp_status text from project.correlation_interpretations
// (the last ref's current_version_id/name — refs are slices here).
struct CorrelationInterpRef {
    std::string current_version_id;
    std::string name;
};
std::string interp_status_text(bool project_bound,
                               const std::vector<CorrelationInterpRef>& refs);

// save_interpretation_version gate outcomes, in Python order.
enum class InterpSaveGate {
    Ok,
    NoProject,        // "未绑定工程"
    MispairedWells,   // "井名与资源 id 配对不一致，已取消保存。请重新加载连井剖面。"
    UnsavedProject,   // "请先保存工程，再保存解释版本（工件随工程文件归档到 <工程名>.artifacts/）。"
    TopsBuildFailed,  // "{exc}。请为重名井绑定稳定资源 id 后重新加载剖面。"
    EmptySection,     // "请先加载连井剖面并确保有分层顶"
};
struct InterpSaveDecision {
    InterpSaveGate gate = InterpSaveGate::Ok;
    std::string message;  // dialog text for non-Ok gates
};
// names/ids pair count + project_file presence + tops-built flag.
InterpSaveDecision gate_save_interpretation(
    bool project_bound, std::size_t loaded_names, std::size_t loaded_ids,
    bool project_file_present, bool tops_built, bool tops_empty,
    const std::string& tops_error);

// Post-save status text (save_correlation_draft result -> interp_status).
// msg == "noop_unchanged" -> "解释: 无变更（保持 {vid}）" + info dialog text.
// ref null -> "保存失败: {msg}". Otherwise "解释: 已保存 {vid}（{msg}）".
struct InterpSaveOutcome {
    bool saved = false;
    bool noop = false;
    std::string interp_status;
    std::string dialog_text;   // QMessageBox text (empty on failure-only)
    std::string failure_text;  // non-empty -> warning dialog
};
InterpSaveOutcome interp_save_outcome(
    const std::optional<CorrelationInterpRef>& ref,
    const std::string& msg);

// open_saved_interpretation gate + post-open status.
enum class InterpOpenGate { Ok, NoProject, NoSavedRef, RestoreFailed, ApplyFailed };
struct InterpOpenDecision {
    InterpOpenGate gate = InterpOpenGate::Ok;
    std::string dialog_text;
    std::string interp_status;
};
// draft == nullopt -> "工程中尚无已保存的连井对比解释" (information).
// restore error string non-empty -> "解释工件缺失或不可读，请重新保存解释版本:\n{exc}".
// apply_ok false -> "解释: 打开失败（画布恢复出错）".
InterpOpenDecision gate_open_interpretation(
    bool project_bound, bool project_file_present,
    const std::optional<std::string>& parent_version_id,
    const std::string& restore_error, bool draft_returned,
    bool apply_ok);

// restore_saved_interpretation — dirty draft -> confirm prompt text.
std::optional<std::string> restore_confirm_text(bool draft_dirty);

}  // namespace pwb::ui_seqviz
