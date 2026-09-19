// CONV-33 轮1 契约冻结测试骨架 — 文件名/测试名/fixture 路径已绑定。
// 轮2 替换为冻结 oracle replay（service.py 8 例 + issue847 overlay +
// orchestrator 3 例 + 拒绝矩阵 10 例：步骤状态两层叠加、就地回写保留
// 规则、游标推进/拒绝消息逐字）。
#include <iostream>

int main(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "usage: workflow_runtime_service_test <oracle-fixture.json>\n";
        return 2;
    }
    std::cout << "CONV-33 round-2 wires the service/orchestrator oracle "
                 "replay against "
              << argv[1] << "\n";
    return 0;
}
