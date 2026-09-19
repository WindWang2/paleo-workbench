#include <pwb/ui_seqviz/correlation_state.hpp>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <utility>

namespace pwb::ui_seqviz {

// ---------------------------------------------------------------------------
// Backend
// ---------------------------------------------------------------------------

CorrelationBackend normalize_backend(const std::string& name) {
    return name == "engine" ? CorrelationBackend::Engine
                            : CorrelationBackend::Legacy;
}

int backend_combo_index(CorrelationBackend backend) {
    return backend == CorrelationBackend::Legacy ? 0 : 1;
}

EngineProbeResult probe_engine(
    const std::function<bool()>& has_submit_multi_well_section,
    bool binding_installed) {
    EngineProbeResult result;
    if (!binding_installed) {
        result.error = "welllog 绑定未安装";
        return result;
    }
    if (!has_submit_multi_well_section ||
        !has_submit_multi_well_section()) {
        result.error = "welllog 绑定缺少 submit_multi_well_section";
        return result;
    }
    result.usable = true;
    return result;
}

// ---------------------------------------------------------------------------
// Well list
// ---------------------------------------------------------------------------

std::vector<WellListEntry> well_list_entries(
    const std::vector<ui_workers::ResourceSlice>& well_log_resources) {
    std::vector<WellListEntry> entries;
    entries.reserve(well_log_resources.size());
    for (const auto& resource : well_log_resources) {
        entries.push_back(
            {resource.id,
             !resource.name.empty() ? resource.name : resource.id});
    }
    return entries;
}

WellListSignature well_list_signature(
    const std::vector<WellListEntry>& entries) {
    WellListSignature signature;
    signature.reserve(entries.size());
    for (const auto& entry : entries) {
        signature.emplace_back(entry.id, entry.name);
    }
    return signature;
}

std::vector<std::string> selected_resource_ids(
    const std::vector<WellListEntry>& entries,
    const std::vector<bool>& checked) {
    std::vector<std::string> ids;
    const std::size_t n = std::min(entries.size(), checked.size());
    for (std::size_t i = 0; i < n; ++i) {
        if (checked[i] && !entries[i].id.empty()) {
            ids.push_back(entries[i].id);
        }
    }
    return ids;
}

std::vector<bool> bound_well_check_states(
    const std::vector<WellListEntry>& entries,
    const std::set<std::string>& bound_ids) {
    std::vector<bool> states(entries.size(), false);
    if (bound_ids.empty()) {
        // Fall back: check first few wells (min(4, count)).
        for (std::size_t i = 0; i < std::min<std::size_t>(4, entries.size());
             ++i) {
            states[i] = true;
        }
        return states;
    }
    for (std::size_t i = 0; i < entries.size(); ++i) {
        states[i] = bound_ids.count(entries[i].id) != 0U;
    }
    return states;
}

// ---------------------------------------------------------------------------
// Header / load plan
// ---------------------------------------------------------------------------

CorrelationHeaderView correlation_header(
    const std::optional<std::string>& active_target_horizon) {
    CorrelationHeaderView view;
    const std::string horizon =
        active_target_horizon.has_value() && !active_target_horizon->empty()
            ? *active_target_horizon
            : "—";
    view.horizon_text = "目标层位: " + horizon;
    view.section_title = horizon != "—"
                             ? "连井地层对比 · " + horizon
                             : "连井地层对比";
    return view;
}

LoadSectionDecision plan_load_section(bool project_bound,
                                      bool load_running,
                                      const std::vector<std::string>& checked_ids,
                                      std::size_t well_list_count) {
    LoadSectionDecision decision;
    if (!project_bound) {
        decision.plan = LoadSectionPlan::NoProject;
        return decision;
    }
    if (load_running) {
        decision.plan = LoadSectionPlan::AlreadyRunning;
        return decision;
    }
    decision.ids = checked_ids;
    if (decision.ids.empty()) {
        // Auto-select up to 4 wells if none checked — the caller applies
        // the check states, then re-reads.
        decision.ids.clear();
        const std::size_t take = std::min<std::size_t>(4, well_list_count);
        if (take == 0) {
            decision.plan = LoadSectionPlan::NoResources;
            return decision;
        }
    }
    decision.plan = LoadSectionPlan::Load;
    return decision;
}

// ---------------------------------------------------------------------------
// Load completion view
// ---------------------------------------------------------------------------

CorrelationLoadView correlation_load_view(
    const ui_workers::CorrelationLoadResult& result,
    const CurveCountFn& count_fn, const std::string& path_msg,
    const std::vector<std::string>& top_notices,
    const std::string& engine_error, bool backend_is_engine) {
    CorrelationLoadView view;
    view.logs = result.logs;
    view.names = result.names;
    view.loaded_ids = result.loaded_ids;
    view.warnings = result.warnings;
    if (result.logs.empty()) {
        std::string detail;
        for (std::size_t i = 0;
             i < std::min<std::size_t>(5, result.warnings.size()); ++i) {
            if (!detail.empty()) {
                detail += "；";
            }
            detail += result.warnings[i];
        }
        view.empty_status = "未能加载任何井曲线" +
                            (detail.empty() ? std::string{}
                                            : "：" + detail);
        return view;
    }
    view.loaded_value =
        "已加载: " + std::to_string(result.names.size()) + " 口井";
    std::vector<std::string> tops_bits;
    const std::size_t n =
        std::min(result.logs.size(), result.names.size());
    for (std::size_t i = 0; i < n; ++i) {
        const auto [n_facies, n_litho] =
            count_fn ? count_fn(result.logs[i])
                     : std::pair<long long, long long>{0, 0};
        if (n_facies > 0 || n_litho > 0) {
            tops_bits.push_back(result.names[i] + ": 相" +
                                std::to_string(n_facies) + "/岩性" +
                                std::to_string(n_litho));
        }
    }
    view.tops_value =
        tops_bits.empty()
            ? "无预测相/岩性 tops（可先运行测井预测）"
            : [&] {
                  std::string joined;
                  for (const auto& bit : tops_bits) {
                      if (!joined.empty()) {
                          joined += " · ";
                      }
                      joined += bit;
                  }
                  return joined;
              }();
    std::string msg = "已加载 " + std::to_string(result.names.size()) +
                      " 口井 (" + path_msg + ")";
    if (!result.warnings.empty()) {
        msg += "；警告 " + std::to_string(result.warnings.size()) + " 项";
    }
    if (!top_notices.empty()) {
        msg += "；";
        for (std::size_t i = 0;
             i < std::min<std::size_t>(2, top_notices.size()); ++i) {
            if (i != 0U) {
                msg += "；";
            }
            msg += top_notices[i];
        }
    }
    if (!engine_error.empty() && backend_is_engine) {
        msg += "；Engine: " + engine_error;
    }
    view.status = std::move(msg);
    return view;
}

// ---------------------------------------------------------------------------
// DTW flow
// ---------------------------------------------------------------------------

DtwConfidence dtw_confidence_from_cost(double dtw_cost, double confidence) {
    if (dtw_cost >= 999.0) {
        return dtw_confidence_unavailable();
    }
    DtwConfidence out;
    char buf[64];
    std::snprintf(buf, sizeof(buf), "置信度: %.2f", confidence);
    out.text = buf;
    out.value = confidence;
    return out;
}

DtwConfidence dtw_confidence_unavailable() {
    return {"置信度: 不可用", 0.0};
}

std::string dtw_finished_status(const std::string& formation,
                                std::size_t created,
                                const std::string& conf_text) {
    return "DTW 已为层位 " + formation + " 生成 " +
           std::to_string(created) + " 个建议拾取 (" + conf_text +
           ")（点击接受 / 右键拒绝）";
}

std::string dtw_progress_status(int done, int total) {
    if (total <= 0) {
        return {};
    }
    return "DTW 传播中… " + std::to_string(done) + "/" +
           std::to_string(total) + " 井（再次点击可取消）";
}

std::string dtw_failed_status(const std::string& message) {
    return "DTW 传播失败: " + message;
}

long long max_loaded_curve_samples(const std::vector<std::any>& logs,
                                   const CurveLengthFn& length_fn) {
    long long n = 0;
    for (const auto& log : logs) {
        if (length_fn) {
            n = std::max(n, length_fn(log));
        }
    }
    return n;
}

// ---------------------------------------------------------------------------
// Tops injection
// ---------------------------------------------------------------------------

std::vector<std::string> tops_injection_notices(
    const TopsMatchResult& match) {
    std::vector<std::string> notices;
    if (!match.unmatched.empty()) {
        std::string joined = "分层井未在剖面中: ";
        bool first = true;
        for (const auto& name : match.unmatched) {
            if (!first) {
                joined += ", ";
            }
            joined += name;
            first = false;
        }
        notices.push_back(std::move(joined));
    }
    return notices;
}

// ---------------------------------------------------------------------------
// Interpretation save/open
// ---------------------------------------------------------------------------

std::string interp_status_text(
    bool project_bound, const std::vector<CorrelationInterpRef>& refs) {
    if (!project_bound) {
        return "解释: 未绑定工程";
    }
    if (refs.empty()) {
        return "解释: 未保存";
    }
    const CorrelationInterpRef& ref = refs.back();
    return "解释: 当前 " +
           (ref.current_version_id.empty() ? "—" : ref.current_version_id) +
           " / " + ref.name;
}

InterpSaveDecision gate_save_interpretation(
    bool project_bound, std::size_t loaded_names, std::size_t loaded_ids,
    bool project_file_present, bool tops_built, bool tops_empty,
    const std::string& tops_error) {
    InterpSaveDecision decision;
    if (!project_bound) {
        decision.gate = InterpSaveGate::NoProject;
        decision.message = "未绑定工程";
        return decision;
    }
    if (loaded_names != loaded_ids) {
        decision.gate = InterpSaveGate::MispairedWells;
        decision.message =
            "井名与资源 id 配对不一致，已取消保存。请重新加载连井剖面。";
        return decision;
    }
    if (!project_file_present) {
        decision.gate = InterpSaveGate::UnsavedProject;
        decision.message =
            "请先保存工程，再保存解释版本（工件随工程文件归档到 "
            "<工程名>.artifacts/）。";
        return decision;
    }
    if (!tops_built) {
        decision.gate = InterpSaveGate::TopsBuildFailed;
        decision.message =
            tops_error +
            "。请为重名井绑定稳定资源 id 后重新加载剖面。";
        return decision;
    }
    if (tops_empty && loaded_ids == 0) {
        decision.gate = InterpSaveGate::EmptySection;
        decision.message = "请先加载连井剖面并确保有分层顶";
        return decision;
    }
    decision.gate = InterpSaveGate::Ok;
    return decision;
}

InterpSaveOutcome interp_save_outcome(
    const std::optional<CorrelationInterpRef>& ref,
    const std::string& msg) {
    InterpSaveOutcome outcome;
    if (msg == "noop_unchanged") {
        outcome.noop = true;
        outcome.interp_status =
            "解释: 无变更（保持 " +
            (ref.has_value() ? ref->current_version_id : "") + "）";
        outcome.dialog_text = "科学内容未变化，未创建新版本";
        return outcome;
    }
    if (!ref.has_value()) {
        outcome.failure_text = "保存失败: " + msg;
        return outcome;
    }
    outcome.saved = true;
    outcome.interp_status =
        "解释: 已保存 " + ref->current_version_id + "（" + msg + "）";
    outcome.dialog_text =
        "已保存连井对比版本\n" + ref->current_version_id;
    return outcome;
}

InterpOpenDecision gate_open_interpretation(
    bool project_bound, bool project_file_present,
    const std::optional<std::string>& parent_version_id,
    const std::string& restore_error, bool draft_returned, bool apply_ok) {
    InterpOpenDecision decision;
    if (!project_bound) {
        decision.gate = InterpOpenGate::NoProject;
        decision.dialog_text = "未绑定工程";
        return decision;
    }
    if (!project_file_present) {
        decision.gate = InterpOpenGate::NoSavedRef;
        decision.dialog_text = "工程中尚无已保存的连井对比解释";
        return decision;
    }
    if (!restore_error.empty()) {
        decision.gate = InterpOpenGate::RestoreFailed;
        decision.dialog_text =
            "解释工件缺失或不可读，请重新保存解释版本:\n" + restore_error;
        return decision;
    }
    if (!draft_returned) {
        decision.gate = InterpOpenGate::NoSavedRef;
        decision.dialog_text = "工程中尚无已保存的连井对比解释";
        return decision;
    }
    if (!apply_ok) {
        decision.gate = InterpOpenGate::ApplyFailed;
        decision.interp_status = "解释: 打开失败（画布恢复出错）";
        return decision;
    }
    decision.gate = InterpOpenGate::Ok;
    decision.interp_status =
        "解释: 已打开工作副本（父版本 " +
        (parent_version_id.has_value() && !parent_version_id->empty()
             ? *parent_version_id
             : "—") +
        "）";
    return decision;
}

std::optional<std::string> restore_confirm_text(bool draft_dirty) {
    if (!draft_dirty) {
        return std::nullopt;
    }
    return std::string("将丢弃未保存的分层编辑，确认？");
}

}  // namespace pwb::ui_seqviz
