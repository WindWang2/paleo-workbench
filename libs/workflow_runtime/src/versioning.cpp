// CONV-33 轮1 契约桩 — versioning.hpp 的 fail-loud 占位实现（轮2 替换；
// 定义参数匿名，形参名以头文件声明为准）。
#include "pwb/workflow_runtime/versioning.hpp"

#include <stdexcept>

namespace pwb::workflow_runtime {
namespace {

[[noreturn]] void freeze_stub(const char* symbol) {
    throw std::logic_error(std::string("CONV-33 round-2 implements ") +
                           symbol + " (contract freeze stub)");
}

}  // namespace

project::VersionSnapshot build_snapshot(const domain::Json&,
                                        const domain::Json&,
                                        const std::string&,
                                        const std::string&,
                                        const project::ModelClock&) {
    freeze_stub("build_snapshot");
}

project::VersionSet finalize_map_version(domain::Json&, const std::string&,
                                         const FinalizeOptions&,
                                         const FinalizeDeps&) {
    freeze_stub("finalize_map_version");
}

std::optional<project::VersionSnapshot> active_final_snapshot(
    const domain::Json&, const std::string&) {
    freeze_stub("active_final_snapshot");
}

domain::Json version_set_summary(const domain::Json&) {
    freeze_stub("version_set_summary");
}

}  // namespace pwb::workflow_runtime
