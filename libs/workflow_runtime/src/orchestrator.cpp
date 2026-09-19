// CONV-33 轮2 实装 — workflow/orchestrator.py 游标语义（route A4）。
//
// headless 步骤游标：只推进游标、绝不持久化（docstring 自认非权威；
// 权威 = service.home_workflow_steps，audit #847-2）。状态推断全权委托
// service.infer_workflow_step_status（默认 options：无目录 → 空组合 →
// evidence-only，与 Python get_catalog() 为 None 的宿主环境等价）。
//
// 消息模板逐字（orchestrator.hpp 冻结注释 = Python L92/98/107/113）；
// step_payload 形参按 D4 裁决省略（Python 接受但忽略）。
#include "pwb/workflow_runtime/orchestrator.hpp"

#include <pwb/workflow_runtime/service.hpp>

#include <stdexcept>
#include <string>
#include <utility>

namespace pwb::workflow_runtime {
namespace {

// project.resources 真值（缺段 / 非数组 ≙ 空 —— pydantic list 属性 parity）。
bool has_resources(const domain::Json& project) {
    if (!project.is_object()) {
        return false;
    }
    const auto it = project.find("resources");
    return it != project.end() && it->is_array() && !it->empty();
}

}  // namespace

WorkflowOrchestrator::WorkflowOrchestrator(domain::Json project)
    : project_(std::move(project)) {
    steps_.reserve(std::size(kStepOrder));
    for (std::string_view step : kStepOrder) {
        steps_.emplace_back(step);
    }
}

const domain::Json& WorkflowOrchestrator::project() const noexcept {
    return project_;
}

int WorkflowOrchestrator::current_step_index() const noexcept {
    return current_step_index_;
}

WorkflowStepContext WorkflowOrchestrator::get_step_context() const {
    // 越界游标回落首步（Python L58-61：0 <= i < len 不成立取 steps[0]）。
    const std::string step_id =
        (current_step_index_ >= 0 &&
         current_step_index_ < static_cast<int>(steps_.size()))
            ? steps_[static_cast<std::size_t>(current_step_index_)]
            : steps_[0];

    std::string step_name = step_id;
    for (const auto& [id, name] : kOrchestratorStepNames) {
        if (id == step_id) {
            step_name = std::string(name);
            break;
        }
    }

    const std::string status =
        infer_workflow_step_status(project_, step_id);
    // is_valid 陷阱（L65）：warning / running 也算 valid —— 唯 complete
    // 才是完成，但未完成不阻塞推进的门槛只看 evidence-valid。
    const bool is_valid = status == "complete" || status == "running" ||
                         status == "warning";

    std::vector<std::string> prerequisites;
    if (step_id != "data_check" && !has_resources(project_)) {
        prerequisites.push_back("数据资产清单不能为空");
    }

    WorkflowStepContext context;
    context.step_id = step_id;
    context.step_name = std::move(step_name);
    context.index = current_step_index_;
    context.total_steps = static_cast<int>(steps_.size());
    context.is_valid = is_valid;
    context.prerequisites = std::move(prerequisites);
    context.status = status;
    return context;
}

StepTransitionResult WorkflowOrchestrator::next_step() {
    WorkflowStepContext context = get_step_context();
    if (!context.prerequisites.empty()) {
        std::string joined;
        for (const std::string& prereq : context.prerequisites) {
            if (!joined.empty()) {
                joined += ", ";
            }
            joined += prereq;
        }
        StepTransitionResult result;
        result.success = false;
        result.message = "无法进入下一步: " + joined;
        result.step_context = std::move(context);
        return result;
    }
    if (!context.is_valid) {
        StepTransitionResult result;
        result.success = false;
        result.message = "当前步骤 [" + context.step_name +
                         "] 尚未完成，不能进入下一步";
        result.step_context = std::move(context);
        return result;
    }
    if (current_step_index_ < static_cast<int>(steps_.size()) - 1) {
        ++current_step_index_;
        WorkflowStepContext new_context = get_step_context();
        StepTransitionResult result;
        result.success = true;
        result.message = "已成功切换至第 " +
                         std::to_string(new_context.index + 1) + " 步 [" +
                         new_context.step_name + "]";
        result.step_context = std::move(new_context);
        return result;
    }
    StepTransitionResult result;
    result.success = true;
    result.message = "工作流已全部完成";
    result.step_context = std::move(context);
    return result;
}

}  // namespace pwb::workflow_runtime
