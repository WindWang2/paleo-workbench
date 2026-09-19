// CONV-33 — workflow/qc.py 契约冻结（轮1 签名桩；实装 = 轮2）。
//
// 编图质检面（ISS-QC-01 / ISS-QC-02）。issue 可携带空间定位字段供
// IssueLayer 定位：feature_id / feature_kind / geometry(GeoJSON) /
// centroid [x,y] / ref。
//
// 落点：workflow_runtime 新 TU（findings A1 初判不变）。质心三级兜底链
//（L60-103）：facade centroid（面积质心）→ 自交/退化面回退顶点均值定位点
//（ISS-QC-02：畸形 ≠ 无处可指）→ 畸形/空洞几何按"无定位点"处理
//（fail-open：定位缺失不掩盖问题本身）。
#pragma once

#include <pwb/domain/json.hpp>
#include <pwb/project/version_models.hpp>

#include <array>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace pwb::workflow_runtime {

// BASIC_QC_RULES（L17 顺序即 QualityReport.rules 顺序；引擎键，非中文 chip）。
inline constexpr std::string_view kBasicQcRules[] = {
    "target_horizon_present",
    "facies_polygons_present",
    "facies_geometry_valid",
    "well_overlays_present",
    "contour_lines_present",
    "well_table_qc_clean",
};

// make_issue（L27）的可选空间字段（kwargs parity；extra 平铺进 issue）。
struct QcIssueFields {
    std::optional<std::string> feature_id;
    std::optional<std::string> feature_kind;
    std::optional<domain::Json> geometry;   // GeoJSON dict
    std::optional<std::string> ref;
    domain::Json extra = domain::Json::object();
};

// make_issue：构造一个 QC issue dict。geometry 存在且可定位时附
// centroid（三级兜底链见头注释）。
[[nodiscard]] domain::Json make_issue(std::string_view rule,
                                      std::string_view severity,
                                      std::string_view message,
                                      const QcIssueFields& fields = {});

// spatial_issues（L278）：可上图定位的 issue（有 geometry 或 centroid）。
[[nodiscard]] domain::Json spatial_issues(const domain::Json& issues);

// issue_layer_geojson（L289）：空间定位 QC issue → GeoJSON
// FeatureCollection。properties 携带 rule/severity/message/feature_id/
// feature_kind/ref/map_document_id；顶层 properties 携带 report_id/
// linked_map_document_id/status。
[[nodiscard]] domain::Json issue_layer_geojson(
    const std::optional<project::QualityReport>& report,
    const std::optional<std::string>& map_document_id = std::nullopt);

// catalog qc-DataRun 溯源缝（register_qc_run，H3/H14）。C++ 等价面：
// 报告 JSON 序列化后交缝注册（Python 走临时文件 OUTPUT 版本；临时文件的
// C++ 化 = 缝实现侧职责，报告本体照常返回）。best-effort：注册失败绝不
// 让 QC 本身失败，但必须可见（provenance_registered = false）。
struct QcRunRegistration {
    std::string run_id;
    std::string version_id;
};
class QcProvenanceSink {
public:
    virtual ~QcProvenanceSink() = default;
    // nullopt ≙ Python run_qc is None（注册未发生）。
    [[nodiscard]] virtual std::optional<QcRunRegistration> register_qc_run(
        const std::string& name,
        const std::vector<std::string>& source_task_ids,
        const std::string& domain_task_id, const domain::Json& parameters,
        const domain::Json& report_json) = 0;
};

struct QcRunDeps {
    project::ModelClock clock;  // report id / generated_at / run.updated_at
    // null → 无目录（get_catalog() → None 分支，溯源跳过）。
    QcProvenanceSink* provenance_sink = nullptr;
};

// run_basic_qc（L338）：基础编图 QC，按 linked_map_document_id 稳定 id
// upsert（重跑替换旧报告，dashboard 计数不膨胀）。可选绑定活动编译 run 的
// active_quality_report_id。V8 M11：basic 规则全部评估（每个文档都跑存在
// 性检查），coverage 记录让 pass ≠ skipped 可证：
//   rules = BASIC_QC_RULES；rule_status = {rule: {evaluated: true}}；
//   coverage = {evaluated: 6, skipped: 0}。
// domain_task_id 锚（issue #373 / C15）：linked_prediction_task_id 回退
// document.id —— 逐报告键会让每个历史 QC 自成"最新"域，步骤聚合永远
// 留着被换下图件的过期 QC run。
[[nodiscard]] project::QualityReport run_basic_qc(
    domain::Json& project, const std::string& map_document_id,
    bool bind_active_run = true, const QcRunDeps& deps = {});

// active_quality_reports（L462）：应计入 dashboard QC 指标的报告 ——
// 活动 run 的 active_quality_report_id 指向者；无 run/未绑定 → 每图
// 最新一份（by_map 去重保序）。
[[nodiscard]] std::vector<project::QualityReport> active_quality_reports(
    const domain::Json& project);

// run_map_qc（L475）与 collect_extended_qc_issues /
// extended_rule_coverage 共享的输入（map_qa_rules.hpp 消费同形状）。
struct MapQcInputs {
    // Python map_extent：显式 4 元 [xmin, ymin, xmax, ymax]；缺省 → 读
    // document.view_state.extent；两者皆无 → 越界检查跳过（不猜）。
    std::optional<std::array<double, 4>> map_extent;
    domain::Json fusion_confidence = nullptr;  // {"min": f, "mean": f}
    double confidence_threshold = 0.5;         // map_qa_rules.hpp 常量
    domain::Json export_report = nullptr;
};

// run_map_qc（L475）：扩展 QC（M12）= BASIC + 可定位 M12 规则集；同一
// upsert-by-document 语义，report.rules 精确列出实际跑过的规则，
// BASIC+EXTENDED 两趟 issue 合并且各携带定位字段。
[[nodiscard]] project::QualityReport run_map_qc(
    domain::Json& project, const std::string& map_document_id,
    bool bind_active_run = true, const MapQcInputs& inputs = {},
    const QcRunDeps& deps = {});

}  // namespace pwb::workflow_runtime
