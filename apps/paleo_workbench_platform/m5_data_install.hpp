#pragma once

// M5-3 — 数据管理工作区收尾安装：数据属性表单 + 血缘页签挂进
// DataWorkspace 的右列/底部槽，选择状态订阅 AssetSelectionBus（单
// 一权威）。血缘面板对读侧切片缺席自降级，故装配无条件。

class QMainWindow;

namespace pwb::app {

class AppShell;
class AppContext;

namespace m5_data {

struct Install {
    QMainWindow* window = nullptr;
    AppShell* shell = nullptr;
    AppContext* context = nullptr;
};

void install(const Install& install);

}  // namespace m5_data

}  // namespace pwb::app
