// CONV-33 轮1 契约冻结测试骨架 — 文件名/测试名/fixture 路径已绑定。
// 轮2 替换为冻结 oracle replay（tools/oracle/
// generate_workflow_recipe_fixtures.py → 12 例：密钥/绝对路径/SQL/损坏
// JSON 安全门 + save/load 字节级 + clone/diff/inspect + migrate 拒绝）。
#include <iostream>

int main(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "usage: workflow_engine_recipe_test <oracle-fixture.json>\n";
        return 2;
    }
    std::cout << "CONV-33 round-2 wires the recipe oracle replay against "
              << argv[1] << "\n";
    return 0;
}
