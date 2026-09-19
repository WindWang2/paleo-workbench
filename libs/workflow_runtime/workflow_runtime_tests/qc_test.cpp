// CONV-33 轮1 契约冻结测试骨架 — 文件名/测试名/fixture 路径已绑定。
// 轮2 替换为冻结 oracle replay（qc.py + map_qa_rules.py 面：BASIC/EXTENDED
// 规则、make_issue 空间字段、稳定 id upsert、coverage 诚实标记、
// issue_layer_geojson、质心三级兜底）。
#include <iostream>

int main(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "usage: workflow_runtime_qc_test <oracle-fixture.json>\n";
        return 2;
    }
    std::cout << "CONV-33 round-2 wires the qc/map_qa_rules oracle replay "
                 "against "
              << argv[1] << "\n";
    return 0;
}
