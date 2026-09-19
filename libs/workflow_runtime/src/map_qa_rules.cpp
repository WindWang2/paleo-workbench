// CONV-33 轮1 契约桩 — map_qa_rules.hpp 的 fail-loud 占位实现（轮2 替换；
// 定义参数匿名，形参名以头文件声明为准）。
#include "pwb/workflow_runtime/map_qa_rules.hpp"

#include <stdexcept>

namespace pwb::workflow_runtime {
namespace {

[[noreturn]] void freeze_stub(const char* symbol) {
    throw std::logic_error(std::string("CONV-33 round-2 implements ") +
                           symbol + " (contract freeze stub)");
}

}  // namespace

domain::Json collect_extended_qc_issues(const domain::Json&,
                                        const domain::Json&,
                                        const MapQcInputs&) {
    freeze_stub("collect_extended_qc_issues");
}

domain::Json extended_rule_coverage(const MapQcInputs&) {
    freeze_stub("extended_rule_coverage");
}

domain::Json composition_qa_issues(const domain::Json&) {
    freeze_stub("composition_qa_issues");
}

domain::Json cartographic_issues(const domain::Json&,
                                 const CartographicQaInputs&,
                                 const CartographicQaDelegate&) {
    freeze_stub("cartographic_issues");
}

}  // namespace pwb::workflow_runtime
