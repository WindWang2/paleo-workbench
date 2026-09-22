#pragma once

// M5-2 — 综合编图 ws3 的版式轻量页 + 上下文 Ribbon 组安装：
//
//   * LayoutComposePanel 挂进 ws3 底部栈第 2 页（版式模式才显示，
//     F:70），chrome 读写骑活动编图文档的 map_chrome（单一状态），
//     导出入口复用 governed map_export（D4）；
//   * 编图场景选中（MapEditScene::selection_ids_changed — 真实选中
//     信号）驱动上下文组：line（约束线）→ ws2/ws3「约束线编辑」组
//     （物源线/展布线/捕捉），label（标注）→ ws3「标注」组；
//     无选中即清除（R:33 不新增顶层工作区、主按钮不跳位）。
//
// 仅在 PWB_WITH_CLOSURE_MAPPING 构建中编译实体；其它构建保持 M4 的
// 诚实禁用原因。

class QMainWindow;

namespace pwb::app {

class AppShell;
class AppContext;

namespace m5_compose {

struct Install {
    QMainWindow* window = nullptr;
    AppShell* shell = nullptr;
    AppContext* context = nullptr;
};

void install(const Install& install);

}  // namespace m5_compose

}  // namespace pwb::app
