// CONV-33 — workflow/service.py 契约冻结（轮1 签名桩；实装 = 轮2）。
//
// 首页步骤状态推断权威（单一事实源）：STEP_ORDER / REQUIRED_RESOURCE_TYPES
// / create_compilation_run / infer_workflow_step_status（evidence→freshness
// 两层叠加）/ home_workflow_steps（活动 run 就地回写，save/load 保进度）/
// build_affected_products_plan / downstream_impact_for_version /
// dashboard_state。
//
// 落点裁决（33-decisions D1）：workflow_runtime 新 TU —— 组合本库 freshness
// /recompute_plan/qc；workflow_runtime PUBLIC 链接 workflow_engine，落
// engine 会成环（findings 初判修正）。
//
// 状态字符串契约（E-2）：pending/running/complete/warning/failed/stale 是
// 跨模块隐式契约、Python 无 enum —— C++ 同样以 std::string 冻结，不发明
// enum（33-decisions D5）。降级语义：两处 broad except（L136-146/L197-206，
// audit #847-3）→ 轮2 实装为显式 catch + log sink 回退 evidence-only，
// 不得静默吞错。
#pragma once

#include <pwb/domain/json.hpp>
#include <pwb/project/version_models.hpp>
#include <pwb/workflow_runtime/catalog_seam.hpp>
#include <pwb/workflow_runtime/freshness.hpp>
#include <pwb/workflow_runtime/recompute_plan.hpp>

#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace pwb::workflow_runtime {

// service.STEP_ORDER / REQUIRED_RESOURCE_TYPES（L19-20 逐字，顺序即权威）。
inline constexpr std::string_view kStepOrder[] = {
    "data_check", "factor_map", "prediction", "map_compile", "qc", "export",
};
inline constexpr std::string_view kRequiredResourceTypes[] = {
    "well_log", "seismic", "horizon",
};

// _FRESHNESS_STEP_OPS（L23）：catalog run 参与派生 freshness 的步骤映射。
inline constexpr std::pair<std::string_view, std::string_view>
    kFreshnessStepOps[] = {
        {"factor_map", "factor_map"},
        {"prediction", "prediction"},
        {"map_compile", "map_compile"},
        {"qc", "qc"},
        {"export", "export"},
};

// infer_workflow_step_status / home_workflow_steps 的注入选项
//（Python kwargs parity：catalog / freshness_service）。
struct StepStatusOptions {
    // null → 轮2 由 project + catalog 组合 FreshnessService
    //（FreshnessService.for_project 等价面）。
    const FreshnessService* freshness_service = nullptr;
    // catalog 缝（catalog_seam.hpp）；null → 无目录（evidence-only 降级）。
    const CatalogRepository* catalog = nullptr;
    bool apply_freshness = true;
};

// create_compilation_run（L32）：就地回写 project（stratigraphy 的
// target_horizon + systems_tract_scheme 两字段、compilation_runs 追加），
// 返回盖章后的 run DTO（六步 WorkflowStep 全 pending）。
[[nodiscard]] project::CompilationRun create_compilation_run(
    domain::Json& project, const std::string& name,
    const std::string& target_horizon, const std::string& sequence_scheme,
    const project::ModelClock& clock = {});

// infer_workflow_step_status（L149）：evidence 回答"有没有成果"，
// freshness 回答"相对当前选中上游版本是否最新"。combined 状态含
// complete（已完成）与 stale（需更新）。freshness 叠加规则（L122-134）：
// STALE→stale / FAILED→failed / RUNNING→running / MISSING→warning /
// UNKNOWN→warning（H1：provenance 未知不是"已完成"）/ FRESH→保持 evidence。
[[nodiscard]] std::string infer_workflow_step_status(
    const domain::Json& project, std::string_view step_type,
    const StepStatusOptions& options = {});

// home_workflow_steps（L175）：有序步骤（含就地回写 active_run
// .workflow_steps —— 持久化进度；无 run 时返回纯 evidence 临时步骤，
// 进度条绝不全 pending）。保留规则（L236-242）：已持久化的 failed/warning
// 弱覆盖（pending/stale）不降级，fresh evidence 可升回 complete。
[[nodiscard]] std::vector<project::WorkflowStep> home_workflow_steps(
    domain::Json& project, const StepStatusOptions& options = {});

// build_affected_products_plan（L247）：最小重算计划（UI: 更新受影响成果）
// —— FreshnessService + recompute_plan.build_recompute_plan 直通。
[[nodiscard]] RecomputePlan build_affected_products_plan(
    const domain::Json& project,
    const std::optional<std::vector<std::string>>& changed_version_ids =
        std::nullopt,
    const CatalogRepository* catalog = nullptr);

// downstream_impact_for_version（L263）：依赖面板载荷 —— 下游 runs +
// freshness 标签。根扩展镜像 build_recompute_plan：dependents 挂在其消费
// 的 SUPERSEDED 版本上，面板必须含整个 asset + domain-task 兄弟集，否则
// 新 current tip 静默显示"不影响任何成果"（H1）。
// 行形状：{run_id, operation, label(OPERATION_LABELS_ZH), domain_task_id,
// state, state_label(FRESHNESS_UI_LABELS), reasons[]}。
[[nodiscard]] domain::Json downstream_impact_for_version(
    const std::string& version_id, const domain::Json* project = nullptr,
    const CatalogRepository* catalog = nullptr);

// dashboard_state（L312）：首页仪表盘聚合（project_name /
// active_target_horizon / sequence_scheme / workflow_status /
// resource_counts / resource_readiness{required_types, available_counts,
// missing_types, ready} / factor_map_count / prediction_count /
// map_document_count / qc_issue_count / export_count /
// workflow_complete_count / workflow_step_count）。QC 计数走
// active_quality_reports（qc.hpp）。
[[nodiscard]] domain::Json dashboard_state(const domain::Json& project);

}  // namespace pwb::workflow_runtime
