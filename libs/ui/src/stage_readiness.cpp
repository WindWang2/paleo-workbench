#include <pwb/ui/stage_readiness.hpp>

#include <algorithm>
#include <array>
#include <map>

namespace pwb::ui {
namespace {

const char* status_value(ReadinessItemStatus status) {
    switch (status) {
        case ReadinessItemStatus::Ok: return "ok";
        case ReadinessItemStatus::Warning: return "warning";
        case ReadinessItemStatus::Error: return "error";
        case ReadinessItemStatus::Info: return "info";
    }
    return "info";
}

ReadinessItem ok(const std::string& id, const std::string& title,
                 const std::string& detail = "",
                 const std::string& target = "") {
    return {id, ReadinessItemStatus::Ok, title, detail, target};
}
ReadinessItem warn(const std::string& id, const std::string& title,
                   const std::string& detail = "",
                   const std::string& target = "") {
    return {id, ReadinessItemStatus::Warning, title, detail, target};
}
ReadinessItem err(const std::string& id, const std::string& title,
                  const std::string& detail = "",
                  const std::string& target = "") {
    return {id, ReadinessItemStatus::Error, title, detail, target};
}
ReadinessItem info(const std::string& id, const std::string& title,
                   const std::string& detail = "",
                   const std::string& target = "") {
    return {id, ReadinessItemStatus::Info, title, detail, target};
}

}  // namespace

const char* readiness_item_status_value(ReadinessItemStatus status) {
    return status_value(status);
}

int ReadinessItem::sort_weight() const {
    // readiness.py sort_weight map.
    switch (status) {
        case ReadinessItemStatus::Error: return 0;
        case ReadinessItemStatus::Warning: return 1;
        case ReadinessItemStatus::Info: return 2;
        case ReadinessItemStatus::Ok: return 3;
    }
    return 3;
}

StageReadinessStatus StageReadiness::status() const {
    const bool has_error = std::any_of(
        items.begin(), items.end(), [](const ReadinessItem& item) {
            return item.status == ReadinessItemStatus::Error;
        });
    const bool has_warning = std::any_of(
        items.begin(), items.end(), [](const ReadinessItem& item) {
            return item.status == ReadinessItemStatus::Warning;
        });
    if (has_error) return StageReadinessStatus::NotReady;
    if (has_warning) return StageReadinessStatus::ReadyWithWarnings;
    return StageReadinessStatus::Ready;
}

const char* StageReadiness::label() const {
    switch (status()) {
        case StageReadinessStatus::Ready: return "就绪";
        case StageReadinessStatus::ReadyWithWarnings: return "就绪（有提醒）";
        case StageReadinessStatus::NotReady: return "未就绪";
    }
    return "未就绪";
}

std::vector<ReadinessItem> StageReadiness::warnings() const {
    std::vector<ReadinessItem> out;
    for (const ReadinessItem& item : items) {
        if (item.status == ReadinessItemStatus::Warning
            || item.status == ReadinessItemStatus::Error) {
            out.push_back(item);
        }
    }
    return out;
}

std::vector<ReadinessItem> StageReadiness::sorted_items() const {
    // Python sorted() is stable; std::stable_sort preserves the evaluation
    // order within equal weights (both use the same weight ladder).
    std::vector<ReadinessItem> out = items;
    std::stable_sort(out.begin(), out.end(),
                     [](const ReadinessItem& a, const ReadinessItem& b) {
                         return a.sort_weight() < b.sort_weight();
                     });
    return out;
}

// -------------------------------------------------------------- checks ----
// Wording mirrors readiness.py verbatim (the strings are part of the
// acceptance surface the Python panel shows).

namespace {

ReadinessItem check_target_horizon(const ReadinessInputs& in) {
    const std::string horizon = [&] {
        std::string s = in.target_horizon;
        // str.strip() parity.
        const auto first = s.find_first_not_of(" \t\r\n");
        if (first == std::string::npos) return std::string();
        const auto last = s.find_last_not_of(" \t\r\n");
        return s.substr(first, last - first + 1);
    }();
    if (!horizon.empty()) {
        return ok("target_horizon", "编图层位已设定", horizon);
    }
    return err("target_horizon", "未设定编图层位",
               "相图按层位进行——请先在阶段条选择或输入层位");
}

ReadinessItem check_initial_facies_present(const ReadinessInputs& in) {
    if (in.facies_polygon_count > 0) {
        return ok("initial_facies_present", "初始相图存在",
                  std::to_string(in.facies_polygon_count) + " 个相面多边形");
    }
    if (in.workarea_boundary_vertices >= 3) {
        return ok("initial_facies_present", "初始相图（工区默认空白相）",
                  "未指定初始相图——按默认规则以工区范围为空白相，加载后可校正");
    }
    return err("initial_facies_present", "初始相图缺失",
               "未找到初始沉积相图——导入或生成初始相图后才能进行校正");
}

ReadinessItem check_initial_facies_crs(const ReadinessInputs& in) {
    if (!in.project_crs.empty()) {
        return ok("initial_facies_crs", "相图 CRS 有效", in.project_crs);
    }
    return err("initial_facies_crs", "工程 CRS 未设置",
               "工程未配置坐标系，叠加与编辑无法进行");
}

ReadinessItem check_initial_facies_geometry(const ReadinessInputs& in) {
    if (!in.facies_polygons_loaded) {
        return info("initial_facies_geometry", "相图几何检查待相图加载");
    }
    if (in.facies_polygon_geometry_issues == 0) {
        return ok("initial_facies_geometry", "相图几何有效");
    }
    return warn("initial_facies_geometry",
                std::to_string(in.facies_polygon_geometry_issues)
                    + " 个相面几何异常",
                "空/缺失几何的相面将被跳过", "phase1.initial_facies");
}

ReadinessItem check_well_prediction_linked(const ReadinessInputs& in) {
    if (in.real_prediction_tasks > 0) {
        return ok("well_prediction_linked", "测井预测已关联",
                  std::to_string(in.real_prediction_tasks) + " 个预测任务");
    }
    if (in.mock_prediction_tasks > 0) {
        return ok("well_prediction_linked", "测井预测已关联",
                  std::to_string(in.mock_prediction_tasks)
                      + " 个 mock 演示任务（非科学预测，仅供流程演示）");
    }
    return warn("well_prediction_linked", "测井预测未关联",
                "无真实测井预测任务——校正只能基于初始相图人工解释");
}

ReadinessItem check_seismic_prediction_confidence(const ReadinessInputs& in) {
    if (!in.any_probability_summary) {
        return warn("seismic_prediction_confidence", "地震预测缺失",
                    "未关联地震预测结果");
    }
    const bool all_mock = in.real_prediction_tasks == 0;
    if (all_mock) {
        return ok("seismic_prediction_confidence", "地震预测已关联",
                  std::to_string(in.mock_prediction_tasks)
                      + " 个 mock 演示任务（概率未标定）");
    }
    if (in.low_confidence_regions > 0) {
        return warn("seismic_prediction_confidence",
                    "地震预测存在 "
                        + std::to_string(in.low_confidence_regions)
                        + " 个低置信度区域",
                    "建议优先人工复核低置信度区域", "phase1.seismic_predictions");
    }
    return ok("seismic_prediction_confidence", "地震预测置信度良好");
}

ReadinessItem check_interpretation_saved(const ReadinessInputs& in) {
    if (in.facies_draft_layers > 0) {
        return ok("interpretation_saved", "解释草稿已保存",
                  std::to_string(in.facies_draft_layers)
                      + " 个解释图层含已提交要素");
    }
    return info("interpretation_saved", "尚无解释草稿",
                "从原始相图创建可编辑草稿后开始校正（RAW 保持不可变）",
                "phase1.interpretation");
}

ReadinessItem check_constraints_present(const ReadinessInputs& in) {
    if (in.constraint_lines > 0) {
        return ok("constraints_present", "地质约束存在",
                  std::to_string(in.constraint_lines) + " 条约束线",
                  "phase2.constraints");
    }
    return warn("constraints_present", "尚无地质约束",
                "物源/展布/岸线/断层等约束为空——单因素建模将缺少地质控制",
                "phase2.constraints");
}

ReadinessItem check_factors_complete(const ReadinessInputs& in) {
    if (in.factor_tasks_total == 0) {
        return warn("factors_complete", "无单因素任务", "尚未配置任何单因素图任务",
                    "phase2.factors");
    }
    const int pending = in.factor_tasks_total - in.factor_tasks_complete;
    if (pending > 0) {
        return warn("factors_complete",
                    std::to_string(in.factor_tasks_complete) + "/"
                        + std::to_string(in.factor_tasks_total)
                        + " 个单因素完成",
                    std::to_string(pending) + " 个任务未完成", "phase2.factors");
    }
    return ok("factors_complete",
              std::to_string(in.factor_tasks_complete) + " 个单因素完成", "",
              "phase2.factors");
}

ReadinessItem check_factor_staleness(const ReadinessInputs& in) {
    if (in.stale_artifacts > 0) {
        return warn("factor_staleness",
                    std::to_string(in.stale_artifacts) + " 项成果已过期",
                    "上游输入更新——建议重新计算（旧结果保留）", "phase2.factors");
    }
    return ok("factor_staleness", "单因素均为最新");
}

ReadinessItem check_evidence_available(const ReadinessInputs& in) {
    const int evidence = in.factor_tasks_complete + in.constraint_lines;
    if (evidence > 0) {
        return ok("evidence_available", "证据可用",
                  std::to_string(evidence) + " 项约束/单因素证据");
    }
    return err("evidence_available", "无可用证据",
               "综合编图至少需要一项上阶段成果作为证据");
}

ReadinessItem check_integrated_draft(const ReadinessInputs& in) {
    if (in.integrated_draft_layers > 0) {
        return ok("integrated_draft", "综合解释草稿存在",
                  std::to_string(in.integrated_draft_layers) + " 个综合解释图层",
                  "phase3.integrated");
    }
    return info("integrated_draft", "尚无综合解释草稿",
                "选择证据版本后创建综合解释草稿", "phase3.integrated");
}

ReadinessItem check_qa_geometry_errors(const ReadinessInputs& in) {
    if (in.qa_geometry_issues > 0) {
        return warn("qa_geometry_errors",
                    "QA 存在 " + std::to_string(in.qa_geometry_issues)
                        + " 个几何/拓扑问题",
                    "成图前建议修复", "phase3.qc");
    }
    return ok("qa_geometry_errors", "QA 无几何错误");
}

using CheckFn = ReadinessItem (*)(const ReadinessInputs&);

const std::map<std::string, CheckFn>& check_implementations() {
    static const std::map<std::string, CheckFn> table = {
        {"target_horizon", &check_target_horizon},
        {"initial_facies_present", &check_initial_facies_present},
        {"initial_facies_crs", &check_initial_facies_crs},
        {"initial_facies_geometry", &check_initial_facies_geometry},
        {"well_prediction_linked", &check_well_prediction_linked},
        {"seismic_prediction_confidence",
         &check_seismic_prediction_confidence},
        {"interpretation_saved", &check_interpretation_saved},
        {"phase1_interpretation", &check_interpretation_saved},
        {"constraints_present", &check_constraints_present},
        {"factors_complete", &check_factors_complete},
        {"factor_staleness", &check_factor_staleness},
        {"evidence_available", &check_evidence_available},
        {"evidence_staleness", &check_factor_staleness},
        {"integrated_draft", &check_integrated_draft},
        {"qa_geometry_errors", &check_qa_geometry_errors},
    };
    return table;
}

// stage_profiles.py readiness_checks tuples (order preserved).
const std::map<pwb::tool_policy::MappingStage,
               std::vector<std::string>>& stage_check_lists() {
    static const std::map<pwb::tool_policy::MappingStage,
                          std::vector<std::string>> table = {
        {pwb::tool_policy::MappingStage::FaciesCalibration,
         {"target_horizon", "initial_facies_present", "initial_facies_crs",
          "initial_facies_geometry", "well_prediction_linked",
          "seismic_prediction_confidence", "interpretation_saved"}},
        {pwb::tool_policy::MappingStage::ConstraintFactor,
         {"target_horizon", "phase1_interpretation", "constraints_present",
          "factors_complete", "factor_staleness"}},
        {pwb::tool_policy::MappingStage::IntegratedCompilation,
         {"target_horizon", "evidence_available", "evidence_staleness",
          "integrated_draft", "qa_geometry_errors"}},
    };
    return table;
}

}  // namespace

const std::vector<std::string>& stage_readiness_checks(
    pwb::tool_policy::MappingStage stage) {
    const auto& table = stage_check_lists();
    const auto it = table.find(stage);
    if (it == table.end()) {
        static const std::vector<std::string> empty;
        return empty;
    }
    return it->second;
}

ReadinessItem evaluate_readiness_check(const std::string& check_id,
                                       const ReadinessInputs& inputs) {
    const auto& table = check_implementations();
    const auto it = table.find(check_id);
    if (it == table.end() || it->second == nullptr) {
        // Python: unknown ids are skipped by the evaluator; callers get a
        // neutral placeholder only through this direct entry point.
        return info(check_id, "检查未实现");
    }
    return it->second(inputs);
}

StageReadiness evaluate_stage_readiness(
    pwb::tool_policy::MappingStage stage, const ReadinessInputs& inputs) {
    StageReadiness readiness;
    readiness.stage = stage;
    for (const std::string& check_id : stage_readiness_checks(stage)) {
        const auto& table = check_implementations();
        const auto it = table.find(check_id);
        if (it == table.end() || it->second == nullptr) continue;
        readiness.items.push_back(it->second(inputs));
    }
    return readiness;
}

}  // namespace pwb::ui
