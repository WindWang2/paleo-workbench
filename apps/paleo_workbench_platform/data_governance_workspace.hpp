#pragma once

// ws0 数据治理闭环 — workspace 接线（薄接线策略：本模块持有治理行为，
// 共享装配文件只加一行调用）。不依赖 AppShell/MainWindow/closure_preview
// —— 轻量 offscreen 测试目标可直接链接。
//
//   * 工具条标签过滤（候选/and-or 过滤 → FilterQuery）与标签管理入口；
//   * 工具条「移出项目」→ 真实软删除流：impact 预检 → 显式确认（可注入
//     decision seam，测试两条路径）→ governance::trash_assets → 刷新；
//   * 多选跟踪（表格 selected_assets_changed）——标签批量与批量移除的
//     操作面；
//   * 行集刷新 → 工具条标签候选。
//
// 回收站视图 = TrashDialog（data.trash 命令打开），不进资产表行集
// （trashed 行由适配层保持排除——表内只看 live 是既有语义）。

#include <functional>
#include <string>
#include <vector>

#include <QString>

#include "closure_data_workspace.hpp"  // StoreProvider

namespace pwb::ui_pages_data {
struct AssetRow;
}

namespace pwb::app::data_governance {

struct Install {
    pwb::ui_pages_data::qt::DataWorkspace* workspace = nullptr;
    pwb::ui_pages_data::qt::AssetSelectionBus* bus = nullptr;
    v14_lineage::StoreProvider store;                 // lazy store getter
    QWidget* dialog_parent = nullptr;                 // may be null (tests)
    std::function<void()> refresh_notify;             // closure refresh
    std::function<void(const QString&)> status;       // shell status bar
    // 破坏性确认 seam：默认 QMessageBox；测试注入。收到 impact 摘要，
    // 返回是否继续。
    std::function<bool(const QString& impact_text)> confirm_destructive;
};

void install_data_governance(const Install& install);

// 软删除流（toolbar 移除按钮 + 测试直接驱动）。返回是否成功落库。
// 流程：按资产聚合 impact（live 下游/关联实体）→ 有依赖时 decision
// 确认 → governance::trash_assets（保留 entity links）→ 刷新。
bool run_trash_flow(
    const Install& install,
    const std::vector<pwb::ui_pages_data::AssetRow>& rows,
    const std::string& reason);

}  // namespace pwb::app::data_governance
