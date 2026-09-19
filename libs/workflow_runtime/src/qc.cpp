// CONV-33 轮1 契约桩 — qc.hpp 的 fail-loud 占位实现（轮2 替换；
// 定义参数匿名，形参名以头文件声明为准）。
#include "pwb/workflow_runtime/qc.hpp"

#include <stdexcept>

namespace pwb::workflow_runtime {
namespace {

[[noreturn]] void freeze_stub(const char* symbol) {
    throw std::logic_error(std::string("CONV-33 round-2 implements ") +
                           symbol + " (contract freeze stub)");
}

}  // namespace

domain::Json make_issue(std::string_view, std::string_view, std::string_view,
                        const QcIssueFields&) {
    freeze_stub("make_issue");
}

domain::Json spatial_issues(const domain::Json&) {
    freeze_stub("spatial_issues");
}

domain::Json issue_layer_geojson(const std::optional<project::QualityReport>&,
                                 const std::optional<std::string>&) {
    freeze_stub("issue_layer_geojson");
}

project::QualityReport run_basic_qc(domain::Json&, const std::string&, bool,
                                    const QcRunDeps&) {
    freeze_stub("run_basic_qc");
}

std::vector<project::QualityReport> active_quality_reports(
    const domain::Json&) {
    freeze_stub("active_quality_reports");
}

project::QualityReport run_map_qc(domain::Json&, const std::string&, bool,
                                  const MapQcInputs&, const QcRunDeps&) {
    freeze_stub("run_map_qc");
}

}  // namespace pwb::workflow_runtime
