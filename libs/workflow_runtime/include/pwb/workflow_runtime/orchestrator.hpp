// CONV-33 — workflow/orchestrator.py 契约冻结（轮1 签名桩；实装 = 轮2）。
//
// WorkflowOrchestrator：headless 工作流步骤游标。docstring 自认非权威：
// 权威步骤状态推断与持久化在 service.home_workflow_steps（单一事实源，
// audit #847-2）。本编排器只推进游标、绝不持久化 — 生产 UI 不得依赖它。
//
// 落点裁决（33-decisions D1）：workflow_runtime 新 TU（非 findings 初判的
// workflow_engine）—— orchestrator 依赖 service.infer_workflow_step_status +
// STEP_ORDER，而 service 依赖本库 freshness；workflow_runtime PUBLIC 链接
// workflow_engine，反向落 engine 会成环。
#pragma once

#include <pwb/domain/json.hpp>

#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace pwb::workflow_runtime {

// orchestrator.STEP_NAMES（L42 逐字）：六步中文名。
inline constexpr std::pair<std::string_view, std::string_view>
    kOrchestratorStepNames[] = {
        {"data_check", "数据校验"},
        {"factor_map", "单因素图编制"},
        {"prediction", "地震相预测"},
        {"map_compile", "古地理图编绘"},
        {"qc", "质量检查"},
        {"export", "成果导出"},
};

// orchestrator.WorkflowStepContext（L17）：当前活动步骤的只读上下文
//（7 字段 parity）。
struct WorkflowStepContext {
    std::string step_id;
    std::string step_name;
    int index = 0;
    int total_steps = 0;
    bool is_valid = false;
    std::vector<std::string> prerequisites;
    std::string status;
};

// orchestrator.StepTransitionResult（L30）：next_step() 的结果载荷。
struct StepTransitionResult {
    bool success = false;
    std::string message;
    WorkflowStepContext step_context;
};

class WorkflowOrchestrator {
public:
    // project = .paleo.json root（Json seam）。空 object ≙ Python
    // ProjectDocument(meta=ProjectMeta(name="Default Project"))：状态推断
    // 只读 resources/证据段，两者语义等价（33-decisions D4）。
    explicit WorkflowOrchestrator(domain::Json project = domain::Json::object());

    [[nodiscard]] const domain::Json& project() const noexcept;
    [[nodiscard]] int current_step_index() const noexcept;

    // 深接口 1/2：当前活动步骤的只读上下文。is_valid 陷阱（L65）：
    // warning / running 也算 valid —— 唯 complete 才是完成，但未完成不
    // 阻塞推进的门槛只看 evidence-valid。
    [[nodiscard]] WorkflowStepContext get_step_context() const;

    // 深接口 2/2：前置满足且当前步骤 evidence-valid 时推进游标。
    // 空工程绝不沿进度条走到"已完成"（audit #847-2）。推进/拒绝 message
    // 逐字（L92/98/107/113）：
    //   拒绝-前置  "无法进入下一步: {', '.join(prereqs)}"
    //   拒绝-无效  "当前步骤 [{step_name}] 尚未完成，不能进入下一步"
    //   推进成功  "已成功切换至第 {index+1} 步 [{step_name}]"
    //   终态      "工作流已全部完成"
    //
    // Python 形参 step_payload 被接受但忽略（L81）→ C++ 省略
    //（33-decisions D4：无语义形参不入契约）。
    StepTransitionResult next_step();

private:
    domain::Json project_;
    int current_step_index_ = 0;
    std::vector<std::string> steps_;  // service.STEP_ORDER 副本
};

}  // namespace pwb::workflow_runtime
