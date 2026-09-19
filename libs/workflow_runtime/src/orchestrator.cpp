// CONV-33 轮1 契约桩 — orchestrator.hpp 的 fail-loud 占位实现（轮2 替换）。
// 真实部分：游标初值 + STEP_ORDER 常量拷贝（冻结数据契约，常量权威在
// service.hpp）；fail-loud 部分：状态推断与推进语义（依赖 service 轮2 实装）。
#include "pwb/workflow_runtime/orchestrator.hpp"

#include <pwb/workflow_runtime/service.hpp>

#include <stdexcept>
#include <utility>

namespace pwb::workflow_runtime {
namespace {

[[noreturn]] void freeze_stub(const char* symbol) {
    throw std::logic_error(std::string("CONV-33 round-2 implements ") +
                           symbol + " (contract freeze stub)");
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
    freeze_stub("WorkflowOrchestrator::get_step_context");
}

StepTransitionResult WorkflowOrchestrator::next_step() {
    freeze_stub("WorkflowOrchestrator::next_step");
}

}  // namespace pwb::workflow_runtime
