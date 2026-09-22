#include "m5_data_install.hpp"

#include "app_context.hpp"
#include "app_shell.hpp"
#include "data_lineage_panel.hpp"

#include <pwb/ui_pages_data/asset_view.hpp>
#include <pwb/ui_pages_data/qt/asset_selection_bus.hpp>
#include <pwb/ui_pages_data/qt/data_detail_panel.hpp>
#include <pwb/ui_pages_data/qt/data_workspace.hpp>
#include <pwb/ui_workstation/workstation_frame.hpp>

#include <QTabWidget>

namespace pwb::app::m5_data {

void install(const Install& install) {
    auto* shell = install.shell;
    auto* workspace =
        shell != nullptr ? shell->data_workspace() : nullptr;
    auto* frame =
        shell != nullptr ? shell->workstation() : nullptr;
    if (workspace == nullptr || frame == nullptr) return;
    auto* bus = workspace->selection_bus();

    // 原型 ws0 右列 = 数据属性（上）+ 数据血缘（下）—— 面板化后两片是
    // 壳层右栏 dock（竖向二分同显，可单独悬浮/停靠）。
    // 数据属性：真实元数据表单（类型/格式/状态/路径/校验），选择走
    // 单一 AssetSelectionBus 权威 —— 与数据表/血缘同一选择。
    auto* detail =
        new pwb::ui_pages_data::qt::DataDetailPanel(workspace);
    if (bus != nullptr) {
        QObject::connect(
            bus, &pwb::ui_pages_data::qt::AssetSelectionBus::
                     current_asset_changed,
            detail,
            [detail](const std::optional<
                     pwb::ui_pages_data::AssetRow>& asset) {
                detail->update_asset(asset);
            });
    }
    frame->install_panel("data_props", detail);

    // 数据血缘：真实版本历史 + 来源关系（DataLineagePanel）。面板自身
    // 对血缘读侧切片缺席降级诚实（PWB_WITH_V14_DATA_LINEAGE 门查询）。
    auto* lineage = new DataLineagePanel(workspace);
    lineage->set_context(install.context);
    if (bus != nullptr) lineage->bind_selection_bus(bus);
    QObject::connect(lineage, &DataLineagePanel::status_message, shell,
                     &AppShell::status_message);
    frame->install_panel("data_lineage", lineage);

    // 原型 ws0 底签「版本历史 | 关联关系」—— 与右列血缘同一权威的另
    // 一视图：第二实例只做数据控制器（自身隐藏），其两个真实页各成一
    // 个 dock；两个实例订阅同一 bus，选择一致。
    auto* bottom_lineage = new DataLineagePanel(workspace);
    bottom_lineage->set_context(install.context);
    if (bus != nullptr) bottom_lineage->bind_selection_bus(bus);
    QObject::connect(bottom_lineage, &DataLineagePanel::status_message,
                     shell, &AppShell::status_message);
    // 先取指针再 reparent —— QTabWidget 页索引随移除前移，按序取会
    // 越界丢页。
    auto* history_page = bottom_lineage->tabs()->widget(0);
    auto* relations_page = bottom_lineage->tabs()->widget(1);
    frame->install_panel("data_history", history_page);
    frame->install_panel("data_relations", relations_page);
    bottom_lineage->hide();  // 控制器壳隐藏，页面已提入各自 dock

    // 属性/血缘已是壳层 dock —— 页内右列占位槽腾空，整列隐藏。
    if (workspace->right_column() != nullptr) {
        workspace->right_column()->hide();
    }
}

}  // namespace pwb::app::m5_data
