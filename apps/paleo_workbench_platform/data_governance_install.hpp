#pragma once

// ws0 数据治理闭环 — ribbon 命令回调体（全壳装配专用）。
//
// 五个 ribbon 命令（data.link_well / data.set_role / data.tags /
// data.impact / data.trash）的执行体在此；ribbon_command_install.cpp 只做
// 注册。依赖 AppShell/AppContext 与 closure_preview 的进程级刷新注册表，
// 因此与全壳目标链接；workspace 级接线见 data_governance_workspace.hpp
//（无壳依赖，轻量测试可直接链接）。
//
// 共同约定：从 context 取 store、从 shell 取 bus；写后统一走
// closure_preview 刷新 + bus republish（面板即时反映 tag/role/link 变化）。

#include <QWidget>

namespace pwb::app {
class AppContext;
class AppShell;
}

namespace pwb::app::data_governance {

void open_link_well_dialog(AppContext* context, AppShell* shell,
                           QWidget* window);
void open_set_role_dialog(AppContext* context, AppShell* shell,
                          QWidget* window);
void open_tags_dialog(AppContext* context, AppShell* shell, QWidget* window);
void open_trash_dialog(AppContext* context, AppShell* shell, QWidget* window);
void focus_impact_tab(AppShell* shell);

}  // namespace pwb::app::data_governance
