#include <pwb/ui_seqviz/curve_ops_state.hpp>

#include <algorithm>
#include <cstdio>

#include <pwb/ui_data_core/json_util.hpp>

namespace pwb::ui_seqviz {

// ---------------------------------------------------------------------------
// Operation registry (_OPERATION_LABELS verbatim, dict order)
// ---------------------------------------------------------------------------

const std::vector<std::pair<std::string, std::string>>& operation_labels() {
    static const std::vector<std::pair<std::string, std::string>> labels = {
        {"despike", "去尖峰（滚动中值 + 稳健 MAD 阈值）"},
        {"smooth", "平滑（居中滑动平均，NaN 保持）"},
        {"median_filter", "中值滤波"},
        {"normalize", "归一化（z-score / min-max）"},
        {"clip_outliers", "离群值裁剪（界限或百分位）"},
        {"baseline_shift", "基线校正（加常数偏移）"},
        {"unit_conversion", "单位换算（白名单精确因子）"},
        {"depth_shift", "深度平移（校正深度误差）"},
        {"resample", "重采样（全文件，保持曲线对齐）"},
        {"depth_unit_normalize", "深度单位归一（ft → m 等）"},
        {"derive_curve", "派生曲线计算器（受控表达式，无 eval）"},
    };
    return labels;
}

std::vector<std::pair<std::string, std::string>> operation_combo_entries() {
    std::vector<std::pair<std::string, std::string>> entries;
    for (const auto& [op_id, label] : operation_labels()) {
        const auto& registry = well_science::curve_operations();
        const bool registered =
            std::any_of(registry.begin(), registry.end(),
                        [&op_id](const well_science::CurveOperationInfo& info) {
                            return info.name == op_id;
                        });
        if (registered) {
            entries.emplace_back(label, op_id);
        }
    }
    return entries;
}

std::string operation_scope(const std::string& op) {
    for (const auto& info : well_science::curve_operations()) {
        if (info.name == op) {
            return std::string(info.scope);
        }
    }
    return "curve";
}

CurveFieldState curve_field_state(const std::string& op) {
    const std::string scope = operation_scope(op);
    const bool file_scope = scope == "file" || scope == "derive";
    CurveFieldState state;
    state.enabled = !file_scope || op == "derive_curve";
    state.tooltip =
        file_scope
            ? "派生曲线操作此处填输入文件中任一曲线（用于校验）"
            : "曲线助记符（如 GR / RT / DEN）";
    return state;
}

// ---------------------------------------------------------------------------
// Parameter rows (_parameter_rows verbatim)
// ---------------------------------------------------------------------------

namespace {

ParamRowDesc spin(std::string label, std::string name, double value,
                  int decimals, double minimum, double maximum,
                  std::string suffix) {
    ParamRowDesc row;
    row.label = std::move(label);
    row.name = std::move(name);
    row.kind = ParamEditorKind::Spin;
    row.value = value;
    row.decimals = decimals;
    row.minimum = minimum;
    row.maximum = maximum;
    row.suffix = std::move(suffix);
    return row;
}

ParamRowDesc combo(std::string label, std::string name,
                   std::vector<std::pair<std::string, std::string>> choices) {
    ParamRowDesc row;
    row.label = std::move(label);
    row.name = std::move(name);
    row.kind = ParamEditorKind::Combo;
    row.choices = std::move(choices);
    return row;
}

ParamRowDesc line(std::string label, std::string name, std::string text,
                  std::string tooltip = "") {
    ParamRowDesc row;
    row.label = std::move(label);
    row.name = std::move(name);
    row.kind = ParamEditorKind::Line;
    row.text = std::move(text);
    row.suffix = std::move(tooltip);  // reuse suffix slot for the tooltip
    return row;
}

ParamRowDesc hint(std::string text) {
    ParamRowDesc row;
    row.name = "_hint";
    row.kind = ParamEditorKind::Hint;
    row.text = std::move(text);
    return row;
}

}  // namespace

std::vector<ParamRowDesc> parameter_rows(const std::string& op) {
    if (op == "despike") {
        return {spin("阈值 σ", "threshold_sigma", 3.0, 1, 0.1, 20.0, " σ"),
                spin("窗口", "window", 3, 0, 1, 101, " 样点")};
    }
    if (op == "smooth") {
        return {spin("窗口", "window", 5, 0, 1, 4095, " 样点")};
    }
    if (op == "median_filter") {
        return {spin("窗口", "window", 5, 0, 1, 255, " 样点")};
    }
    if (op == "normalize") {
        return {combo("方法", "method",
                      {{"z-score", "zscore"}, {"min-max [0,1]", "minmax"}})};
    }
    if (op == "clip_outliers") {
        return {spin("百分位", "percentile", 1.0, 1, 0.01, 49.9, " %")};
    }
    if (op == "baseline_shift") {
        return {spin("偏移量", "delta", 0.0, 3, -1e6, 1e6, "")};
    }
    if (op == "unit_conversion") {
        return {line("源单位", "from_unit", "g/cm3"),
                line("目标单位", "to_unit", "kg/m3"),
                hint("白名单对：m↔ft, g/cm3↔kg/m3, us/m↔us/ft, mm↔in, "
                     "mv↔v, %↔v/v")};
    }
    if (op == "depth_shift") {
        return {spin("平移 Δm（正=加深）", "delta_m", 0.0, 3, -1e5, 1e5,
                     " m")};
    }
    if (op == "resample") {
        return {spin("新步长", "step", 0.125, 4, 1e-6, 1e4, " m")};
    }
    if (op == "depth_unit_normalize") {
        return {combo("目标单位", "target_unit",
                      {{"m（米）", "m"}, {"ft（英尺）", "ft"}})};
    }
    if (op == "derive_curve") {
        return {
            line("表达式", "expression", "0.5 * (GR + 10)",
                 "受控表达式：曲线名 + 四则运算 + min/max/log/sqrt/where/"
                 "clip 等白名单函数"),
            line("结果曲线名", "result_mnemonic", "DERV"),
            line("结果单位（可空）", "result_unit", ""),
        };
    }
    return {};
}

domain::Json collect_parameters(
    const std::vector<ParamRowDesc>& rows,
    const std::map<std::string, ParamValue>& values) {
    domain::Json params = domain::Json::object();
    for (const auto& row : rows) {
        if (row.name == "_hint" || row.kind == ParamEditorKind::Hint) {
            continue;
        }
        const auto it = values.find(row.name);
        if (it == values.end()) {
            continue;
        }
        std::visit(
            [&params, &row](const auto& value) {
                using T = std::decay_t<decltype(value)>;
                if constexpr (std::is_same_v<T, double>) {
                    params[row.name] = value;
                } else {
                    params[row.name] = ui_data_core::strip_copy(value);
                }
            },
            it->second);
    }
    return params;
}

// ---------------------------------------------------------------------------
// Diagnostics
// ---------------------------------------------------------------------------

std::string missing_interval_dialog_text(
    const std::string& curve,
    const well_science::MissingIntervalReport& report,
    std::size_t depth_size) {
    char buf[128];
    std::string out;
    std::snprintf(buf, sizeof(buf), "曲线 %s（%zu 样点）", curve.c_str(),
                  depth_size);
    out += buf;
    out += "\n";
    std::snprintf(buf, sizeof(buf), "缺失样点: %ld (%.1f%%)",
                  report.missing_samples,
                  report.missing_fraction() * 100.0);
    out += buf;
    out += "\n";
    std::snprintf(buf, sizeof(buf), "最大连续缺口: %.2f（深度轴单位）",
                  report.largest_gap());
    out += buf;
    out += "\n";
    if (!report.intervals.empty()) {
        std::string preview = "缺口区间: ";
        const std::size_t shown =
            std::min<std::size_t>(8, report.intervals.size());
        for (std::size_t i = 0; i < shown; ++i) {
            if (i != 0U) {
                preview += "、";
            }
            char seg[64];
            std::snprintf(seg, sizeof(seg), "%g–%g",
                          report.intervals[i].first,
                          report.intervals[i].second);
            preview += seg;
        }
        if (report.intervals.size() > 8) {
            preview += " …等 " + std::to_string(report.intervals.size()) +
                       " 段";
        }
        out += preview;
    } else {
        out += "缺口区间: 无（首末有效样点之间连续）";
    }
    return out;
}

DiagnosticsOutcome run_diagnostics(const CurveReadFn& read_fn,
                                   const std::string& version_id,
                                   const std::string& curve_text) {
    DiagnosticsOutcome outcome;
    outcome.title = "缺失区间诊断";
    const std::string curve =
        ui_data_core::strip_copy(curve_text).empty()
            ? "GR"
            : ui_data_core::strip_copy(curve_text);
    if (!read_fn) {
        outcome.is_error = true;
        outcome.body = "读取失败: LAS 读取 seam 未配置";
        return outcome;
    }
    const CurveReadResult result = read_fn(version_id, curve);
    if (!result.ok) {
        outcome.is_error = true;
        outcome.body = result.error;
        return outcome;
    }
    const auto report = well_science::missing_interval_report(
        result.depth, result.values);
    outcome.ok = true;
    outcome.body =
        missing_interval_dialog_text(curve, report, result.depth.size());
    return outcome;
}

// ---------------------------------------------------------------------------
// Derived-version result text
// ---------------------------------------------------------------------------

std::string derived_version_success_text(const std::string& operation,
                                         const std::string& input_version_id,
                                         const std::string& output_version_id,
                                         const std::string& run_id) {
    const auto prefix = [](const std::string& id) {
        return id.size() > 18 ? id.substr(0, 18) + "…" : id + "…";
    };
    return "已生成派生版本（" + operation + "）\n输入版本: " +
           prefix(input_version_id) + "\n输出版本: " +
           prefix(output_version_id) + "\nRun: " + prefix(run_id);
}

std::string derived_version_failure_text(const std::string& exc_message) {
    return "操作失败: " + exc_message;
}

}  // namespace pwb::ui_seqviz
