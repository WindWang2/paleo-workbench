#pragma once

// M5-3 — 数据管理工作区收尾安装：版本历史/来源关系面板挂进
// DataWorkspace 的 inspector 槽，选择状态订阅 AssetSelectionBus（单
// 一权威）。仅 PWB_WITH_V14_DATA_LINEAGE 构建（血缘读侧符号所在）。

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
