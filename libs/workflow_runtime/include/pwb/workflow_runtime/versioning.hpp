// CONV-33 — workflow/versioning.py 契约冻结（轮1 签名桩；实装 = 轮2）。
//
// VersionSet 定稿工作流（ISS-DOM-04）：图件草稿的专家签核。
//  - build_snapshot：内容指纹 = json.dumps(sort_keys=True,
//    ensure_ascii=False, default=str) 的 sha256 截 16 hex（L31-32）。
//  - finalize_map_version：六道门 + 同层位旧 final 置 superseded +
//    ContourDraft→final + 编译 run→export_ready 联动 + catalog
//    register_finalize_run best-effort（失败绝不让定稿失败，L189-203）。
//  - active_final_snapshot / version_set_summary：读侧。
//
// 落点裁决（33-decisions D1）：workflow_runtime 新 TU —— 编排 project
// 版本模型（version_models.hpp 前置）+ QualityReport + catalog best-effort
// 缝；runtime 已有 catalog_seam 先例，project 库保持纯 DTO/IO 不引 catalog。
#pragma once

#include <pwb/domain/json.hpp>
#include <pwb/project/version_models.hpp>

#include <optional>
#include <string>
#include <string_view>

namespace pwb::workflow_runtime {

// finalize_map_version 六道门中文消息（L126-148 逐字冻结；轮2 直接消费，
// 不得改写 —— 全角标点是契约）。
inline constexpr std::string_view kErrUnknownMapDocumentPrefix =
    "unknown map document: ";  // ValueError(f"unknown map document: {id}")
// H3：演示草稿绝不能被专家定稿为生产成果 —— 最高信任步骤不能洗白启发式
// 几何；无目录编译（lineage 未登记）不是演示草稿，须分开表述。
inline constexpr std::string_view kErrDemoDraftFinalize =
    "演示草稿图不能专家定稿为生产成果；请先通过生产编图路径生成正式图件";
inline constexpr std::string_view kErrUntrackedLineage =
    "该成果的 lineage 未登记（无目录），不能专家定稿；请重新打开目录后通过生产编图生成";
inline constexpr std::string_view kErrNonProduction =
    "非生产成果不能专家定稿为正式图件";
inline constexpr std::string_view kErrQcNotRun = "定稿前需先运行质检";
// f"质检未通过（status={qc.status}），不能定稿" — status 原样内插。
inline constexpr std::string_view kErrQcNotPassedPrefix =
    "质检未通过（status=";
inline constexpr std::string_view kErrQcNotPassedSuffix = "），不能定稿";

struct FinalizeOptions {
    std::string note;
    std::string operator_ = "expert";
    bool require_qc_pass = false;
};

// catalog register_finalize_run 的 best-effort 缝（L190-201）：把签核记为
// 定稿图件已注册版本之上的 version_finalize DataRun。无目录 / lineage
// 不可解析 → 跳过；注册失败绝不让定稿本身失败（吞错语义在实装侧显式
// 化并留日志，不静默）。
class VersionFinalizeSink {
public:
    virtual ~VersionFinalizeSink() = default;
    virtual void register_finalize_run(const project::VersionSnapshot& snapshot,
                                       const std::string& operator_name,
                                       const std::string& note,
                                       const std::string& version_set_id) = 0;
};

struct FinalizeDeps {
    project::ModelClock clock;  // _now_iso / id 盖章
    // null → 无目录（get_catalog() → None，溯源跳过）。
    VersionFinalizeSink* finalize_sink = nullptr;
};

// build_snapshot（L73）：定稿时点快照（计数、qc_status、内容指纹、
// 匹配层位的因子任务 id 集）。qc_status 缺报告时 = "unchecked"。
[[nodiscard]] project::VersionSnapshot build_snapshot(
    const domain::Json& project, const domain::Json& map_doc,
    const std::string& note = "", const std::string& created_by = "",
    const project::ModelClock& clock = {});

// finalize_map_version（L107）：建快照并把 VersionSet 置 final。
// 副作用（就地回写 project Json）：
//   1. 同层位旧 final → superseded（保留历史）；
//   2. 目标层位 VersionSet（无则建 "{horizon or '未指定层位'} 定稿版本集"，
//      关联活动编译 run）追加快照、active_snapshot_id / finalized_by /
//      finalized_at / updated_at 盖章；
//   3. linked ContourDraft → status="final" + updated_at；
//   4. 活动编译 run：active_paleomap_document_id（+active_quality_report_id
//      若有 qc）；status ∈ {draft,running,review_required,blocked} →
//      export_ready；updated_at。
// 门失败 → std::invalid_argument（消息 = 上方冻结常量）。
[[nodiscard]] project::VersionSet finalize_map_version(
    domain::Json& project, const std::string& map_document_id,
    const FinalizeOptions& options = {}, const FinalizeDeps& deps = {});

// active_final_snapshot（L208）：最新 final VersionSet 的活动快照
//（可选层位过滤；active_snapshot_id 缺失时回退末位快照）。
[[nodiscard]] std::optional<project::VersionSnapshot> active_final_snapshot(
    const domain::Json& project, const std::string& target_horizon = "");

// version_set_summary（L229）：{version_set_count, final_count, open_count,
// latest_final_horizon, latest_final_at}。
[[nodiscard]] domain::Json version_set_summary(const domain::Json& project);

}  // namespace pwb::workflow_runtime
