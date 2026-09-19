// CONV-33 轮1 契约冻结测试骨架 — 文件名/测试名/fixture 路径已绑定。
// 轮2 替换为冻结 oracle replay（versioning.py 5 例 + version_models
// roundtrip：六道门消息、指纹 sha256[:16]、supersede 链、run→export_ready
// 联动、DTO 键序/None 字节对拍）。
#include <iostream>

int main(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "usage: workflow_runtime_versioning_test <oracle-fixture.json>\n";
        return 2;
    }
    std::cout << "CONV-33 round-2 wires the versioning oracle replay against "
              << argv[1] << "\n";
    return 0;
}
