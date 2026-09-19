// CONV-33 轮1 契约桩 — service.hpp 的 fail-loud 占位实现（轮2 替换；
// 定义参数匿名，形参名以头文件声明为准）。
#include "pwb/workflow_runtime/service.hpp"

#include <stdexcept>

namespace pwb::workflow_runtime {
namespace {

[[noreturn]] void freeze_stub(const char* symbol) {
    throw std::logic_error(std::string("CONV-33 round-2 implements ") +
                           symbol + " (contract freeze stub)");
}

}  // namespace

project::CompilationRun create_compilation_run(
    domain::Json&, const std::string&, const std::string&, const std::string&,
    const project::ModelClock&) {
    freeze_stub("create_compilation_run");
}

std::string infer_workflow_step_status(const domain::Json&, std::string_view,
                                       const StepStatusOptions&) {
    freeze_stub("infer_workflow_step_status");
}

std::vector<project::WorkflowStep> home_workflow_steps(
    domain::Json&, const StepStatusOptions&) {
    freeze_stub("home_workflow_steps");
}

RecomputePlan build_affected_products_plan(
    const domain::Json&, const std::optional<std::vector<std::string>>&,
    const CatalogRepository*) {
    freeze_stub("build_affected_products_plan");
}

domain::Json downstream_impact_for_version(const std::string&,
                                           const domain::Json*,
                                           const CatalogRepository*) {
    freeze_stub("downstream_impact_for_version");
}

domain::Json dashboard_state(const domain::Json&) {
    freeze_stub("dashboard_state");
}

}  // namespace pwb::workflow_runtime
