// CONV-33 — workflow/map_qa_rules.py 契约冻结（轮1 签名桩；实装 = 轮2）。
//
// M12 扩展 QA 规则集：与 qc.BASIC_QC_RULES（文档内容检查）互补的生产级
// 可定位检查 —— CRS 纪律（D5：文档/图层未声明、图层↔文档不一致）、
// renderer/class 一致（分类样式必须覆盖实际出现的要素值，图例永不与数据
// 静默分叉）、几何越界（要素超出声明图幅，feature_id + geometry 定位）、
// 数据健康（空井表 / 因子任务无持久化栅格（stale）/ 解释引用悬空 /
// 外部文件缺失）、融合置信度低于显式阈值、导出诚实（D2：回退渲染器的
// 导出报告浮出为 QA 警告）。
//
// 每个 issue 由 workflow_runtime qc.make_issue 构造并携带
// layer_id/feature_id/ref —— QA 回答"哪里错了、在哪"，不只是分数。
#pragma once

#include <pwb/domain/json.hpp>
#include <pwb/workflow_runtime/catalog_seam.hpp>
#include <pwb/workflow_runtime/qc.hpp>

#include <functional>
#include <string_view>

namespace pwb::workflow_runtime {

// EXTENDED_QC_RULES（L40 顺序即 run_map_qc 报告里 BASIC 之后的顺序）。
inline constexpr std::string_view kExtendedQcRules[] = {
    "crs_undeclared",
    "crs_mismatch",
    "class_renderer_mismatch",
    "out_of_bound_feature",
    "well_table_empty",
    "stale_inputs",
    "broken_external_reference",
    "low_confidence",
    "export_fallback",
    "composition_incomplete",
};

// DEFAULT_CONFIDENCE_THRESHOLD（L53）。
inline constexpr double kDefaultConfidenceThreshold = 0.5;

// collect_extended_qc_issues（L355）：六组收集器合并输出（issue 数组）。
// project/document 均为 Json 视图（recompute_plan 的 project seam 先例：
// 缺键 ≙ 空）。
[[nodiscard]] domain::Json collect_extended_qc_issues(
    const domain::Json& project, const domain::Json& document,
    const MapQcInputs& inputs = {});

// extended_rule_coverage（L376）：V8 M11 —— 哪些扩展规则实际 EVALUATED、
// 哪些 SKIPPED（带原因）。镜像收集器的静默返回条件：输入缺失的规则不
// 发 issue，此前等于隐式 pass；coverage 让 skip 可见。跳过原因逐字：
//   out_of_bound_feature → "未提供图幅范围（map_extent）"
//   low_confidence       → "未提供融合置信度数据"
//   export_fallback      → "尚未执行导出（无导出报告）"
[[nodiscard]] domain::Json extended_rule_coverage(const MapQcInputs& inputs = {});

// composition_qa_issues（L416）：合成页 QA —— 缺 MAIN_MAP/图例/比例尺是
// warning（可能是进行中的页面），定位到要素级。必选组件中文标签逐字：
//   ("main_map", "图面主图") / ("legend", "图例") / ("scale_bar", "比例尺")
// 消息模板："合成页缺少{label}组件"。
[[nodiscard]] domain::Json composition_qa_issues(const domain::Json& composition);

// cartographic_issues（L446）：对 §14 制图规则集（V7）的薄委托 —— 逻辑
// 权威在 mapping.cartographic_qa（规则 id CARTOGRAPHIC_QA_RULES），本模块
// 家族保持 one-import，绝不在此复制（33-decisions D7：C++ 侧不重复声明
// 规则常量，避免双权威）。
struct CartographicQaInputs {
    domain::Json snapshot = nullptr;
    domain::Json capability = nullptr;
    domain::Json stale_summary = nullptr;
    const CatalogRepository* catalog = nullptr;
    double confidence_threshold = 0.5;
};
using CartographicQaDelegate = std::function<domain::Json(
    const domain::Json& project, const CartographicQaInputs& inputs)>;
[[nodiscard]] domain::Json cartographic_issues(
    const domain::Json& project, const CartographicQaInputs& inputs,
    const CartographicQaDelegate& delegate);

}  // namespace pwb::workflow_runtime
